from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.error import register_exception_handlers
from app.core.lifespan import lifespan

app = FastAPI(title="Base AI Server", lifespan=lifespan)

register_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")