import pytest
import uuid
import json
import asyncio
from unittest.mock import patch
from app.session_service.tasks.persist_session_buffer import persist_session_buffer_task
from sqlalchemy import text

@pytest.mark.asyncio
async def test_e2e_qwen_active_persistence(client, db_session, redis_client, repo):
    """
    End-to-End Test for multi-turn interaction with Qwen model.
    Checks the active buffer threshold logic (simulated worker) and 
    ZSET partial cleanup when DB persistence kicks in mid-session.
    Saves the final DB records to a text file for the user.
    """
    session_id = str(uuid.uuid4())
    
    # ---------------------------------------------
    # Turn 1: User -> Qwen
    # ---------------------------------------------
    payload_1 = {
        "user_query": "Hello Alibaba! My name is John. Can you remember it?",
        "prompt_scene": "pal",
        "llm_choice": "qwen"
    }

    chunks_1 = []
    async with client.stream("POST", f"/api/v1/session/{session_id}/chat", json=payload_1) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line.replace("data: ", "")
                chunks_1.append(json.loads(data))
    
    print("CHUNKS 1 DEBUG:", chunks_1)
    await asyncio.sleep(1)

    # ---------------------------------------------
    # Turn 2: User -> Qwen
    # ---------------------------------------------
    payload_2 = {
        "user_query": "What is my name?",
        "prompt_scene": "pal",
        "llm_choice": "qwen"
    }
    chunks_2 = []
    async with client.stream("POST", f"/api/v1/session/{session_id}/chat", json=payload_2) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line.replace("data: ", "")
                chunks_2.append(json.loads(data))
                
    await asyncio.sleep(1)
    
    # Verify that the response includes 'John'
    print("CHUNKS 2 DEBUG:", chunks_2)
    run_finish_event = next((c for c in chunks_2 if c["event_type"] == "run_finish"), None)
    assert run_finish_event is not None
    assistant_msg = run_finish_event["generated_messages"][0]["content"]
    assert "John" in assistant_msg
    
    # Postgres is empty initially
    rows = (await db_session.execute(text("SELECT * FROM session_messages WHERE session_id = :session_id"), {"session_id": session_id})).mappings().all()
    assert len(rows) == 0

    # Redis has 4 items
    assert await redis_client.zcard(f"session_buffer:{session_id}") == 4
    
    # ---------------------------------------------
    # Active Taskiq Worker Execution (Buffer Threshold Reached)
    # ---------------------------------------------
    # Usually service.py calls persist_session_buffer_task.kiq(session_id)
    # We pretend the worker immediately picked it up
    await persist_session_buffer_task(session_id=uuid.UUID(session_id), repo=repo)
    
    # Now Redis buffer should be completely flushed of the 4 elements
    assert await redis_client.zcard(f"session_buffer:{session_id}") == 0
    # But Cache should still exist!
    assert await redis_client.zcard(f"session_cache:{session_id}") == 4
    assert await redis_client.exists(f"session_meta:{session_id}") == 1
    
    # And Postgres should have 4 messages
    persistent_rows = (await db_session.execute(text("SELECT * FROM session_messages WHERE session_id = :session_id ORDER BY seq_id ASC"), {"session_id": session_id})).mappings().all()
    assert len(persistent_rows) == 4
    
    # If we talk to Qwen again, it should be able to load memory from Redis Cache/PG 
    payload_3 = {
        "user_query": "Have you completely forgotten me?",
        "prompt_scene": "pal",
        "llm_choice": "qwen"
    }
    chunks_3 = []
    async with client.stream("POST", f"/api/v1/session/{session_id}/chat", json=payload_3) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line.replace("data: ", "")
                chunks_3.append(json.loads(data))
                
    await asyncio.sleep(1)
    
    # ZSET Buffer should be at 2 items (it started accumulating from scratch again!)
    assert await redis_client.zcard(f"session_buffer:{session_id}") == 2
    
    # Dump results to file for USER to manually review
    with open("qwen_e2e_results.txt", "w") as f:
        f.write("=== Turn 1 Event Stream (JSON) ===\n")
        for c in chunks_1:
            f.write(json.dumps(c) + "\n")
            
        f.write("\n=== Turn 2 Event Stream (JSON) ===\n")
        f.write(f"Model Recall Output: {assistant_msg}\n")
            
        f.write("\n=== Postgres Final Persisted Messages (Mid-Session Worker Trigger) ===\n")
        for row in persistent_rows:
            f.write(f"SEQ {row['seq_id']} | {row['llm_message']['role']}: {row['llm_message']['content']}\n")
            
        f.write("\n=== Turn 3 Event Stream (JSON) Response ===\n")
        run_finish = next((c for c in chunks_3 if c["event_type"] == "run_finish"), None)
        f.write(f"Post-Flush Recall Output: {run_finish['generated_messages'][0]['content']}\n")
