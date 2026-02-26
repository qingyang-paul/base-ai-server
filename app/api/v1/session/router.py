from fastapi import APIRouter

from fastapi import APIRouter

from app.api.v1.session.endpoints.chat import router as chat_router

session_router = APIRouter()

session_router.include_router(chat_router, tags=["Session"])
