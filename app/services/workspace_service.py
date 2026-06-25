"""工作区服务：封装 AgentScope 的 WorkspaceManager，提供工作区生命周期管理。

设计说明：
- 优先使用 agentscope.app.workspace_manager 中的 LocalWorkspaceManager / DockerWorkspaceManager
- 若不存在（旧版 agentscope），回退到 agentscope.workspace.LocalWorkspace
"""
import logging
import os
from typing import Any, List, Optional

import yaml

logger = logging.getLogger(__name__)

# 尝试导入新版 WorkspaceManager API，回退到旧版 workspace
try:
    from agentscope.app.workspace_manager import (
        DockerWorkspaceManager,
        LocalWorkspaceManager,
    )

    HAS_NEW_WS_MANAGER = True
except ImportError:
    from agentscope.workspace import DockerWorkspace, LocalWorkspace

    HAS_NEW_WS_MANAGER = False


def _parse_extra_pip(extra_pip_str: str) -> List[str]:
    """解析逗号分隔的额外 pip 包列表。"""
    if not extra_pip_str or not extra_pip_str.strip():
        return []
    return [pkg.strip() for pkg in extra_pip_str.split(",") if pkg.strip()]


def _build_docker_workspace_kwargs(
    base_image: str,
    node_version: str,
    extra_pip: str,
) -> dict:
    """构建 Docker workspace 额外关键字参数。

    Args:
        base_image: Docker 基础镜像
        node_version: Node.js 版本（空字符串则不安装）
        extra_pip: 额外 pip 包（逗号分隔）

    Returns:
        传给 DockerWorkspace / DockerWorkspaceManager 的关键字参数字典
    """
    kwargs: dict = {}
    if base_image:
        kwargs["base_image"] = base_image
    if node_version:
        kwargs["node_version"] = node_version
    pip_list = _parse_extra_pip(extra_pip)
    if pip_list:
        kwargs["extra_pip"] = pip_list
    return kwargs


class WorkspaceService:
    """工作区服务：封装 WorkspaceManager，按用户/智能体/会话提供独立工作区。

    生命周期由 app.main lifespan 管理，单例存于 app.state。
    """

    def __init__(
        self,
        manager_type: str = "local",
        basedir: str = "./workspaces",
        ttl: float = 3600.0,
        docker_base_image: str = "python:3.11-slim",
        docker_node_version: str = "",
        docker_extra_pip: str = "",
    ):
        """
        Args:
            manager_type: 管理器类型，"local" 或 "docker"
            basedir: 工作区基础目录
            ttl: 工作区 TTL（秒），超时未访问的自动清理
            docker_base_image: Docker 基础镜像（仅 manager_type="docker" 时生效）
            docker_node_version: Docker 容器内安装的 Node.js 版本
            docker_extra_pip: Docker 容器内额外 pip 包（逗号分隔）
        """
        self._manager_type = manager_type
        self._basedir = basedir
        self._ttl = ttl
        self._docker_kwargs = _build_docker_workspace_kwargs(
            docker_base_image,
            docker_node_version,
            docker_extra_pip,
        )
        self._base_workspace: Any = None
        self._skill_paths: List[str] = []

    async def _load_skill_config(self, skill_config_path: str) -> List[str]:
        """从 skill_config.yml 加载技能目录列表。"""
        with open(skill_config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return [s["directory"] for s in config.get("skills", [])]

    async def get_base_workspace(
        self,
        skill_config_path: str,
    ) -> Any:
        """加载基础工作区（含所有技能），供启动时提取全量工具和技能元信息。

        结果缓存在内部，后续调用不会重复初始化。

        Args:
            skill_config_path: skill_config.yml 的路径

        Returns:
            已初始化的工作区实例，支持 list_tools() / list_skills()
        """
        if self._base_workspace is not None:
            return self._base_workspace

        self._skill_paths = await self._load_skill_config(skill_config_path)

        if HAS_NEW_WS_MANAGER:
            is_docker = self._manager_type == "docker"
            if is_docker:
                ws = DockerWorkspaceManager(
                    basedir=self._basedir,
                    ttl=self._ttl,
                    **self._docker_kwargs,
                )
            else:
                ws = LocalWorkspaceManager(
                    basedir=self._basedir,
                    ttl=self._ttl,
                )
        else:
            if self._manager_type == "docker":
                ws = DockerWorkspace(
                    workdir=self._basedir,
                    default_mcps=[],
                    skill_paths=self._skill_paths,
                    **self._docker_kwargs,
                )
            else:
                ws = LocalWorkspace(
                    workdir=self._basedir,
                    default_mcps=[],
                    skill_paths=self._skill_paths,
                )

        await ws.initialize()
        self._base_workspace = ws
        logger.info(
            "[WorkspaceService] 基础工作区已初始化，skills=%s",
            self._skill_paths,
        )
        return ws

    async def get_workspace(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> Any:
        """获取指定用户/智能体/会话的工作区实例。

        工作区键格式: ``{user_id}/{agent_id}/{session_id}``

        Args:
            user_id: 用户标识
            agent_id: 智能体标识
            session_id: 会话标识

        Returns:
            已初始化的工作区实例
        """
        key = f"{user_id}/{agent_id}/{session_id}"

        if HAS_NEW_WS_MANAGER:
            is_docker = self._manager_type == "docker"
            if is_docker:
                ws = DockerWorkspaceManager(
                    basedir=os.path.join(self._basedir, key),
                    ttl=self._ttl,
                    **self._docker_kwargs,
                )
            else:
                ws = LocalWorkspaceManager(
                    basedir=os.path.join(self._basedir, key),
                    ttl=self._ttl,
                )
        else:
            if self._manager_type == "docker":
                ws = DockerWorkspace(
                    workdir=os.path.join(self._basedir, key),
                    default_mcps=[],
                    skill_paths=self._skill_paths,
                    **self._docker_kwargs,
                )
            else:
                ws = LocalWorkspace(
                    workdir=os.path.join(self._basedir, key),
                    default_mcps=[],
                    skill_paths=self._skill_paths,
                )

        await ws.initialize()
        return ws

    @property
    def skill_paths(self) -> List[str]:
        """当前已加载的技能目录列表。"""
        return list(self._skill_paths)

    async def close(self):
        """清理工作区资源（关闭基础工作区）。"""
        if self._base_workspace is not None:
            close_fn = getattr(self._base_workspace, "close", None)
            if close_fn is not None:
                if hasattr(close_fn, "__await__") or callable(close_fn):
                    result = close_fn()
                    if hasattr(result, "__await__"):
                        await result
            self._base_workspace = None
            logger.info("[WorkspaceService] 基础工作区已关闭")