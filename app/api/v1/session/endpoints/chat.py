import uuid
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from fastapi_limiter.depends import RateLimiter
from loguru import logger

from pydantic import BaseModel, Field
from app.session_service.core.prompt_registry import SystemPromptScene
from app.dependencies import get_session_service, get_current_user_id
from app.session_service.session_service import SessionService

class ChatRequest(BaseModel):
    user_query: str = Field(..., description="The user's chat message")
    prompt_scene: SystemPromptScene = Field(default=SystemPromptScene.PAL, description="System prompt scene, used if creating a new session")
    llm_choice: str = Field(default="qwen", description="The LLM model choice, used if creating a new session")
from app.session_service.session_service import SessionService

router = APIRouter()

@router.post("/{session_id}/chat", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def chat_with_agent_stream(
    session_id: uuid.UUID,
    request: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    service: SessionService = Depends(get_session_service)
):
    logger.info(f"User {user_id} starting chat in session {session_id}")
    
    async def event_generator():
        try:
            stream_gen = service.handle_agent_stream_reply(
                user_query_text=request.user_query,
                session_id=session_id,
                user_id=uuid.UUID(user_id),
                prompt_scene=request.prompt_scene,
                llm_choice=request.llm_choice
            )
            async for reply in stream_gen:
                # SSE dictates we yield string or dict. We convert StreamReply to JSON
                yield {
                    "data": reply.model_dump_json()
                }
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            # Ensure we send some error formatting if stream fails, or let error middleware catch it
            yield {
                "event": "error",
                "data": str(e)
            }

    return EventSourceResponse(event_generator())
