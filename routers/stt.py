# routers/stt.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.auth import get_current_auth_user
from api_server import get_current_session_for_user
from core.supabase import get_admin_supabase

import azure.cognitiveservices.speech as speechsdk
import json
import asyncio
import requests
import os

router = APIRouter()

# Your existing API endpoints
API_BASE = os.getenv("API_BASE", "https://api.versecast.ca")
INGEST_URL = f"{API_BASE}/ingest"
MATCH_URL = f"{API_BASE}/match"

AZURE_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_REGION = os.getenv("AZURE_SPEECH_REGION")


@router.websocket("/stt/stream")
async def stt_stream(websocket: WebSocket):
    # -----------------------------------------
    # 1. Extract query params
    # -----------------------------------------
    token = websocket.query_params.get("token")
    session_id = websocket.query_params.get("session_id")

    if not token or not session_id:
        await websocket.close(code=4401)
        return

    # -----------------------------------------
    # 2. Authenticate user
    # -----------------------------------------
    try:
        auth_user = get_current_auth_user(token)
    except Exception:
        await websocket.close(code=4401)
        return

    # -----------------------------------------
    # 3. Validate session belongs to this church
    # -----------------------------------------
    session = get_current_session_for_user(auth_user.id)
    if not session or session["id"] != session_id:
        await websocket.close(code=4403)
        return

    # -----------------------------------------
    # 4. Accept WebSocket
    # -----------------------------------------
    await websocket.accept()
    await websocket.send_json({"type": "info", "message": "WebSocket connected. Initializing Azure STT..."})

    # -----------------------------------------
    # 5. Initialize Azure Speech Recognizer
    # -----------------------------------------
    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_KEY,
        region=AZURE_REGION
    )
    speech_config.speech_recognition_language = "en-US"

    push_stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    loop = asyncio.get_event_loop()

    # -----------------------------------------
    # 6. Event Handlers
    # -----------------------------------------
    def handle_partial(evt):
        text = (evt.result.text or "").strip()
        if not text:
            return

        # Send partial to browser
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "partial", "text": text}),
            loop
        )

        # Send partial to ingest
        try:
            requests.post(INGEST_URL, json={
                "session_id": session_id,
                "text": text,
                "is_final": False
            }, timeout=5)
        except:
            pass

    def handle_final(evt):
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return

        text = (evt.result.text or "").strip()
        if not text:
            return

        # Send final to browser
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "final", "text": text}),
            loop
        )

        # Send final to ingest
        try:
            requests.post(INGEST_URL, json={
                "session_id": session_id,
                "text": text,
                "is_final": True
            }, timeout=5)
        except:
            pass

        # Send final to matcher
        try:
            requests.post(MATCH_URL, json={
                "session_id": session_id,
                "text": text
            }, timeout=5)
        except:
            pass

    recognizer.recognizing.connect(handle_partial)
    recognizer.recognized.connect(handle_final)

    # Start Azure continuous recognition
    recognizer.start_continuous_recognition_async().get()
    await websocket.send_json({"type": "info", "message": "Azure STT started."})

    # -----------------------------------------
    # 7. Main WebSocket Loop
    # -----------------------------------------
    try:
        while True:
            message = await websocket.receive()

            # Text frames (control messages)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                except:
                    continue

                if data.get("type") == "stop":
                    break

            # Binary frames (audio)
            elif "bytes" in message:
                audio_chunk = message["bytes"]
                push_stream.write(audio_chunk)

    except WebSocketDisconnect:
        pass

    finally:
        # -----------------------------------------
        # 8. Cleanup
        # -----------------------------------------
        recognizer.stop_continuous_recognition_async().get()
        push_stream.close()
        await websocket.close()
