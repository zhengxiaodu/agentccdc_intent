# 迁移计划：Redis → PostgreSQL 持久化存储

## 摘要

将会话存储后端从 Redis 切换到 PostgreSQL，包括会话状态（AgentState）、会话元信息、会话消息列表，以及用户会话索引（置顶/非置顶列表）。所有 `/session` API 接口保持不变。

**Redis 保留不变**，仅把 SessionDAO 的数据层从 Redis 迁移到 PostgreSQL。

---

## 一、当前状态分析

### 数据流

```
前端 API (routes/sessions.py, routes/chat.py)
    → SessionService (services/session_service.py)  # 不变
        → SessionDAO (dao/session_dao.py)           # 重写为 PostgreSQL 版本
            → Redis → 改为 → PostgreSQL
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
3. AgentScope 原生的 `get_session` 和 `update_session_state` 的接口签名：
   - `get_session(user_id, agent_id, session_id) -> SessionRecord | None`
   - `update_session_state(user_id, agent_id, session_id, state: AgentState) -> None`
4. 当前代码存在一个问题：**每次问答 AgentState 都是新建的，从未保存/恢复**。BaseOrchestrator._run_single_agent() 创建 agent 时没有传入 agent_state，registry.create_agent() 在 agent_state=None 时会新建 `AgentState()`

---

## 二、目标设计

### 数据库表结构

#### `sessions` 表（替代 Redis 的 state + meta + 用户索引 + 置顶索引）

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    message_count INTEGER NOT NULL DEFAULT 0,
    latest_trace_id TEXT,
    agent_id     TEXT,
    state        JSONB,              -- AgentState 完整序列化
    is_pinned    BOOLEAN NOT NULL DEFAULT FALSE,
    pinned_at    TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user_pinned ON sessions(user_id, pinned_at DESC) WHERE is_pinned = TRUE;
```

> `agent_id` 列新增，用于支持按 (user_id, agent_id, session_id) 查找状态

#### `messages` 表（替代 Redis 的 session_msgs）

```sql
CREATE TABLE IF NOT EXISTS messages (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role         TEXT NOT NULL,       -- 'user' 或 'assistant'
    content      TEXT NOT NULL,
    timestamp    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(session_id, timestamp);
```

### PostgreSQL 配置

写入 `.env` 文件（如不存在则创建）：

```
# PostgreSQL 配置
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=zxdzxd.123
PG_DATABASE=agentscope
PG_DSN=postgresql+asyncpg://postgres:zxdzxd.123@localhost:5432/agentscope
```

---

## 三、文件变更清单

### 1. 新建: `app/dao/pg_session_dao.py`

使用 `asyncpg` 连接池替代 Redis。需要实现的方法（保持与现有 SessionService 兼容）：

| 方法 | 说明 |
|---|---|
| `__init__(pg_pool)` | 接收 asyncpg 连接池 |
| `session_exists(session_id) -> bool` | 检查会话是否存在 |
| `load_agent_state(session_id) -> dict\|None` | 从 sessions.state 加载 AgentState JSON |
| `save_agent_state(session_id, user_id, state_dict)` | 将 AgentState 写入 sessions.state |
| `load_messages(session_id) -> list[dict]` | 从 messages 表查询消息列表 |
| `append_messages(session_id, user_id, messages)` | 向 messages 表插入消息 + 更新 sessions 元信息 |
| `save_latest_trace_id(session_id, trace_id)` | 更新 sessions.latest_trace_id |
| `get_session_meta(session_id) -> dict\|None` | 查 sessions 行返回元信息 |
| `list_user_sessions(user_id, limit) -> (top, sessions)` | 按 user_id 查 sessions，is_pinned 区分置顶/非置顶 |
| `pin_session(user_id, session_id)` | UPDATE is_pinned=true, pinned_at=now() |
| `unpin_session(user_id, session_id)` | UPDATE is_pinned=false, pinned_at=null |
| `delete_session(session_id, user_id)` | DELETE FROM sessions（CASCADE 自动删 messages） |
| `extract_messages_from_state(state_dict)` | **保持静态方法不变，从旧文件复制** |

### 2. 新增: `get_session` 和 `update_session_state`（AgentScope 原生接口）

```python
async def get_session(
    self, user_id: str, agent_id: str, session_id: str
) -> Optional[dict]:
    """加载 SessionRecord（dict 格式），其 .state 字段为 AgentState"""
    row = await self.pool.fetchrow(
        "SELECT * FROM sessions WHERE session_id = $1 AND user_id = $2",
        session_id, user_id
    )
    if row is None:
        return None
    return dict(row)

async def update_session_state(
    self, user_id: str, agent_id: str, session_id: str, state: AgentState
) -> None:
    """将 AgentState 持久化到 sessions.state 列"""
    state_json = json.dumps(state.model_dump(), ensure_ascii=False, default=str)
    await self.pool.execute(
        "UPDATE sessions SET state = $1::jsonb, updated_at = NOW() "
        "WHERE session_id = $2 AND user_id = $3",
        state_json, session_id, user_id
    )
```

### 3. 修改 `app/config.py`

**变动**：
- 保留 `REDIS_URL` 和 `REDIS_SESSION_TTL`（Redis 仍可用于其他需求）
- 新增 PostgreSQL 配置变量：
  - `PG_DSN` - 连接字符串
  - `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DATABASE`

### 4. 修改 `app/main.py`

