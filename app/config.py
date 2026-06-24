import os
from dotenv import load_dotenv

load_dotenv()

SKILL_CONFIG_PATH = "../config/skill_config.yml"
MODEL_CONFIG_PATH = "../config/model_config.yml"
# 多智能体与多意图编排配置
AGENT_CONFIG_PATH = "../config/agent_config.yml"
INTENT_CONFIG_PATH = "../config/intent_config.yml"

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.getenv("JWT_SECRET", "please-change-this-secret")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "8"))

# Redis 配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_SESSION_TTL = int(os.getenv("REDIS_SESSION_TTL", "86400"))

# 文件上传配置
UPLOAD_MAX_SIZE_MB = int(os.getenv("UPLOAD_MAX_SIZE_MB", "10"))
UPLOAD_ALLOWED_MEDIA_TYPES = [
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "text/csv",  # csv
    "application/vnd.ms-excel",  # xls
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.ms-powerpoint",  # ppt
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
]

# Langfuse 可观测性配置
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")

# 管理中心地址
MNG_URL = os.getenv("MNG_URL", "")