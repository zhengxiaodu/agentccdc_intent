# Checklist

- [ ] R1.1: 登录成功调用 MNG 接口后，`access_token` 和 `permissions` 正确存入 Redis（key: `user:permissions:{user_id}`）
- [ ] R1.2: Redis 中存储的权限数据 TTL 与 JWT 过期时间一致
- [ ] R1.3: 能从 Redis 正确查询用户的 `agent_whitelist` 和 `skill_blacklist`
- [ ] R1.4: `AUTH_MOCK=true` 时使用模拟数据（向后兼容）；`AUTH_MOCK=false` 时调用 MNG 接口

- [ ] R2.1: `.env` 中存在 `EXTERNAL_SKILLS_DIR` 配置项，默认值为 `./external_skills`
- [ ] R2.2: `config.py` 正确导出 `EXTERNAL_SKILLS_DIR` 常量

- [ ] R3.1: 每次 `/chat` 请求开始时，从文件重新加载 `intent_config.yml` 作为基础 intent 配置
- [ ] R3.2: 从 MNG `/api/intents` 获取外部意图并与基础 intent 合并
- [ ] R3.3: `RuntimeChatContext` 正确持有合并后的 intent 配置、外部 agent 定义、用户权限
- [ ] R3.4: 外部 agent 定义在 `/chat` 开始前注入 `AgentRegistry`，问答结束后清理
- [ ] R3.5: `IntentRecognizer` 在每次 `/chat` 时使用合并后的 intent 配置重建

- [ ] R4.1: MNG `/api/intents` 的响应正确解析，外部 intent/agent/skill 结构正确构建
- [ ] R4.2: 外部 intent 的 id 使用 `intentCode` 字段
- [ ] R4.3: 外部 agent 的 id 使用 `agent.code` 字段，构建为 `AgentDefinition`
- [ ] R4.4: 外部 skill 的 directory 设为 `{EXTERNAL_SKILLS_DIR}/{skill.code}`
- [ ] R4.5: 外部 agent 不在 `agent_whitelist` 中时被移除，对应 intent 中清除关联
- [ ] R4.6: 外部 skill 在 `skill_blacklist` 中时被移除，对应 agent 中清除关联
- [ ] R4.7: intent 下所有 agent 都被移除时，该 intent 不加入配置
- [ ] R4.8: 外部 intent 追加在基础 intent 之后，两者在 `IntentRecognizer` 中同时生效

- [ ] R5.1: 传入外部 agent_id 时，能从运行时上下文中找到 agent 定义并正常执行
- [ ] R5.2: 传入被权限过滤移除的外部 agent_id 时，返回正确的错误事件
- [ ] R5.3: 传入基础 agent_id 时，行为与之前一致（不依赖 MNG）

- [ ] 集成：所有模块编译通过，无 import 错误
- [ ] 集成：完整的登录 → /chat（含外部意图识别 + 外部 agent 问答）流程可正常运行