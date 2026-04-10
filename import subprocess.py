import subprocess
import json
import os
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import signal

app = FastAPI()

WORKER_PROCESS = None
SESSION_INFO_PATH = "session_info.json"


class StartPayload(BaseModel):
    token: str
    session_id: str


@app.post("/start-worker")
def start_worker(payload: StartPayload):
    global WORKER_PROCESS

    # Write session_info.json
    with open(SESSION_INFO_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"token": payload.token, "session_id": payload.session_id},
            f,
            indent=2,
        )

    # If worker already running, kill it
    if WORKER_PROCESS and WORKER_PROCESS.poll() is None:
        WORKER_PROCESS.terminate()

    # Start stt_azure.py in background
    WORKER_PROCESS = subprocess.Popen(
        ["python", "stt_azure.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    return {"status": "worker_started"}


@app.post("/stop-worker")
def stop_worker():
    global WORKER_PROCESS

    if WORKER_PROCESS and WORKER_PROCESS.poll() is None:
        WORKER_PROCESS.terminate()
        WORKER_PROCESS = None

    # Remove session_info.json
    if os.path.exists(SESSION_INFO_PATH):
        os.remove(SESSION_INFO_PATH)

    return {"status": "worker_stopped"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
