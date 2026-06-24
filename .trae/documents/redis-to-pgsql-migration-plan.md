# 迁移计划：Redis → PostgreSQL 持久化存储

## 摘要

将会话存储后端从 Redis 切换到 PostgreSQL，包括会话状态（AgentState）、会话元信息、会话消息列表，以及用户会话索引（置顶/非置顶列表）。所有 `/session` API 接口保持不变。

---

## 一、当前状态分析

### 数据流

```
前端 API (routes/sessions.py, routes/chat.py)
    → SessionService (services/session_service.py)  # 不变
        → SessionDAO (dao/session_dao.py)           # 需要重写
            → Redis (config.py: REDIS_URL)
```

### 当前 Redis 存储的数据结构

| 逻辑数据 | Redis Key | 类型 | 说明 |
|---|---|---|---|
| AgentState JSON | `session:{session_id}` | String (JSON) | AgentState.model_dump() 后的完整 JSON |
| Session 元信息 | `session_meta:{session_id}` | String (JSON) | user_id, name, created_at, updated_at, message_count, latest_trace_id |
| 消息列表 | `session_msgs:{session_id}` | String (JSON) | [{role, content, timestamp}, ...] |
| 用户会话索引 | `user_sessions:{user_id}` | Sorted Set (ZSET) | score=更新时间戳, member=session_id |
| 置顶索引 | `pinned_sessions:{user_id}` | Sorted Set (ZSET) | score=置顶时间戳, member=session_id |

### 关键发现

1. `AgentState` 是 Pydantic BaseModel（agentscope.state.AgentState），可直接 `model_dump()` 序列化为 JSON → 存入 JSONB 列
2. 当前项目**没有使用** AgentScope 内置的 `RedisStorage`，而是自行实现了 `SessionDAO`
3. AgentScope 原生的 `get_session` 和 `update_session_state` 的接口签名已从 `_redis_storage.py` 确认：
   - `get_session(user_id, agent_id, session_id) -> SessionRecord | None`
   - `update_session_state(user_id, agent_id, session_id, state: AgentState) -> None`
4. Offloader 协议定义了两个方法：`offload_context(session_id, msgs)` 和 `offload_tool_result(session_id, tool_result)` — 用于上下文的卸载到 workspace

---

## 二、目标设计

### 数据库表结构

#### `sessions` 表（替代 Redis 的 state + meta + 用户索引 + 置顶索引）

```sql
CREATE TABLE sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    message_count INTEGER NOT NULL DEFAULT 0,
    latest_trace_id TEXT,
    state        JSONB,              -- AgentState 完整序列化
    is_pinned    BOOLEAN NOT NULL DEFAULT FALSE,
    pinned_at    TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_updated_at ON sessions(updated_at DESC);
CREATE INDEX idx_sessions_user_pinned ON sessions(user_id, pinned_at DESC) WHERE is_pinned = TRUE;
```

#### `messages` 表（替代 Redis 的 session_msgs）

```sql
CREATE TABLE messages (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role         TEXT NOT NULL,       -- 'user' 或 'assistant'
    content      TEXT NOT NULL,
    timestamp    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_session_id ON messages(session_id);
CREATE INDEX idx_messages_timestamp ON messages(session_id, timestamp);
```

### PostgreSQL 配置

写入 `.env` 文件（不存在则创建）：

```
# PostgreSQL 配置
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=zxdzxd.123
PG_DATABASE=agentscope
PG_DSN=postgresql+asyncpg://postgres:zxdzxd.123@localhost:5432/agentscope
```

> **注意**：`postgresql+asyncpg://` 是 asyncpg 的 DSN 格式前缀

---

## 三、文件变更清单

### 1. 新建数据库初始化脚本

**文件**: `app/dao/pg_session_dao.py` (新文件)

重写 SessionDAO，使用 `asyncpg` 替代 Redis。保持与现有 `SessionService` 兼容的接口。

需要实现的方法（与当前 SessionDAO 签名完全一致）：

| 方法 | 说明 |
|---|---|
| `session_exists(session_id) -> bool` | 检查会话是否存在 |
| `load_agent_state(session_id) -> dict\|None` | 加载 AgentState JSON |
| `save_agent_state(session_id, user_id, state_dict)` | 保存 AgentState |
| `load_messages(session_id) -> list[dict]` | 加载消息列表 |
| `append_messages(session_id, user_id, messages)` | 追加消息 |
| `save_latest_trace_id(session_id, trace_id)` | 保存 trace_id |
| `session_exists(session_id) -> bool` | 已存在 |
| `get_session_meta(session_id) -> dict\|None` | 获取元信息 |
| `list_user_sessions(user_id, limit) -> (top, sessions)` | 列出用户会话 |
| `pin_session(user_id, session_id)` | 置顶 |
| `unpin_session(user_id, session_id)` | 取消置顶 |
| `delete_session(session_id, user_id)` | 删除会话 |
| `extract_messages_from_state(state_dict) -> list` | 从 state 提取消息(静态方法,不需要改) |

### 2. 新增: `get_session` 和 `update_session_state`（AgentScope 原生接口）

这两个方法直接映射到 `sessions` 表的 state JSONB 列：

```python
async def get_session(
    self, user_id: str, agent_id: str, session_id: str
) -> Optional[dict]:
    """加载 SessionRecord，返回包含 .state 字段的 dict。
    
    对应 AgentScope 原生 RedisStorage.get_session() 语义。
    """
    ...

async def update_session_state(
    self, user_id: str, agent_id: str, session_id: str, state: AgentState
) -> None:
    """在 reply 结束后将更新后的 AgentState 持久化回数据库。
    
    对应 AgentScope 原生 RedisStorage.update_session_state() 语义。
    """
    ...
```

