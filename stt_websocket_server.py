print("LOADING STT SERVER... VERSION B", flush=True)

import os
import json
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

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
    allow_origins=["*"],  # tighten later
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

    print("🔥 ENTERED /stt/stream HANDLER 🔥", flush=True)

    await ws.accept()
    print("🔥 WS ROUTE HIT AFTER ACCEPT 🔥", flush=True)

    session_id: Optional[str] = None
    token: Optional[str] = None

    # =====================================================
    # WAIT FOR START MESSAGE (DIAGNOSTIC VERSION)
    # =====================================================
    print("🔥 WAITING FOR FIRST WS MESSAGE 🔥", flush=True)

    try:
        msg = await ws.receive()
        print("[WS DEBUG] raw message received:", msg, flush=True)

    except Exception as e:
        print("[WS ERROR] receive failed:", repr(e), flush=True)
        try:
            await ws.close()
        except Exception as close_error:
            print("[WS ERROR] close after receive failure failed:", repr(close_error), flush=True)
        return

    # Ensure it's a receive event
    if msg.get("type") != "websocket.receive":
        print("[WS DEBUG] unexpected message type:", msg.get("type"), flush=True)
        try:
            await ws.close()
        except Exception as close_error:
            print("[WS ERROR] close after unexpected type failed:", repr(close_error), flush=True)
        return

    # Extract payload
    data = None

    if msg.get("text") is not None:
        try:
            data = json.loads(msg["text"])
            print("[WS DEBUG] parsed JSON (text):", data, flush=True)
        except Exception as e:
            print("[WS ERROR] failed to parse text JSON:", repr(e), flush=True)
            try:
                await ws.close()
            except Exception as close_error:
                print("[WS ERROR] close after text parse failure failed:", repr(close_error), flush=True)
            return

    elif msg.get("bytes") is not None:
        try:
            decoded = msg["bytes"].decode("utf-8")
            data = json.loads(decoded)
            print("[WS DEBUG] parsed JSON (bytes):", data, flush=True)
        except Exception as e:
            print("[WS ERROR] failed to parse bytes JSON:", repr(e), flush=True)
            try:
                await ws.close()
            except Exception as close_error:
                print("[WS ERROR] close after bytes parse failure failed:", repr(close_error), flush=True)
            return

    else:
        print("[WS DEBUG] message had no text or bytes payload", flush=True)
        try:
            await ws.close()
        except Exception as close_error:
            print("[WS ERROR] close after empty payload failed:", repr(close_error), flush=True)
        return

    # =====================================================
    # VALIDATE MESSAGE
    # =====================================================
    if data.get("type") != "start":
        print("[WS DEBUG] invalid message type:", data, flush=True)
        try:
            await ws.close()
        except Exception as close_error:
            print("[WS ERROR] close after invalid message type failed:", repr(close_error), flush=True)
        return

    token = data.get("token")
    session_id = data.get("session_id")

    if not token or not session_id:
        print("[WS DEBUG] missing token or session_id:", data, flush=True)
        try:
            await ws.close()
        except Exception as close_error:
            print("[WS ERROR] close after missing token/session_id failed:", repr(close_error), flush=True)
        return

    print(f"[WS] STT session started for {session_id}", flush=True)

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
            print(f"[PARTIAL] {text}", flush=True)
            post_ingest(session_id, text, is_final=False)

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = normalize(evt.result.text)
            if text:
                print(f"[FINAL] {text}", flush=True)
                post_ingest(session_id, text, is_final=True)

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)

    # Start Azure recognition
    recognizer.start_continuous_recognition_async().get()
    print("🔥 AZURE RECOGNIZER STARTED 🔥", flush=True)

    # =====================================================
    # RECEIVE AUDIO FROM BROWSER
    # =====================================================
    try:
        while True:
            msg = await ws.receive()
            print("[WS DEBUG] loop message:", msg.get("type"), flush=True)

            if msg["type"] == "websocket.disconnect":
                print("🔥 WEBSOCKET DISCONNECT RECEIVED 🔥", flush=True)
                break

            elif msg["type"] == "websocket.receive":
                if msg.get("bytes") is not None:
                    print(f"[WS DEBUG] received audio chunk: {len(msg['bytes'])} bytes", flush=True)
                    stream.write(msg["bytes"])

                elif msg.get("text") is not None:
                    print("[WS DEBUG] received text control message:", msg["text"], flush=True)
                    try:
                        data = json.loads(msg["text"])
                        if data.get("type") == "stop":
                            print("🔥 STOP MESSAGE RECEIVED 🔥", flush=True)
                            break
                    except Exception as e:
                        print("[WS ERROR] failed to parse loop text control message:", repr(e), flush=True)

    except WebSocketDisconnect:
        print("🔥 WebSocketDisconnect exception caught 🔥", flush=True)
    except Exception as e:
        print("[WS] Error:", repr(e), flush=True)

    # =====================================================
    # CLEANUP
    # =====================================================
    try:
        recognizer.stop_continuous_recognition_async().get()
        print("🔥 AZURE RECOGNIZER STOPPED 🔥", flush=True)
    except Exception as e:
        print("[WS ERROR] stopping recognizer failed:", repr(e), flush=True)

    try:
        stream.close()
        print("🔥 AUDIO STREAM CLOSED 🔥", flush=True)
    except Exception as e:
        print("[WS ERROR] closing stream failed:", repr(e), flush=True)

    print(f"[WS] STT session ended for {session_id}", flush=True)

    try:
        await ws.close()
        print("🔥 WEBSOCKET CLOSED CLEANLY 🔥", flush=True)
    except Exception as e:
        print("[WS ERROR] final ws.close() failed:", repr(e), flush=True)