print("LOADING STT SERVER...", flush=True)

import os
import json
import asyncio
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


def post_ingest(session_id: str, text: str, is_final: bool) -> bool:
    payload = {
        "session_id": session_id,
        "text": normalize(text),
        "is_final": is_final,
    }
    try:
        r = requests.post(INGEST_URL, json=payload, timeout=HTTP_TIMEOUT)
        if is_final:
            print("[INGEST] FINAL", r.status_code, r.text, flush=True)
            
        return r.ok
    except Exception as e:
        print("[INGEST ERROR]", repr(e), flush=True)
        return False


def post_match(session_id: str, text: str) -> bool:
    payload = {
        "session_id": session_id,
        "text": text,
    }
    print(f"[MATCH URL] {MATCH_URL}", flush=True)
    print(f"[MATCH CALL] sending: {text}", flush=True)

    try:
        r = requests.post(MATCH_URL, json=payload, timeout=HTTP_TIMEOUT)
        print("[MATCH] POST /match:", r.status_code, r.text, flush=True)
        
        return r.ok
    except Exception as e:
        print("[MATCH ERROR]", repr(e), flush=True)
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
    # WAIT FOR START MESSAGE
    # =====================================================
    try:
        msg = await ws.receive()
    except Exception as e:
        print("[WS ERROR] Failed to receive first message:", repr(e), flush=True)
        try:
            await ws.close()
        except Exception:
            pass
        return

    if msg.get("type") != "websocket.receive":
        print("[WS ERROR] Unexpected first WebSocket message type:", msg.get("type"), flush=True)
        try:
            await ws.close()
        except Exception:
            pass
        return

    data = None

    if msg.get("text") is not None:
        try:
            data = json.loads(msg["text"])
        except Exception as e:
            print("[WS ERROR] Failed to parse start message as text JSON:", repr(e), flush=True)
            try:
                await ws.close()
            except Exception:
                pass
            return

    elif msg.get("bytes") is not None:
        try:
            decoded = msg["bytes"].decode("utf-8")
            data = json.loads(decoded)
        except Exception as e:
            print("[WS ERROR] Failed to parse start message as bytes JSON:", repr(e), flush=True)
            try:
                await ws.close()
            except Exception:
                pass
            return

    else:
        print("[WS ERROR] First WebSocket message had no text or bytes payload.", flush=True)
        try:
            await ws.close()
        except Exception:
            pass
        return

    if data.get("type") != "start":
        print("[WS ERROR] First message was not a start message:", data, flush=True)
        try:
            await ws.close()
        except Exception:
            pass
        return

    token = data.get("token")
    session_id = data.get("session_id")

    if not token or not session_id:
        print("[WS ERROR] Missing token or session_id in start message.", flush=True)
        try:
            await ws.close()
        except Exception:
            pass
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

    speech_config.set_property(
    speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
    "1000"   # balanced (faster than default)
)


    audio_format = speechsdk.audio.AudioStreamFormat(
        samples_per_second=48000,
        bits_per_sample=16,
        channels=1,
    )

    stream = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
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
            post_ingest(session_id, text, is_final=False)

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = normalize(evt.result.text)

            if text:
                print(f"[FINAL] {text}", flush=True)
                post_ingest(session_id, text, is_final=True)
                post_match(session_id, text)

        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("[FINAL NO MATCH]", evt.result.no_match_details, flush=True)

    def on_canceled(evt):
        print("[CANCELED]", evt.reason, flush=True)

        if evt.reason == speechsdk.CancellationReason.Error:
            print("[CANCELED ERROR]", evt.error_details, flush=True)
    
    def on_session_started(evt):
        print("[AZURE SESSION STARTED]", evt, flush=True)

    def on_session_stopped(evt):
        print("[AZURE SESSION STOPPED]", evt, flush=True)

    def on_speech_start_detected(evt):
        print("[AZURE SPEECH START DETECTED]", evt, flush=True)

    def on_speech_end_detected(evt):
        print("[AZURE SPEECH END DETECTED]", evt, flush=True)

    recognizer.session_started.connect(on_session_started)
    recognizer.session_stopped.connect(on_session_stopped)
    recognizer.speech_start_detected.connect(on_speech_start_detected)
    recognizer.speech_end_detected.connect(on_speech_end_detected)

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)

    print("[AZURE] starting recognizer...", flush=True)

    recognizer.start_continuous_recognition_async().get()
    await asyncio.sleep(0.2)  # stabilize pipeline

    print("[AZURE] recognizer start returned OK", flush=True)

    # =====================================================
    # RECEIVE AUDIO / CONTROL MESSAGES
    # =====================================================
    audio_count = 0

    try:
        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            if msg["type"] == "websocket.receive":
                if msg.get("bytes") is not None:
                    chunk = msg["bytes"]

                    audio_count += 1

                    if audio_count == 100:
                        print("[AUDIO STREAM ACTIVE]", flush=True)

                    stream.write(chunk)

                elif msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                        if data.get("type") == "stop":
                            break
                    except Exception as e:
                        print(
                            "[WS ERROR] Failed to parse text control message:",
                            repr(e),
                            flush=True,
                        )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("[WS ERROR] WebSocket loop error:", repr(e), flush=True)

    # =====================================================
    # CLEANUP
    # =====================================================
    try:
        recognizer.stop_continuous_recognition_async().get()
    except Exception as e:
        print("[WS ERROR] Failed to stop Azure recognizer:", repr(e), flush=True)

    try:
        stream.close()
    except Exception as e:
        print("[WS ERROR] Failed to close audio stream:", repr(e), flush=True)

    print(f"[WS] STT session ended for {session_id}", flush=True)

    try:
        await ws.close()
    except Exception:
        pass