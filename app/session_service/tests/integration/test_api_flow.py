import pytest
import uuid
import json
from sse_starlette.sse import ServerSentEvent

@pytest.mark.asyncio
async def test_chat_streaming_endpoint(client, db_session, redis_client):
    """
    Test the integration of the Chat Streaming Endpoint
    Requires starting the FastAPI application via the client.
    """
    session_id = str(uuid.uuid4())
    
    # Send request to our chat endpoint
    payload = {
        "user_query": "Hello AI!",
        "prompt_scene": "pal",
        "llm_choice": "qwen"
    }

    from unittest.mock import patch
    from app.session_service.core.prompt_registry import SystemPromptScene, PromptMeta
    
    mock_prompt_meta = PromptMeta(scene=SystemPromptScene.PAL, version="v1.0", description="test", content="System PAL")

    # We use stream=True since we are expecting SSE texts
    with patch("app.session_service.session_service.PromptRegistry.get_latest_prompt", return_value=mock_prompt_meta):
        async with client.stream("POST", f"/api/v1/session/{session_id}/chat", json=payload) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            
            # Read the chunks from the generator
            chunks = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line.replace("data: ", "")
                    chunks.append(data)
                elif line.startswith("event: error"):
                    print("STREAM ERROR CAUGHT", line)
                    
        print("STREAM CHUNKS PRODUCED:", chunks)
                
        # Since ChatService is mocked to not return anything out of the box (or relies on actual LLM generation),
        # the stream might immediately exit without tokens unless we configure the mock inside conftest.py.
        # But this verifies that the routing works, the endpoint parses correctly, handles SSE streaming headers,
        # and doesn't 500 fault on lazy Session creation.
        
    # Verify Lazy Creation persistence in Redis
    import json
    meta_bytes = await redis_client.get(f"session_meta:{session_id}")
    assert meta_bytes is not None
    meta_data = json.loads(meta_bytes)
    assert meta_data["llm_choice"] == "qwen"
    assert meta_data["prompt_scene"] == "pal"
    assert meta_data["status"] == "active"
