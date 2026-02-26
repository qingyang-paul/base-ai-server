import pytest
import uuid
import json
import asyncio
from datetime import datetime, timezone, timedelta
from app.session_service.tasks.persist_session_buffer import persist_session_buffer_task
from app.session_service.tasks.cleanup_inactive_sessions import cleanup_inactive_sessions_task
from sqlalchemy import text
from unittest.mock import patch

@pytest.mark.asyncio
async def test_e2e_gemini_multi_turn_chat(client, db_session, redis_client, repo):
    """
    End-to-End Test for multi-turn interaction with Gemini model.
    Checks accurate streaming output, ZSET buffer creation, and Taskiq PostgreSQL persistence.
    Saves the final DB records to a text file for the user.
    """
    session_id = str(uuid.uuid4())
    
    # ---------------------------------------------
    # Turn 1: User -> Gemini
    # ---------------------------------------------
    payload_1 = {
        "user_query": "Hello Gemini! I am testing your memory. My favorite number is 99.",
        "prompt_scene": "pal",
        "llm_choice": "gemini"
    }

    chunks_1 = []
    async with client.stream("POST", f"/api/v1/session/{session_id}/chat", json=payload_1) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line.replace("data: ", "")
                chunks_1.append(json.loads(data))
    
    # The stream finishes and the SessionService saves the chat to the buffer asynchronously.
    # We must wait a tiny bit to ensure the asyncio task completes.
    await asyncio.sleep(1)

    # Verify Redis buffer contains 2 messages (User + AI)
    buffer_key = f"session_buffer:{session_id}"
    buffer_size = await redis_client.zcard(buffer_key)
    assert buffer_size == 2

    # Verify PostgreSQL is empty (passive buffer hasn't flushed yet)
    rows = (await db_session.execute(text("SELECT * FROM session_messages WHERE session_id = :session_id"), {"session_id": session_id})).mappings().all()
    assert len(rows) == 0

    # ---------------------------------------------
    # Turn 2: User -> Gemini (Memory Check)
    # ---------------------------------------------
    payload_2 = {
        "user_query": "Do you remember what my favorite number is?",
        "prompt_scene": "pal",
        "llm_choice": "gemini"
    }
    
    chunks_2 = []
    async with client.stream("POST", f"/api/v1/session/{session_id}/chat", json=payload_2) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line.replace("data: ", "")
                chunks_2.append(json.loads(data))
                
    await asyncio.sleep(1)
    
    # Verify Redis buffer contains 4 messages
    buffer_size = await redis_client.zcard(buffer_key)
    assert buffer_size == 4
    
    # Check that Gemini remembered the number
    run_finish_event = next((c for c in chunks_2 if c["event_type"] == "run_finish"), None)
    assert run_finish_event is not None
    assistant_msg = run_finish_event["generated_messages"][0]["content"]
    assert "99" in assistant_msg
    
    # Postgres is still empty
    rows = (await db_session.execute(text("SELECT * FROM session_messages WHERE session_id = :session_id"), {"session_id": session_id})).mappings().all()
    assert len(rows) == 0

    # ---------------------------------------------
    # Manual Taskiq Worker Execution
    # ---------------------------------------------
    
    # We will simulate 5 minutes passing by patching the config threshold to 0 and running the cleanup task
    with patch("app.session_service.tasks.cleanup_inactive_sessions.SESSION_INACTIVE_THRESHOLD", -1):
        await cleanup_inactive_sessions_task(repo=repo)
        
    # Now Redis should be entirely wiped clean
    assert await redis_client.exists(f"session_meta:{session_id}") == 0
    assert await redis_client.exists(f"session_buffer:{session_id}") == 0
    assert await redis_client.exists(f"session_cache:{session_id}") == 0
    
    # And Postgres should have 4 messages perfectly chronologically ordered
    persistent_rows = (await db_session.execute(text("SELECT * FROM session_messages WHERE session_id = :session_id ORDER BY seq_id ASC"), {"session_id": session_id})).mappings().all()
    assert len(persistent_rows) == 4
    
    # Dump results to file for USER to manually review
    with open("gemini_e2e_results.txt", "w") as f:
        f.write("=== Turn 1 Event Stream (JSON) ===\n")
        for c in chunks_1:
            f.write(json.dumps(c) + "\n")
            
        f.write("\n=== Turn 2 Event Stream (JSON) ===\n")
        f.write(f"Model Recall Output: {assistant_msg}\n")
            
        f.write("\n=== Postgres Final Persisted Messages ===\n")
        for row in persistent_rows:
            f.write(f"SEQ {row['seq_id']} | {row['llm_message']['role']}: {row['llm_message']['content']}\n")
