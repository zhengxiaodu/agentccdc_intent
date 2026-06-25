"""运行时聊天上下文服务。

为 /chat 接口动态加载 MNG 外部意图配置和权限过滤，
提供运行时上下文构建、应用、清理的完整生命周期管理。
"""
import logging
from dataclasses import dataclass, field
from typing import List

from app.agents.base import AgentDefinition
from app.config import INTENT_CONFIG_PATH
from app.intent.models import IntentConfig
from app.intent.recognizer import load_intent_config
from app.services.mng_intent_service import (
    build_external_configs,
    fetch_mng_intents,
    register_external_agents,
    unregister_external_agents,
)
from app.services.permission_service import get_user_permissions

logger = logging.getLogger(__name__)


@dataclass
class RuntimeChatContext:
    """运行时聊天上下文，包含合并后的意图配置和外部智能体信息。

    Attributes:
        intent_configs: 合并后的意图配置列表（base + external）
        external_agent_defs: 外部智能体定义列表
        external_agent_ids: 外部智能体 ID 列表（用于清理）
        whitelist: 当前用户的 agent whitelist
        blacklist: 当前用户的 skill blacklist
    """
    intent_configs: List[IntentConfig] = field(default_factory=list)
    external_agent_defs: List[AgentDefinition] = field(default_factory=list)
    external_agent_ids: List[str] = field(default_factory=list)
    whitelist: List[dict] = field(default_factory=list)
    blacklist: List[dict] = field(default_factory=list)


async def build_runtime_context(app_state, user_id: str) -> RuntimeChatContext:
    """构建运行时聊天上下文。

    流程：
    1. 从 INTENT_CONFIG_PATH 加载基础意图配置
    2. 从 Redis 获取用户权限（agent_whitelist / skill_blacklist）
    3. 从 MNG 拉取外部意图
    4. 根据权限过滤并构建外部配置
    5. 合并 base + external 意图配置

    Args:
        app_state: FastAPI app.state（需包含 redis_client, mng_url, external_skills_dir）
        user_id: 当前用户 ID

    Returns:
        RuntimeChatContext 实例
    """
    # 1. 加载基础意图配置
    raw_intent_config = load_intent_config(INTENT_CONFIG_PATH)
    base_intent_configs = [
        IntentConfig(**item) for item in raw_intent_config.get("intents", [])
    ]

    # 2. 获取用户权限
    permissions = await get_user_permissions(app_state.redis_client, user_id)
    whitelist = []
    blacklist = []
    if permissions:
        perms = permissions.get("permissions", {})
        whitelist = perms.get("agent_whitelist", [])
        blacklist = perms.get("skill_blacklist", [])

    # 3. 获取 MNG 外部意图
    mng_url = getattr(app_state, "mng_url", "")
    external_skills_dir = getattr(app_state, "external_skills_dir", "")
    mng_data = await fetch_mng_intents(mng_url)

    # 4. 构建外部配置（权限过滤）
    external_intents, external_agents = build_external_configs(
        mng_data,
        whitelist,
        blacklist,
        external_skills_dir,
    )

    # 5. 合并：base + external
    merged_intent_configs = base_intent_configs + external_intents

    context = RuntimeChatContext(
        intent_configs=merged_intent_configs,
        external_agent_defs=external_agents,
        external_agent_ids=[a.id for a in external_agents],
        whitelist=whitelist,
        blacklist=blacklist,
    )

    logger.info(
        "build_runtime_context: user=%s, base_intents=%d, external_intents=%d, "
        "external_agents=%d",
        user_id,
        len(base_intent_configs),
        len(external_intents),
        len(external_agents),
    )
    return context


async def apply_context(
    orchestrator_service,
    context: RuntimeChatContext,
):
    """应用运行时上下文到编排服务。

    - 注册外部智能体到 registry
    - 更新 IntentRecognizer 为合并后的意图配置

    Args:
        orchestrator_service: OrchestratorService 实例
        context: 运行时上下文
    """
    # 注册外部智能体
    register_external_agents(
        orchestrator_service.registry,
        context.external_agent_defs,
    )

    # 更新意图识别器
    orchestrator_service.set_runtime_recognizer(context.intent_configs)

    logger.info(
        "apply_context: 已注册 %d 个外部智能体，更新 %d 个意图配置",
        len(context.external_agent_defs),
        len(context.intent_configs),
    )


async def cleanup_context(
    orchestrator_service,
    context: RuntimeChatContext,
):
    """清理运行时上下文，恢复原始状态。

    - 注销外部智能体
    - 恢复基础意图识别器

    Args:
        orchestrator_service: OrchestratorService 实例
        context: 运行时上下文
    """
    # 注销外部智能体
    unregister_external_agents(
        orchestrator_service.registry,
        context.external_agent_ids,
    )

    # 恢复基础识别器
    orchestrator_service.restore_base_recognizer()

    logger.info(
        "cleanup_context: 已注销 %d 个外部智能体，恢复基础识别器",
        len(context.external_agent_ids),
    )