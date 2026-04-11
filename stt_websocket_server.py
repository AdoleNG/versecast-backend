print("LOADING STT SERVER...")

import os
import json
import asyncio
import base64
import time
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import azure.cognitiveservices.speech as speechsdk
import requests

# =========================================================
# CONFIG
# =========================================================

API_BASE = os.getenv("VERSECAST_API_BASE", "https://api.versecast.ca")
INGEST_URL = f"{API_BASE}/ingest"
MATCH_URL = f"{API_BASE}/match"

AZURE_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_REGION = os.getenv("AZURE_SPEECH_REGION")

LANGUAGE = "en-US"
HTTP_TIMEOUT = 8

if not AZURE_KEY or not AZURE_REGION:
    raise RuntimeError("Missing Azure STT credentials.")

# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok"}
# =========================================================
# HELPERS
# =========================================================

def normalize(s: str) -> str:
    return " ".join((s or "").strip().split())


def post_ingest(session_id: str, text: str, is_final: bool):
    payload = {
        "session_id": session_id,
        "text": normalize(text),
        "is_final": is_final,
    }
    try:
        r = requests.post(INGEST_URL, json=payload, timeout=HTTP_TIMEOUT)
        return r.ok
    except Exception:
        return False


# =========================================================
# MAIN WEBSOCKET ENDPOINT
# =========================================================

@app.websocket("/stt/stream")
async def stt_stream(ws: WebSocket):
    """
    Browser sends:
        - binary PCM chunks (48000 Hz, 16-bit)
        - JSON control messages: {"type": "start", "token": "...", "session_id": "..."}

    Server:
        - Validates token
        - Streams audio to Azure
        - Sends partial + final transcripts to /ingest
    """

    await ws.accept()

    session_id: Optional[str] = None
    token: Optional[str] = None

 # =====================================================
# WAIT FOR START MESSAGE (DIAGNOSTIC VERSION)
# =====================================================
import json

try:
    msg = await ws.receive()
    print("[WS DEBUG] raw message received:", msg)

except Exception as e:
    print("[WS ERROR] receive failed:", e)
    try:
        await ws.close()
    except:
        pass
    return

# Ensure it's a receive event
if msg.get("type") != "websocket.receive":
    print("[WS DEBUG] unexpected message type:", msg.get("type"))
    await ws.close()
    return

# Extract payload
data = None

if msg.get("text"):
    try:
        data = json.loads(msg["text"])
        print("[WS DEBUG] parsed JSON (text):", data)
    except Exception as e:
        print("[WS ERROR] failed to parse text JSON:", e)
        await ws.close()
        return

elif msg.get("bytes"):
    try:
        decoded = msg["bytes"].decode("utf-8")
        data = json.loads(decoded)
        print("[WS DEBUG] parsed JSON (bytes):", data)
    except Exception as e:
        print("[WS ERROR] failed to parse bytes JSON:", e)
        await ws.close()
        return

else:
    print("[WS DEBUG] message had no text or bytes payload")
    await ws.close()
    return

# =====================================================
# VALIDATE MESSAGE
# =====================================================
if data.get("type") != "start":
    print("[WS DEBUG] invalid message type:", data)
    await ws.close()
    return

token = data.get("token")
session_id = data.get("session_id")

if not token or not session_id:
    print("[WS DEBUG] missing token or session_id:", data)
    await ws.close()
    return

print(f"[WS] STT session started for {session_id}")

    # =====================================================
    # BUILD AZURE STREAMING PIPELINE
    # =====================================================

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_KEY,
        region=AZURE_REGION,
    )
    speech_config.speech_recognition_language = LANGUAGE

    # Use push stream for raw PCM
    stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=stream)

    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    # =====================================================
    # EVENT HANDLERS
    # =====================================================

    def on_recognizing(evt):
        text = normalize(evt.result.text)
        if text:
            print(f"[PARTIAL] {text}")
            post_ingest(session_id, text, is_final=False)

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = normalize(evt.result.text)
            if text:
                print(f"[FINAL] {text}")
                post_ingest(session_id, text, is_final=True)

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)

    # Start Azure recognition
    recognizer.start_continuous_recognition_async().get()

    # =====================================================
    # RECEIVE AUDIO FROM BROWSER
    # =====================================================
    try:
        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            if msg["type"] == "bytes":
                # Raw PCM audio
                stream.write(msg["bytes"])

            elif msg["type"] == "json":
                data = msg["json"]
                if data.get("type") == "stop":
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("[WS] Error:", e)

    # =====================================================
    # CLEANUP
    # =====================================================
    try:
        recognizer.stop_continuous_recognition_async().get()
    except Exception:
        pass

    try:
        stream.close()
    except Exception:
        pass

    print(f"[WS] STT session ended for {session_id}")
    await ws.close()
