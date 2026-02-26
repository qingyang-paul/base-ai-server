from pydantic import BaseModel

# session冷却多久可以认为是inactive (seconds)
# 默认 5 分钟 (300秒)
SESSION_INACTIVE_THRESHOLD: int = 300

# session buffer 达到多少条消息主动做持久化
SESSION_BUFFER_THRESHOLD: int = 50
