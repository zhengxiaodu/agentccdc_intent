import json
from typing import Any, Dict, Optional

import redis.asyncio as aioredis


def _permissions_key(user_id: str) -> str:
    return f"user:permissions:{user_id}"


async def save_login_permissions(
    redis_client: aioredis.Redis,
    user_id: str,
    access_token: str,
    permissions: dict,
    ttl_seconds: int,
) -> None:
    """登录成功后保存 access_token 和 permissions 到 Redis。

    Args:
        redis_client: redis.asyncio.Redis 实例
        user_id: 用户 ID
        access_token: JWT access token
        permissions: 权限对象，包含 agent_whitelist / skill_blacklist
        ttl_seconds: 过期时间（秒）
    """
    data = {
        "access_token": access_token,
        "permissions": permissions,
    }
    await redis_client.setex(
        _permissions_key(user_id),
        ttl_seconds,
        json.dumps(data, ensure_ascii=False),
    )


async def get_user_permissions(
    redis_client: aioredis.Redis,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    """从 Redis 读取用户 permissions。

    Args:
        redis_client: redis.asyncio.Redis 实例
        user_id: 用户 ID

    Returns:
        存储的 dict（含 access_token 和 permissions），不存在时返回 None
    """
    raw = await redis_client.get(_permissions_key(user_id))
    if raw is None:
        return None
    return json.loads(raw)