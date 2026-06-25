"""MNG 外部意图获取与权限过滤服务。

提供从管理平台（MNG）拉取外部意图和智能体配置，
并根据用户的 whitelist/blacklist 权限过滤后，
转换为系统内部 IntentConfig 和 AgentDefinition 的能力。
"""
import logging
from typing import List, Tuple

import aiohttp

from app.agents.base import AgentDefinition
from app.intent.models import IntentConfig

logger = logging.getLogger(__name__)


async def fetch_mng_intents(mng_url: str) -> List[dict]:
    """从 MNG 获取外部意图列表。

    调用 MNG /api/intents GET 接口，返回 data 数组。
    网络异常或非 200 状态码返回空列表。

    Args:
        mng_url: MNG 基础 URL

    Returns:
        外部意图列表（dict 格式），失败时返回空列表
    """
    if not mng_url:
        logger.warning("fetch_mng_intents: mng_url 为空")
        return []

    url = f"{mng_url.rstrip('/')}/api/intents"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(
                        "fetch_mng_intents failed: HTTP %s from %s",
                        resp.status,
                        url,
                    )
                    return []
                data = await resp.json()
                return data.get("data", [])
    except Exception:
        logger.exception("fetch_mng_intents 请求异常")
        return []


def build_external_configs(
    mng_data: list,
    whitelist: list,
    blacklist: list,
    external_skills_dir: str,
) -> Tuple[List[IntentConfig], List[AgentDefinition]]:
    """根据 MNG 数据和权限列表构建外部意图配置和智能体定义。

    权限匹配逻辑：
    - whitelist: agent.code 必须在 whitelist 中（按 code 字段匹配）
    - blacklist: skill.code 不能在 blacklist 中（按 code 字段匹配）
    - 若 whitelist 为空，不允许任何 agent
    - 若 intent 没有可用的 agent，跳过该 intent

    Args:
        mng_data: MNG 返回的意图数据列表，每项格式：
                  {id, name, intentCode, agents: [{id, name, code, prompt}],
                   skills: [{id, name, code}]}
        whitelist: 允许的 agent 列表 [{id, name, code}]
        blacklist: 屏蔽的 skill 列表 [{id, name, code}]
        external_skills_dir: 外部技能目录路径前缀（留作后续使用）

    Returns:
        (external_intents, external_agents) 二元组
    """
    whitelist_codes = {item["code"] for item in whitelist if "code" in item}
    blacklist_codes = {item["code"] for item in blacklist if "code" in item}

    external_intents: List[IntentConfig] = []
    external_agents: List[AgentDefinition] = []

    for item in mng_data:
        intent_code = item.get("intentCode", "")
        intent_name = item.get("name", "")
        agents_data = item.get("agents", [])
        skills_data = item.get("skills", [])

        allowed_agents: List[AgentDefinition] = []

        for agent in agents_data:
            agent_code = agent.get("code", "")
            # whitelist 过滤：agent 必须在 whitelist 中
            if agent_code not in whitelist_codes:
                continue

            # blacklist 过滤：过滤掉被屏蔽的 skill
            filtered_skills = []
            for skill in skills_data:
                skill_code = skill.get("code", "")
                if skill_code not in blacklist_codes:
                    filtered_skills.append(skill_code)

            agent_def = AgentDefinition(
                id=agent_code,
                name=agent.get("name", ""),
                skills=filtered_skills,
                system_prompt=agent.get("prompt", "") or "",
            )
            allowed_agents.append(agent_def)

        # 若没有允许的 agent，跳过此 intent
        if not allowed_agents:
            continue

        # 取第一个允许的 agent 绑定到 intent
        first_agent = allowed_agents[0]
        intent_config = IntentConfig(
            id=intent_code,
            name=intent_name,
            description="",
            agent=first_agent.id,
        )
        external_intents.append(intent_config)
        external_agents.extend(allowed_agents)

    return external_intents, external_agents


def register_external_agents(registry, external_agents: List[AgentDefinition]):
    """将外部智能体注册到 AgentRegistry。

    Args:
        registry: AgentRegistry 实例
        external_agents: 外部智能体定义列表
    """
    for agent_def in external_agents:
        registry.register_external_agent(agent_def)
        logger.info("已注册外部智能体: %s (%s)", agent_def.id, agent_def.name)


def unregister_external_agents(registry, external_agent_ids: List[str]):
    """从 AgentRegistry 注销外部智能体。

    Args:
        registry: AgentRegistry 实例
        external_agent_ids: 要注销的智能体 ID 列表
    """
    for agent_id in external_agent_ids:
        registry.unregister_external_agent(agent_id)
        logger.info("已注销外部智能体: %s", agent_id)