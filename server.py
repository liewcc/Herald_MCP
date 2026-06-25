import fastapi
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Tuple, Optional
import uvicorn
import httpx
import asyncio
import uuid
import json
import pathlib
import datetime
import contextlib

# Load config.json from same directory as this file
current_dir = pathlib.Path(__file__).parent.resolve()
config_path = current_dir / "config.json"
try:
    with open(config_path, "r") as f:
        config = json.load(f)
except Exception:
    config = {
        "name": "machine-a",
        "port": 7700,
        "peers": {}
    }

port = config.get("port", 7700)

app = FastAPI(title="Herald MCP Long-poll Server")

# In-memory store (three dicts):
pending_messages: dict[str, dict] = {}  # message_id -> {message_id, from_peer, message, attachments, received_at}
reply_events: dict[str, tuple[asyncio.Event, dict|None]] = {}  # message_id -> (event, reply_data)
subscribers: dict[str, asyncio.Queue] = {}

class AskBody(BaseModel):
    message_id: str
    from_peer: str
    to_peer: str = ""
    message: str
    attachments: List[Any] = []

class ReplyBody(BaseModel):
    answer: str
    attachments: List[Any] = []

async def check_disconnect(request: Request, message_id: str):
    try:
        while True:
            if await request.is_disconnected():
                pending_messages.pop(message_id, None)
                reply_events.pop(message_id, None)
                break
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass

@app.post("/ask")
async def ask(request: Request, body: AskBody):
    message_id = body.message_id
    
    # Store message in pending_messages
    pending_messages[message_id] = {
        "message_id": message_id,
        "from_peer": body.from_peer,
        "to_peer": body.to_peer,
        "message": body.message,
        "attachments": body.attachments,
        "received_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    
    # Create asyncio.Event for this message_id in reply_events
    event = asyncio.Event()
    reply_events[message_id] = (event, None)
    
    # Background cleanup on disconnect
    disconnect_task = asyncio.create_task(check_disconnect(request, message_id))
    
    # Notify subscriber if registered
    if body.to_peer in subscribers:
        await subscribers[body.to_peer].put({
            "message_id": message_id,
            "from_peer": body.from_peer
        })
        
    try:
        # Wait for event to be set (timeout=300s via asyncio.wait_for)
        await asyncio.wait_for(event.wait(), timeout=300.0)
        
        # If event fires: remove from pending_messages, return {"answer": str, "attachments": [...]}
        _, reply_data = reply_events.get(message_id, (None, None))
        if reply_data is not None:
            return reply_data
        return {"answer": "", "attachments": []}
        
    except asyncio.TimeoutError:
        # If timeout: remove from pending_messages and reply_events, return {"error": "timeout"}
        return {"error": "timeout"}
        
    finally:
        disconnect_task.cancel()
        pending_messages.pop(message_id, None)
        reply_events.pop(message_id, None)

@app.post("/reply/{message_id}")
async def reply(message_id: str, body: ReplyBody):
    # Look up message_id in reply_events
    if message_id not in reply_events:
        raise HTTPException(status_code=404, detail="Message ID not found")
        
    event, _ = reply_events[message_id]
    reply_data = {
        "answer": body.answer,
        "attachments": body.attachments
    }
    # Store reply data, set the event
    reply_events[message_id] = (event, reply_data)
    event.set()
    # Return {"ok": true}
    return {"ok": True}

@app.get("/subscribe")
async def subscribe(request: Request, peer: str):
    if not peer:
        raise HTTPException(status_code=400, detail="Peer name is required")
    
    queue = asyncio.Queue()
    subscribers[peer] = queue
    
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Wait for a message notification or timeout for keepalive
                    msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if subscribers.get(peer) is queue:
                subscribers.pop(peer, None)
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "ok", "name": config.get("name", "machine-a"), "version": "1.0"}

@app.get("/pending")
async def get_pending(peer: str = ""):
    msgs = list(pending_messages.values())
    if peer:
        msgs = [m for m in msgs if m.get("to_peer") == peer]
    return msgs

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=port)