### 3. 修改 `app/config.py`

**变动**：
- 移除 `REDIS_URL` 和 `REDIS_SESSION_TTL`（或保留以兼容旧代码，但不再使用）
- 新增 PostgreSQL 配置变量：`PG_DSN`, `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DATABASE`
- 新增 `PG_SESSION_TTL` 可选（用于软删除 / 归档策略，非必需）

### 4. 修改 `app/main.py`

**变动**：
- 移除 Redis 客户端初始化（`aioredis.from_url(...)`）
- 替换为 PostgreSQL 连接池初始化（`asyncpg.create_pool(...)`）
- `SessionDAO` 初始化参数从 `redis_client` 改为 `pg_pool`
- 关闭逻辑从 `redis_client.close()` 改为 `pg_pool.close()`

### 5. 修改 `.env` 文件

新增 PostgreSQL 配置（见上文）。

### 6. 修改 `requirements.txt`

新增依赖：
```
asyncpg>=0.29.0
```

### 7. 数据库迁移脚本

提供 SQL 初始化脚本 `app/dao/init_pg.sql`，包含建表语句。应用启动时自动执行建表（CREATE TABLE IF NOT EXISTS）。

---

## 四、实施步骤

### 步骤 1: 安装 asyncpg 并验证数据库连接

```bash
pip install asyncpg
python3 -c "import asyncpg; print(asyncpg.__version__)"
```

### 步骤 2: 创建数据库表

连接 PostgreSQL 并执行建表 SQL。可选通过启动脚本自动执行。

### 步骤 3: 重写 `app/dao/session_dao.py` → 新建 `pg_session_dao.py`

1. 将 `__init__` 从接收 Redis client 改为接收 asyncpg 连接池
2. 使用 SQL 查询替换每个 Redis 操作
3. `list_user_sessions` 使用 `WHERE user_id = $1 ORDER BY updated_at DESC` 替代 ZSET
4. `pin_session` / `unpin_session` 使用 `UPDATE sessions SET is_pinned = TRUE/FALSE`
5. `delete_session` 使用 `DELETE FROM sessions WHERE session_id = $1`（CASCADE 会自动删除 messages）
6. `load_messages` / `append_messages` 改为操作 `messages` 表

### 步骤 4: 更新 `app/main.py` 生命周期

```python
# 替换
redis_client = aioredis.from_url(REDIS_URL, ...)
app.state.redis_client = redis_client
app.state.session_dao = SessionDAO(redis_client)

# 改为
pg_pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=2, max_size=10)
app.state.pg_pool = pg_pool
app.state.session_dao = SessionDAO(pg_pool)
```

关闭逻辑：
```python
# 替换 redis_client.close()
await pg_pool.close()
```

### 步骤 5: 添加 `get_session` 和 `update_session_state` 方法

在 `pg_session_dao.py` 中添加，供 AgentScope Agent 原生调用。

### 步骤 6: 验证 API 接口

验证以下端点功能正常：
- `GET /sessions` — 列表用户会话（置顶 + 非置顶）
- `GET /sessions/{session_id}` — 会话详情（含消息历史）
- `PUT /sessions/{session_id}/pin` — 置顶/取消置顶
- `DELETE /sessions/{session_id}` — 删除会话
- `POST /chat` — 聊天（包含历史加载 + 消息持久化）

---

## 五、关键决策与假设

| 决策 | 说明 |
|---|---|
| **移除 Redis 依赖** | 完全移除 Redis，不使用双写或中间过渡期 |
| **使用 asyncpg** | 异步 PostgreSQL 驱动，与 FastAPI asyncio 循环兼容 |
| **state 存 JSONB** | AgentState 的序列化格式是 JSON，JSONB 支持索引和部分更新 |
| **消息存独立表** | 相比当前 Redis 的整块 JSON 字符串，独立表支持按需分页查询 |
| **CASCADE 删除** | messages 表通过 FK + ON DELETE CASCADE 关联 sessions，删除会话时自动清理消息 |
| **不使用 ORM** | 直接使用 asyncpg 连接池 + 原生 SQL，保持轻量和可控制 |
| **不处理数据迁移** | 旧 Redis 数据不迁移到 PostgreSQL（主要因为 Redis 数据带有 TTL，大部分可能是过期数据） |

---

## 六、验证步骤

1. 启动服务: `python app/main.py`
2. 创建新会话: 发送 `POST /chat` 请求
3. 获取会话列表: `GET /sessions` → 验证置顶和非置顶排序正确
4. 获取会话详情: `GET /sessions/{session_id}` → 验证消息内容
5. 置顶操作: `PUT /sessions/{session_id}/pin` → 验证列表顺序
6. 删除会话: `DELETE /sessions/{session_id}` → 验证级联删除消息

---

## 七、注意事项

1. **连接池管理**: PostgreSQL 连接池生命周期必须与 FastAPI app lifespan 绑定，确保启动时创建、关闭时释放
2. **事务**: 当前 Redis 操作没有跨 key 事务，PG 实现中 `append_messages` 的消息插入 + meta 更新应在同一事务中执行
3. **并发安全**: asyncpg 连接池是线程安全的，但需注意同一个 session 的并发读写
4. **AgentScope 原生接口**: `get_session` 和 `update_session_state` 的签名参考了 `RedisStorage` 的实现，确保与其他 AgentScope 组件兼容