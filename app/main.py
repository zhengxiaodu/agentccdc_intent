import uvicorn
import redis.asyncio as aioredis
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import MODEL_CONFIG_PATH, REDIS_URL
from app.services.chat_service import load_model_config
from app.services.orchestrator_service import OrchestratorService
from app.dao.session_dao import SessionDAO
from app.services.session_service import SessionService
from app.services.langfuse_service import LangfuseService
from app.routes import auth, chat, feedback, health, mng_proxy, sessions, upload


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化模型配置
    model_config = load_model_config(MODEL_CONFIG_PATH)
    app.state.model_config = model_config

    # 初始化多智能体编排服务（加载智能体定义 + skill + 意图识别器）
    app.state.orchestrator_service = await OrchestratorService.create(model_config)
    print("Orchestrator service initialized (multi-agent + multi-intent)")

    # 初始化 Redis 和会话服务
    redis_client = aioredis.from_url(
        REDIS_URL,
        decode_responses=False,
    )
    app.state.redis_client = redis_client
    app.state.session_dao = SessionDAO(redis_client)
    app.state.session_service = SessionService(app.state.session_dao)
    print(f"Session service initialized (Redis: {REDIS_URL})")

    # 初始化 Langfuse 追踪服务（非强依赖）
    app.state.langfuse_service = LangfuseService()
    if app.state.langfuse_service.enabled:
        print("Langfuse service initialized")
    else:
        print("Langfuse service disabled (credentials not configured)")

    yield

    # 关闭 Redis 连接
    await redis_client.close()
    print("Redis connection closed")


app = FastAPI(lifespan=lifespan)

app.include_router(auth.router, tags=["auth"])
app.include_router(chat.router, tags=["chat"])
app.include_router(feedback.router, tags=["feedback"])
app.include_router(health.router, tags=["health"])
app.include_router(sessions.router, tags=["sessions"])
app.include_router(upload.router, tags=["upload"])
app.include_router(mng_proxy.router, tags=["mng"])

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=7010, reload=True)
