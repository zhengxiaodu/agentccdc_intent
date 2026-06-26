# MNG 意图集成、WorkspaceManager 与运行时配置管理 Spec

## Why

当前系统的 workspace 管理、配置加载和权限体系存在以下问题：

1. **Workspace 管理原始**：使用单例 `LocalWorkspace` 在启动时一次性加载所有 skill，所有 agent 共享同一个 workspace，无法按用户/会话隔离
2. **登录权限未持久化**：MNG 返回的 `access_token` 和 `permissions` 未存入 Redis，后续无法查询用户权限
3. **配置静态加载**：intent/agent/skill 配置仅在启动时加载，无法动态集成 MNG 的外部意图
4. **无运行时权限过滤**：缺乏 agent 白名单 / skill 黑名单机制
5. **外部技能目录不可配置**

## What Changes

### 1. WorkspaceManager 集成（新增）
- 引入 `WorkspaceManagerBase`（`LocalWorkspaceManager` / `DockerWorkspaceManager`）管理 workspace 生命周期
- 按 `user_id` / `agent_id` / `session_id` 多级 Key 分配/复用 workspace
- `.env` 可配置使用哪个 manager 实现（local / docker）
- workspace 的 workdir 使用 `basedir/{user_id}/{agent_id}/{session_id}` 隔离

### 2. 登录时保存 token/permissions 到 Redis
- `/login` 调用 MNG 验证后，将 `access_token` 和 `permissions` 按 `user_id` 保存到 Redis
- 后续通过 Redis Key `user:permissions:{user_id}` 查询权限

### 3. /chat 时动态加载配置到内存
- 每次 `/chat` 请求开始时，从文件加载 `intent_config.yml`，从 MNG 获取外部意图，合并后用于本次问答
- `agent_config.yml` 和 `skill_config.yml` 的基础部分由启动时加载，外部 agent 定义动态注入/清理
- 问答结束后清理外部配置，释放内存

### 4. .env 新增 external_skills_dir
- 新增 `EXTERNAL_SKILLS_DIR` 配置项，默认 `./external_skills`

### 5. MNG 外部意图集成与权限过滤
- 调用 MNG `/api/intents` 获取外部意图
- 构建 YAML 同构配置，合并到内存
- 应用 agent 白名单 / skill 黑名单过滤
- 保持外部 intent-agent-skill 关联关系

### 6. agent_id 走内存配置（验证项）
- 验证 agent_id 查询能从运行时内存配置中正确查找

## Impact

- Affected code:
  - `.env` — 新增 `WS_MANAGER_TYPE`, `WS_BASEDIR`, `WS_TTL`, `EXTERNAL_SKILLS_DIR`
  - `app/config.py` — 新增 workspace 和 external_skills 配置
  - `app/main.py` — 启动时初始化 WorkspaceManager 替代单例 LocalWorkspace
  - `app/services/workspace_service.py` — **新建**：WorkspaceManager 封装层
  - `app/services/runtime_context.py` — **新建**：运行时上下文管理
  - `app/services/mng_intent_service.py` — **新建**：MNG 意图获取与权限过滤
  - `app/agents/registry.py` — 重构为使用 WorkspaceManager 分配 workspace
  - `app/routes/auth.py` — 登录时存权限到 Redis
  - `app/routes/chat.py` — 构建运行时上下文
  - `app/services/orchestrator_service.py` — 支持运行时上下文注入

## ADDED Requirements

### Requirement 1: WorkspaceManager 集成

系统 SHALL 使用 AgentScope 的 WorkspaceManager 管理工作区生命周期，按 `user_id` / `agent_id` / `session_id` 隔离。

#### Scenario: 初始化 WorkspaceManager
- **WHEN** 应用启动
- **THEN** 根据 `.env` 中 `WS_MANAGER_TYPE` 配置（`local` / `docker`）初始化对应的 Manager
- **AND** `WS_MANAGER_TYPE=local` 时使用 `LocalWorkspaceManager`，`=docker` 时使用 `DockerWorkspaceManager`
- **AND** `basedir` 和 `ttl` 从 `.env` 读取

#### Scenario: 分配/复用 Workspace
- **WHEN** `/chat` 请求中需要创建 agent
- **THEN** 以 `{user_id}/{agent_id}/{session_id}` 为 key 向 Manager 申请 workspace
- **AND** 若该 key 对应的 workspace 已存在（TTL 内），则复用
- **AND** 基础 skill 在首次初始化时加载，后续复用不重复加载

#### Scenario: 释放 Workspace
- **WHEN** `/chat` 请求结束
- **THEN** workspace 归还给 Manager，由 Manager 按 TTL 自动淘汰

### Requirement 2: 登录 Token/Permissions 持久化到 Redis

[同前 — 登录成功保存 access_token 和 permissions 到 Redis]

### Requirement 3: /chat 时动态加载配置

[同前 — 每次 /chat 重新加载 intent 配置，合并外部意图，问答结束清理]

### Requirement 4: external_skills_dir 配置项

[同前 — .env 新增配置项]

### Requirement 5: MNG 外部意图集成与权限过滤

[同前 — 从 MNG 获取外部意图，构建配置，权限过滤]

### Requirement 6: agent_id 查询验证

[同前 — 验证 agent_id 从内存配置查询]

## Key Design Decisions

### D1: Workspace 隔离策略
- Key = `{user_id}/{agent_id}/{session_id}`
- 同一用户同一 agent 同一 session 复用同一个 workspace
- Manager 按 TTL 淘汰空闲 workspace

### D2: 配置生命周期
- **基础 skill**：WorkspaceManager 初始化时加载一次，skill 路径从 `skill_config.yml` 读取
- **基础 agent 定义**：启动时加载到 `AgentRegistry`，常驻
- **基础 intent 配置**：每次 `/chat` 从文件重新加载（确保最新）
- **外部 intent/agent/skill**：每次 `/chat` 从 MNG 获取，问答结束后清理

### D3: 权限传递
- 登录时写入 Redis（key: `user:permissions:{user_id}`）
- `/chat` 时从 Redis 读取

### D4: WorkspaceManager 封装
- 不直接使用 agentscope 的 `create_app`（当前已经是自定义 FastAPI 架构）
- 封装 `WorkspaceService` 管理 Manager 的分配/释放
- `AgentRegistry` 通过 `WorkspaceService` 获取 workspace 而非直接创建 `LocalWorkspace`