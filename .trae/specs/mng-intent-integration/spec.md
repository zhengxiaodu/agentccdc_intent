# MNG 意图集成与运行时配置管理 Spec

## Why

当前系统在启动时一次性加载本地 YAML 配置文件（intent_config.yml、agent_config.yml、skill_config.yml）并常驻内存。存在以下问题：

1. 登录接口返回的 `access_token` 和 `permissions` 未持久化，后续无法按用户查询权限
2. 意图/智能体/技能配置仅在启动时加载，无法动态集成来自 MNG 管理系统的外部意图
3. 缺乏运行时权限过滤机制（agent 白名单 / skill 黑名单）
4. 外部技能目录不可配置

## What Changes

### 1. 登录时保存 token/permissions 到 Redis
- `/login` 接口调用 MNG 系统验证后，将返回的 `access_token` 和 `permissions` 按 `user_id` 保存到 Redis
- JWT payload 中不再包含 `agent_access` / `skills_blacklist`，改为从 Redis 查询

### 2. /chat 时动态加载配置
- 每次 `/chat` 请求开始时，从文件系统重新加载 `intent_config.yml`，并从 MNG 获取外部意图配置，合并后用于本次问答
- `agent_config.yml` 和 `skill_config.yml` 仍由应用启动时加载（skill 加载开销大），但 `AgentRegistry` 支持运行时追加/清理外部 agent 定义
- 问答结束后，清理本次注入的外部 intent/agent 配置

### 3. .env 新增 external_skills_dir
- 新增配置项 `EXTERNAL_SKILLS_DIR`，默认值 `./external_skills`
- 用于外部技能的本地路径前缀

### 4. MNG 外部意图集成与权限过滤
- 调用 MNG `/api/intents` 获取外部意图列表
- 将外部 intent 构建为与 `intent_config.yml` 相同的结构并入内存
- 将外部 agent 构建为与 `agent_config.yml` 相同的结构，动态追加到 AgentRegistry
- 将外部 skill 路径指向 `{external_skills_dir}/{skill.code}`
- 权限过滤：agent 不在 `permissions.agent_whitelist` 中时移除；skill 在 `permissions.skill_blacklist` 中时移除
- 保持外部 intent-agent-skill 的关联关系

### 5. agent_id 查询验证
- 验证 `/chat` 接口传入 `agent_id` 时，从动态合并后的内存配置（含外部 agent）中查找智能体定义

## Impact

- Affected specs: auth, chat, orchestration
- Affected code:
  - `app/routes/auth.py` — 修改 login 流程，保存 token/permissions 到 Redis
  - `app/config.py` — 新增 `EXTERNAL_SKILLS_DIR`
  - `app/services/auth_service.py` — 新增 Redis 存储逻辑
  - `app/services/orchestrator_service.py` — 改为每次 /chat 重建 recognizer，支持动态追加 agent
  - `app/intent/recognizer.py` — 支持动态 setter 更新 intent_configs
  - `app/agents/registry.py` — 支持运行时追加/移除外部 agent 定义
  - `.env` — 新增 `EXTERNAL_SKILLS_DIR`
  - `app/routes/chat.py` — 注入用户权限信息

## ADDED Requirements

### Requirement 1: 登录 Token/Permissions 持久化到 Redis

系统 SHALL 在用户登录成功后，将 MNG 返回的 `access_token` 和 `permissions` 按 `user_id` 保存到 Redis。

#### Scenario: 登录成功保存权限
- **WHEN** 用户调用 `/login` 且验证通过
- **THEN** 系统将 `access_token` 和 `permissions` (含 `agent_whitelist` 和 `skill_blacklist`) 以 JSON 格式存入 Redis，key 为 `user:permissions:{user_id}`
- **AND** 设置合适的 TTL（与 JWT 过期时间一致）

#### Scenario: 登录接口改为调用 MNG
- **WHEN** `AUTH_MOCK=false` 时
- **THEN** 系统调用 MNG 系统的登录接口获取完整的返回格式（含 `access_token` 和 `permissions`）

#### Scenario: Redis 中查询用户权限
- **WHEN** 需要查询用户权限时
- **THEN** 从 Redis 读取 `user:permissions:{user_id}` 并解析 JSON，获取 `access_token`、`agent_whitelist`、`skill_blacklist`

### Requirement 2: /chat 时动态加载配置

系统 SHALL 在每次 `/chat` 请求开始时，重新加载并合并配置，问答结束后释放外部配置。

