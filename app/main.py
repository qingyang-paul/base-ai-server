from fastapi import FastAPI

from app.core.lifespan import lifespan

app = FastAPI(title="Base AI Server", lifespan=lifespan)