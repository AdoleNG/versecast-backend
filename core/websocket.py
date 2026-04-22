from fastapi import WebSocket
from typing import Dict, List

# Store active websocket connections per church
church_connections: Dict[str, List[WebSocket]] = {}

async def broadcast_to_church(church_id: str, message: dict):
    """
    Send a message to all connected clients for a given church.
    """
    if church_id not in church_connections:
        return

    dead = []

    for ws in church_connections[church_id]:
        try:
            await ws.send_json(message)
        except:
            dead.append(ws)

    for ws in dead:
        church_connections[church_id].remove(ws)
