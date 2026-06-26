# Checklist

## Requirement 1: WorkspaceManager 集成
- [ ] R1.1: `.env` 中存在 `WS_MANAGER_TYPE`、`WS_BASEDIR`、`WS_TTL` 配置项，有合理默认值
- [ ] R1.2: `WS_MANAGER_TYPE=local` 时初始化 `LocalWorkspaceManager`，`=docker` 时初始化 `DockerWorkspaceManager`
- [ ] R1.3: `WorkspaceService.get_workspace(user_id, agent_id, session_id)` 返回隔离的 workspace，key 为 `{user_id}/{agent_id}/{session_id}`
- [ ] R1.4: 同一 key 在 TTL 内重复获取时复用已有 workspace
- [ ] R1.5: `AgentRegistry.create_agent()` 通过 `WorkspaceService` 获取 workspace
- [ ] R1.6: 基础 skill 在 workspace 首次初始化时正确加载

## Requirement 2: 登录 Token/Permissions 持久化
- [ ] R2.1: 登录成功后 `access_token` 和 `permissions` 存入 Redis，key `user:permissions:{user_id}`
- [ ] R2.2: Redis TTL 与 JWT 过期时间一致
- [ ] R2.3: 能从 Redis 正确查询用户的 `agent_whitelist` 和 `skill_blacklist`

## Requirement 3: /chat 动态加载配置
- [ ] R3.1: 每次 `/chat` 从文件重新加载 `intent_config.yml`
- [ ] R3.2: 从 MNG 获取外部意图并与基础 intent 合并
- [ ] R3.3: `RuntimeChatContext` 正确持有合并后的 intent config、外部 agent 定义、用户权限
- [ ] R3.4: 外部 agent 在 `/chat` 开始前注入 `AgentRegistry`，结束后清理
- [ ] R3.5: `IntentRecognizer` 每次使用合并后的 intent config 重建

## Requirement 4: external_skills_dir
- [ ] R4.1: `.env` 中存在 `EXTERNAL_SKILLS_DIR` 配置项
- [ ] R4.2: `config.py` 正确导出 `EXTERNAL_SKILLS_DIR`

## Requirement 5: MNG 外部意图集成与权限过滤
- [ ] R5.1: MNG `/api/intents` 响应正确解析
- [ ] R5.2: 外部 intent.id 使用 `intentCode`
- [ ] R5.3: 外部 agent.id 使用 `agent.code`，构建为 `AgentDefinition`
- [ ] R5.4: 外部 skill.directory 设为 `{EXTERNAL_SKILLS_DIR}/{skill.code}`
- [ ] R5.5: agent 不在白名单中时移除，intent 中清除关联
- [ ] R5.6: skill 在黑名单中时移除，agent 中清除关联
- [ ] R5.7: intent 下所有 agent 被移除时，该 intent 不加入配置
- [ ] R5.8: 外部 intent 追加在基础 intent 之后，两者同时生效

## Requirement 6: agent_id 查询验证
- [ ] R6.1: 传入外部 agent_id 能从运行时上下文找到定义并执行
- [ ] R6.2: 被权限过滤移除的 agent_id 返回正确错误事件
- [ ] R6.3: 基础 agent_id 行为不变

## 集成
- [ ] 所有模块编译通过，无 import 错误
- [ ] 完整的登录 → /chat（含 WorkspaceManager + 外部意图 + 权限过滤 + 动态配置）流程可正常运行