**变动**：
- **保留** Redis 客户端初始化（`redis_client = aioredis.from_url(REDIS_URL, ...)`）
- 新增 PostgreSQL 连接池初始化（`pg_pool = await asyncpg.create_pool(dsn=PG_DSN, ...)`）
- SessionDAO 改为接收 pg_pool
- 启动时自动执行建表
- 关闭时关闭 pg_pool（同时保留 redis_client.close）

```python
# main.py 生命周期变化
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 模型初始化 ...
    # ... 编排服务初始化 ...

    # Redis 仍然保留（用于其他需求）
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=False)
    app.state.redis_client = redis_client

    # PostgreSQL 连接池（用于会话持久化）
    pg_pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=2, max_size=10)
    await _init_pg_tables(pg_pool)  # 自动建表
    app.state.pg_pool = pg_pool
    app.state.session_dao = SessionDAO(pg_pool)  # 改用 PG
    app.state.session_service = SessionService(app.state.session_dao)

    yield

    await pg_pool.close()
    await redis_client.close()
```

### 5. 修改 `app/services/chat_service.py` — AgentState 保存/恢复

**这是本次迁移的核心逻辑变更**。

当前流程：orchestrator_service.run() 内部创建 Agent 时没有传入 agent_state → AgentState 每次新建

改造后流程：
```
1. generate_response() 开始：
   a. 根据 session_id 从 PostgreSQL 加载已有的 AgentState JSON
   b. 若存在 → AgentState.model_validate(state_dict)
   c. 若不存在 → AgentState(session_id=session_id, permission_context=...)

2. 调用 orchestrator_service.run() 时，通过 session_id 传递 agent_state
   （或修改 orchestrator 内部，创建 agent 时加载已有的 state）

3. generate_response() 流结束后：
   a. 从已执行的 agent 获取更新后的 state
   b. 调用 session_service.save_agent_state() 持久化到 sessions.state
```

具体实现方案：
- 在 `chat_service.py` 的 `generate_response()` 中：
  - 在调用 `orchestrator_service.run()` **之前**，先加载 agent_state
  - 将 agent_state 通过 orchestrator 传递给 `_run_single_agent()` → `create_for_agent()`
  - 在流结束**之后**，保存 agent 的最终 state

- 在 orchestrator 的 `_run_single_agent()` 中：
  - 增加 `agent_state` 参数，传递给 `agent_factory.create_for_agent()`

### 6. 新建: `app/dao/init_pg.sql`

SQL 初始化脚本，包含 CREATE TABLE IF NOT EXISTS 语句。

### 7. 修改 `requirements.txt`

新增依赖：
```
asyncpg>=0.29.0
```

### 8. 修改 `.env` 文件

新增 PostgreSQL 配置段。

---

## 四、实施步骤

### 步骤 1: 安装 asyncpg 并验证连接

```bash
pip install asyncpg
PGPASSWORD=zxdzxd.123 psql -h localhost -U postgres -d agentscope -c "SELECT 1"
```

### 步骤 2: 创建数据库表

执行 `app/dao/init_pg.sql` 建表。同时在 main.py 中自动执行。

### 步骤 3: 新建 `app/dao/pg_session_dao.py`

完整实现 PostgreSQL 版的 SessionDAO，包含：
- 所有现有 SessionDAO 方法（用 SQL 替代 Redis 命令）
- 新增 `get_session()` 和 `update_session_state()`
- 保留 `extract_messages_from_state()` 静态方法

### 步骤 4: 修改 `app/config.py`

新增 PostgreSQL 配置变量；保留 Redis 配置。

### 步骤 5: 修改 `app/main.py`

- 保留 Redis 初始化
- 新增 PostgreSQL 连接池
- SessionDAO 改用 PostgreSQL
- 启动自动建表

### 步骤 6: 修改 `app/services/chat_service.py`

添加 AgentState 的保存/恢复逻辑。

### 步骤 7: 验证 API

验证：
- `GET /sessions` — 列表
- `GET /sessions/{session_id}` — 详情含消息
- `PUT /sessions/{session_id}/pin` — 置顶
- `DELETE /sessions/{session_id}` — 删除
- `POST /chat` — 会话持久化 + 状态重建

---

## 五、关键决策

| 决策 | 说明 |
|---|---|
| **保留 Redis** | Redis 客户端继续初始化，SessionDAO 改用 PG，Redis 留作其他用途 |
| **使用 asyncpg** | 异步 PostgreSQL 驱动，与 FastAPI asyncio 兼容 |
| **state 存 JSONB** | AgentState.model_dump() → JSON 存入 JSONB 列 |
| **消息存独立表** | 支持按需分页查询，CASCADE 自动清理 |
| **自动建表** | 应用启动时 CREATE TABLE IF NOT EXISTS，无需手动迁移 |
| **sessions 表加 agent_id 列** | 支持按 (user_id, agent_id, session_id) 查询状态 |
| **不迁移旧数据** | Redis TTL 数据不迁移到 PG |

---

## 六、验证步骤

1. 启动服务: `python app/main.py`
2. 首次启动后检查 `sessions` 和 `messages` 表是否自动创建
3. POST /chat 发送消息 → 检查 sessions 表有记录、messages 表有消息、state 列有 JSON
4. GET /sessions → 返回会话列表
5. GET /sessions/{id} → 返回会话详情+消息
6. PUT /sessions/{id}/pin → is_pinned 状态变化
7. DELETE /sessions/{id} → 级联删除 messages
8. 再次 POST /chat 使用相同 session_id → AgentState 应正确恢复（包含历史上下文）