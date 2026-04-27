print("LOADING STT SERVER...", flush=True)

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


def post_ingest(session_id: str, text: str, is_final: bool) -> bool:
    payload = {
        "session_id": session_id,
        "text": normalize(text),
        "is_final": is_final,
    }
    try:
        r = requests.post(INGEST_URL, json=payload, timeout=HTTP_TIMEOUT)
        print(
            "[INGEST]",
            "FINAL" if is_final else "PARTIAL",
            r.status_code,
            r.text,
            flush=True,
        )
        return r.ok
    except Exception as e:
        print("[INGEST ERROR]", repr(e), flush=True)
        return False


def post_match(session_id: str, text: str) -> bool:
    payload = {
        "session_id": session_id,
        "text": text,
    }
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
    print(f"[RECOGNIZED RAW REASON] {evt.result.reason}", flush=True)
    print(f"[RECOGNIZED RAW TEXT] {repr(evt.result.text)}", flush=True)

    if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
        text = normalize(evt.result.text)

        if text:
            print(f"[FINAL] {text}", flush=True)

            # Send to /ingest
            post_ingest(session_id, text, is_final=True)

            # Send FINAL transcript to /match
            post_match(session_id, text)

    elif evt.result.reason == speechsdk.ResultReason.NoMatch:
        print("[FINAL NO MATCH]", evt.result.no_match_details, flush=True)

    elif evt.result.reason == speechsdk.ResultReason.Canceled:
        print("[FINAL CANCELED]", evt.result.cancellation_details, flush=True)

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)

    try:
        recognizer.start_continuous_recognition_async().get()
    except Exception as e:
        print("[WS ERROR] Failed to start Azure recognizer:", repr(e), flush=True)
        try:
            await ws.close()
        except Exception:
            pass
        return

    # =====================================================
    # RECEIVE AUDIO / CONTROL MESSAGES
    # =====================================================
    try:
        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            if msg["type"] == "websocket.receive":
                if msg.get("bytes") is not None:
                    stream.write(msg["bytes"])

                elif msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                        if data.get("type") == "stop":
                            break
                    except Exception as e:
                        print("[WS ERROR] Failed to parse text control message:", repr(e), flush=True)

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
