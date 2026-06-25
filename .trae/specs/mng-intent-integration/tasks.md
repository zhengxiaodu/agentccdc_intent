# Tasks

- [ ] Task 1: WorkspaceManager 集成
  - [ ] 1.1 在 `.env` 中新增 `WS_MANAGER_TYPE`（`local`/`docker`）、`WS_BASEDIR`（默认 `./workspaces`）、`WS_TTL`（默认 `3600`）
  - [ ] 1.2 在 `config.py` 中读取并导出 workspace 配置项
  - [ ] 1.3 新建 `app/services/workspace_service.py`：封装 `WorkspaceService` 类
    - 根据配置初始化 `LocalWorkspaceManager` 或 `DockerWorkspaceManager`
    - 提供 `get_workspace(user_id, agent_id, session_id)` 方法，key 格式 `{user_id}/{agent_id}/{session_id}`
    - 提供 `release_workspace(key)` 方法（可选，Manager 自带 TTL 淘汰）
  - [ ] 1.4 重构 `app/agents/registry.py`：
    - `AgentRegistry` 接受 `WorkspaceService` 而非直接创建 `LocalWorkspace`
    - `create_agent()` 通过 `WorkspaceService.get_workspace()` 获取 workspace 传给 Agent
    - Agent 构造时传入 workspace 参数（`toolkit` 从 workspace 获取）
  - [ ] 1.5 修改 `app/main.py`：
    - 启动时初始化 `WorkspaceService` 替代直接创建 `LocalWorkspace`
    - `AgentRegistry` 通过 `WorkspaceService` 获取 workspace
    - `load_all_skills()` 不再直接创建 `LocalWorkspace`，改为从 `WorkspaceService` 获取基础 skill workspace

- [ ] Task 2: 登录接口保存 token/permissions 到 Redis
  - [ ] 2.1 修改 `auth.py`/`user_dao.py`：登录成功后，将 `access_token` 和 `permissions` 存入 Redis，key `user:permissions:{user_id}`，TTL 与 JWT 一致
  - [ ] 2.2 新增 `get_user_permissions(user_id)` 工具函数从 Redis 读取用户权限

- [ ] Task 3: 实现 /chat 时动态加载配置的运行时上下文
  - [ ] 3.1 新建 `app/services/runtime_context.py`：
    - 定义 `RuntimeChatContext` 数据类（合并后的 intent configs、外部 agent 定义、用户权限）
    - 实现 `build_runtime_context(user_id)`：从文件加载基础 intent config、从 Redis 读权限、从 MNG 获取外部意图 → 合并过滤 → 返回 context
    - 实现 `apply_context(orchestrator_service, context)`：注入外部 agent 到 registry，重建 recognizer
    - 实现 `cleanup_context(orchestrator_service, context)`：清理外部 agent
  - [ ] 3.2 修改 `orchestrator_service.py`：支持运行时上下文的 apply/cleanup
  - [ ] 3.3 修改 `/chat` 路由：在 `stream()` 中构建运行时上下文并应用/清理

- [ ] Task 4: MNG 外部意图获取与权限过滤
  - [ ] 4.1 新建 `app/services/mng_intent_service.py`：`fetch_mng_intents()` 调用 MNG `/api/intents` GET 接口
  - [ ] 4.2 实现 `build_external_configs()`：解析 MNG 数据，构建 intent/agent/skill 配置，应用白名单/黑名单过滤
  - [ ] 4.3 在 `AgentRegistry` 中新增 `register_external_agent()` / `unregister_external_agent()` 方法

- [ ] Task 5: .env 和 config.py 新增 external_skills_dir 配置项
  - [ ] 5.1 `.env` 添加 `EXTERNAL_SKILLS_DIR=./external_skills`
  - [ ] 5.2 `config.py` 读取并导出 `EXTERNAL_SKILLS_DIR`

- [ ] Task 6: 验证 agent_id 走内存配置
  - [ ] 6.1 验证外部 agent_id 能在运行时上下文中找到并执行
  - [ ] 6.2 验证被权限过滤移除的 agent_id 返回正确错误
  - [ ] 6.3 基础 agent_id 行为不变

## Task Dependencies
- Task 1 是 Task 3 的前置（workspace 管理重构会影响到 agent 创建流程）
- Task 5 是 Task 4 的前置（external_skills_dir 需先就绪）
- Task 2 是 Task 3 的前置（权限需先存入 Redis）
- Task 3 和 Task 4 可以并行实现
- Task 6 为验证项，依赖 Task 3/4 完成