#### Scenario: 每次 /chat 重新加载 intent 配置
- **WHEN** 用户调用 `/chat`
- **THEN** 系统从文件重新加载 `intent_config.yml` 作为基础意图配置
- **AND** 从 MNG `/api/intents` 获取外部意图列表
- **AND** 合并基础意图和外部意图，构建完整的 `IntentRecognizer` 实例
- **AND** 将外部 agent 定义动态追加到 `AgentRegistry`
- **AND** 问答结束后，从 `AgentRegistry` 中移除本次追加的外部 agent 定义

#### Scenario: 配置生命周期管理
- **WHEN** `/chat` 请求开始
- **THEN** 创建本次请求的运行时上下文（含合并后的 intent config、动态 agent registry）
- **WHEN** `/chat` 请求结束（正常或异常）
- **THEN** 清理运行时上下文中的外部配置，释放内存

### Requirement 3: external_skills_dir 配置项

系统 SHALL 在 `.env` 中提供 `EXTERNAL_SKILLS_DIR` 配置项。

#### Scenario: 读取配置
- **WHEN** 系统需要定位外部技能目录
- **THEN** 从 `config.py` 读取 `EXTERNAL_SKILLS_DIR` 值（默认 `./external_skills`）

### Requirement 4: MNG 外部意图集成与权限过滤

系统 SHALL 从 MNG 获取外部意图，构建配置并应用权限过滤。

#### Scenario: 获取外部意图
- **WHEN** 调用 MNG `/api/intents`（GET 方法）
- **THEN** 解析返回的 `data` 数组，每一项包含 `id`、`name`、`intentCode`、`agents[]`、`skills[]`
- **AND** 将外部 intent 构建为 `IntentConfig` 结构，`id` 使用 `intentCode`
- **AND** 将外部 agent 构建为 `AgentDefinition` 结构，`id` 使用 `agent.code`
- **AND** 将外部 skill 路径设为 `{external_skills_dir}/{skill.code}`

#### Scenario: 权限过滤 - Agent 白名单
- **WHEN** 外部 agent 的 `agent.id` (即 `agent.code`) 不在当前用户的 `permissions.agent_whitelist` 中
- **THEN** 该 agent 不得加入内存配置
- **AND** 对应 intent 中移除该 agent 关联
- **AND** 若 intent 下所有 agent 都被移除，则整个 intent 不加入配置

#### Scenario: 权限过滤 - Skill 黑名单
- **WHEN** 外部 skill 的 `skill.id` (即 `skill.code`) 在当前用户的 `permissions.skill_blacklist` 中
- **THEN** 该 skill 不得加入内存配置
- **AND** 对应 agent 中移除该 skill 关联

#### Scenario: 外部 Intent 合并
- **WHEN** 外部 intent 通过权限过滤后
- **THEN** 追加到 intent_configs 列表末尾（先基础 intent，后外部 intent）
- **AND** 保持外部 intent-agent-skill 的关联关系

### Requirement 5: agent_id 查询验证

系统 SHALL 验证 `agent_id` 能在动态合并后的内存配置中被正确查询。

#### Scenario: 使用外部 agent_id 调用 /chat
- **WHEN** 用户传入 `agent_id` 对应的外部 agent
- **THEN** 系统从动态合并后的 `AgentRegistry` 中查找到该 agent 定义并执行

#### Scenario: 外部 agent_id 不存在
- **WHEN** 用户传入的 `agent_id` 不在当前会话的内存配置中
- **THEN** 返回错误事件 "agent_id 不存在"

## Key Design Decisions

### D1: 配置加载策略
- **基础 skill/workspace**：应用启动时一次性加载，常驻内存（`LocalWorkspace` 初始化开销大）
- **基础 agent 定义**：应用启动时加载，常驻内存
- **基础 intent 配置**：每次 `/chat` 从文件重新加载（确保配置最新）
- **外部 intent/agent**：每次 `/chat` 从 MNG 获取，动态注入，问答结束后清理

### D2: 权限数据传递
- 登录时将权限存入 Redis（key: `user:permissions:{user_id}`）
- `/chat` 时从 Redis 读取当前用户权限（或从 JWT 解析）
- 当前选择：从 Redis 读取，避免 JWT payload 膨胀

### D3: 外部 Skill 加载时机
- 外部 skill 需要被 `LocalWorkspace` 加载才能使用
- 选项 A：在每次 `/chat` 时发现并加载外部 skill（灵活性高，性能开销大）
- 选项 B：在应用启动时或 lazily 加载 `external_skills_dir` 下所有 skill（推荐）
- **当前选择**：选项 B，外部 skill 在启动时或首次需要时加载到 workspace