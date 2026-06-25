# Tasks

- [ ] Task 1: 登录接口调用 MNG 并持久化 token/permissions 到 Redis
  - [ ] 1.1 修改 `verify_login`：当 `AUTH_MOCK=false` 时调用 MNG 登录接口获取完整响应（含 `access_token` + `permissions`）
  - [ ] 1.2 在 `auth.py` 登录成功后，将 `access_token` 和 `permissions` 存入 Redis，key 格式 `user:permissions:{user_id}`，TTL 与 JWT 一致
  - [ ] 1.3 新增 `get_user_permissions(user_id)` 工具函数，从 Redis 读取用户权限
  - [ ] 1.4 调整 `LoginResponse` 模型，将 `agent_access`/`skills_blacklist` 替换为 `permissions`（或兼容处理）

- [ ] Task 2: .env 和 config.py 新增 external_skills_dir 配置项
  - [ ] 2.1 在 `.env` 中添加 `EXTERNAL_SKILLS_DIR=./external_skills`
  - [ ] 2.2 在 `config.py` 中读取并导出 `EXTERNAL_SKILLS_DIR`

- [ ] Task 3: 实现 /chat 时动态加载配置的运行时上下文
  - [ ] 3.1 定义 `RuntimeChatContext` 数据类，包含：
    - 合并后的 `intent_configs: List[IntentConfig]`
    - 动态追加的外部 agent 定义列表
    - 当前用户的 `agent_whitelist` / `skill_blacklist`
    - 清理方法 `cleanup()`
  - [ ] 3.2 实现 `build_runtime_context(user_id)` 服务函数：
    - 从文件加载基础 `intent_config.yml`
    - 从 Redis 读取用户权限
    - 从 MNG `/api/intents` 获取外部意图
    - 合并并应用权限过滤 → 返回 `RuntimeChatContext`
  - [ ] 3.3 修改 `OrchestratorService`：
    - 新增 `run_with_context()` 方法，接受 `RuntimeChatContext` 参数
    - 每次调用时重建 `IntentRecognizer`（使用合并后的 intent_configs）
    - 调用前将外部 agent 定义注入 `AgentRegistry`，调用后清理
  - [ ] 3.4 修改 `/chat` 路由，在 `stream()` 中构建运行时上下文并传递给 `generate_response`

- [ ] Task 4: 实现 MNG 外部意图获取与权限过滤
  - [ ] 4.1 实现 `fetch_mng_intents()` 函数：调用 MNG `/api/intents` GET 接口
  - [ ] 4.2 实现 `build_external_configs(mng_data, whitelist, blacklist)` 函数：
    - 对每项外部 intent，构建 `IntentConfig`
    - 对每项外部 agent，检查白名单：不在白名单中则移除，断开关联
    - 对每项外部 skill，检查黑名单：在黑名单中则移除，断开关联
    - 外部 skill 的 directory 设为 `{EXTERNAL_SKILLS_DIR}/{skill.code}`
    - 返回 `(external_intents, external_agents)`
  - [ ] 4.3 实现 `merge_configs(base_intents, external_intents, external_agents)`：
    - 外部 intent 追加到 base_intents 末尾
    - 保持 intent-agent-skill 关联关系
  - [ ] 4.4 在 `AgentRegistry` 中添加 `register_external_agent(def)` 和 `unregister_external_agent(agent_id)` 方法

- [ ] Task 5: 验证 agent_id 走内存配置
  - [ ] 5.1 验证：传入外部 agent_id 时，能从运行时上下文中找到 agent 定义
  - [ ] 5.2 验证：外部 agent_id 在权限过滤后被移除时，返回正确的错误事件
  - [ ] 5.3 这是 Task 3 和 Task 4 的验证项，不需要额外代码修改

## Task Dependencies
- Task 2 是 Task 3/4 的前置依赖（配置项需先就绪）
- Task 1 是 Task 3 的前置依赖（权限需要在 login 时先存入 Redis）
- Task 4 依赖于 Task 2 和 Task 1
- Task 3 和 Task 4 可以并行实现（有公共依赖，但代码层面解耦）
- Task 5 是验证项，依赖 Task 3 和 Task 4 完成