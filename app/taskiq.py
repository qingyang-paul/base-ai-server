import taskiq_fastapi
from taskiq import TaskiqEvents, TaskiqState
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from app.core.config import Settings
from app.core.taskiq_middleware import OpentelemetryMiddleware

settings = Settings()

broker = ListQueueBroker(
    url=f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
).with_result_backend(
    RedisAsyncResultBackend(
        redis_url=f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
    )
)

# Workaround: manually add middleware because instance check fails mysteriously
otel_mw = OpentelemetryMiddleware()
otel_mw.set_broker(broker)
broker.middlewares.append(otel_mw)

taskiq_fastapi.init(broker, "app.main:app")
