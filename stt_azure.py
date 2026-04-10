# ======================================================
# AZURE STT WORKER — RUNS DURING ACTIVE SESSION
# ======================================================

import os
import time
import threading
import json
from typing import List, Optional, Tuple

import requests
import azure.cognitiveservices.speech as speechsdk

# =========================================================
# CONFIG — POINTS TO YOUR API SERVER
# =========================================================

API_BASE = "http://127.0.0.1:8000"
INGEST_URL = f"{API_BASE}/ingest"
MATCH_URL = f"{API_BASE}/match"

LANGUAGE = "en-US"

SILENCE_FINAL_SEC = 3.0
PARTIAL_THROTTLE_SEC = 0.35
HTTP_TIMEOUT_SEC = 8
RESTART_DELAY_SEC = 0.75
MAX_RAPID_RESTARTS = 8
RAPID_RESTART_WINDOW_SEC = 10.0

SPEECH_KEY_FALLBACK = ""
SPEECH_REGION_FALLBACK = ""

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY") or SPEECH_KEY_FALLBACK
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION") or SPEECH_REGION_FALLBACK

AZURE_MIC_DEVICE = (os.getenv("AZURE_MIC_DEVICE") or "").strip()

# =========================================================
# LOAD SESSION INFO (TOKEN + SESSION_ID) FROM FILE
# =========================================================

SESSION_INFO_PATH = "session_info.json"

def load_session_info() -> tuple[str, str]:
    try:
        with open(SESSION_INFO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("token") or ""
        session_id = data.get("session_id") or ""
        if not token or not session_id:
            raise RuntimeError("session_info.json missing token or session_id.")
        return token, session_id
    except FileNotFoundError:
        raise RuntimeError(
            f"{SESSION_INFO_PATH} not found. Start a session from the app first."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to load {SESSION_INFO_PATH}: {e}")

SUPABASE_TOKEN, SESSION_ID = load_session_info()

# =========================================================
# HELPERS
# =========================================================

def stt_normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = " ".join(s.split())
    return s


def post_ingest(text: str, is_final: bool) -> str:
    text = stt_normalize_text(text)
    if not text:
        return "empty"

    payload = {"session_id": SESSION_ID, "text": text, "is_final": bool(is_final)}
    try:
        r = requests.post(INGEST_URL, json=payload, timeout=HTTP_TIMEOUT_SEC)
        if r.ok:
            try:
                return r.json().get("status", "ok")
            except Exception:
                return "ok_non_json"

        body = ""
        try:
            body = (r.text or "")[:800]
        except Exception:
            body = ""
        return f"http_{r.status_code}: {body}"
    except Exception as e:
        return f"error:{type(e).__name__}"


DEBUG = False

def dprint(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


def post_match(text: str) -> str:
    text = stt_normalize_text(text)
    if not text:
        return "empty"

    payload = {"session_id": SESSION_ID, "text": text}
    try:
        r = requests.post(MATCH_URL, json=payload, timeout=HTTP_TIMEOUT_SEC)
        dprint("TEXT_SENT_TO_MATCHER:", repr(text))
        dprint("MATCH_HTTP_STATUS:", r.status_code)
        dprint("MATCH_RAW_RESPONSE:", r.text)

        if r.ok:
            try:
                data = r.json()
                dprint("MATCH_RESPONSE_JSON:", data)
                return data.get("status", "ok")
            except Exception:
                return "ok_non_json"
        return f"http_{r.status_code}"
    except Exception as e:
        return f"error:{type(e).__name__}"


def list_azure_input_devices() -> List[str]:
    try:
        devices = speechsdk.audio.AudioConfig.get_microphone_names()
        return [d for d in (devices or []) if isinstance(d, str) and d.strip()]
    except Exception:
        return []


def pick_best_mic_device(preferred: str = "") -> Tuple[Optional[str], str]:
    devices = list_azure_input_devices()

    if preferred:
        if preferred in devices:
            return preferred, "env_exact_match"
        low = preferred.lower()
        for d in devices:
            if low == d.lower():
                return d, "env_case_insensitive_match"
        for d in devices:
            if low in d.lower():
                return d, "env_contains_match"
        return None, "env_not_found_fallback_default"

    def score(name: str) -> int:
        n = name.lower()
        s = 0
        if "wasapi" in n:
            s += 50
        if "microphone array" in n:
            s += 30
        if "microphone" in n:
            s += 10
        if "sound mapper" in n:
            s -= 20
        return s

    if devices:
        best = max(devices, key=score)
        if score(best) > 0:
            return best, "auto_best_match"
        return devices[0], "auto_first_device"

    return None, "no_device_list_use_default"


# =========================================================
# MAIN STT LOOP
# =========================================================

def run_stt_background() -> None:
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        print("[STT] ERROR: Azure credentials not set.")
        print("Set environment variables:")
        print("  AZURE_SPEECH_KEY")
        print("  AZURE_SPEECH_REGION")
        return

    print("[STT] Initializing Azure Speech...")
    print(f"[STT] Region: {AZURE_SPEECH_REGION}")
    print(f"[STT] Posting to: {INGEST_URL} (session_id={SESSION_ID})")
    print(f"[STT] Silence-based FINAL flush: {SILENCE_FINAL_SEC:.1f}s")
    print(f"[STT] Partial throttle: {PARTIAL_THROTTLE_SEC:.2f}s")

    chosen_device, device_reason = pick_best_mic_device(AZURE_MIC_DEVICE)
    if AZURE_MIC_DEVICE:
        print(f"[STT] AZURE_MIC_DEVICE requested: {AZURE_MIC_DEVICE}")
    if chosen_device:
        print(f"[STT] Using microphone device: {chosen_device} ({device_reason})\n")
    else:
        print(f"[STT] Using default microphone ({device_reason})\n")

    stop_event = threading.Event()

    restart_times: List[float] = []

    lock = threading.Lock()
    partial_buffer = ""
    last_activity_at = time.time()
    last_partial_sent_at = 0.0

    last_final_text = ""
    last_final_at = 0.0
    FINAL_DEDUPE_WINDOW_SEC = 4.0

    session_running = threading.Event()
    need_restart = threading.Event()

    def send_partial(text: str) -> None:
        nonlocal last_partial_sent_at
        now = time.time()
        if (now - last_partial_sent_at) < PARTIAL_THROTTLE_SEC:
            return
        last_partial_sent_at = now

        status = post_ingest(text, is_final=False)
        print(f"[PARTIAL] {text}")
        print(f"   -> {status}\n")

    def send_final(text: str, reason: str) -> None:
        nonlocal last_final_text, last_final_at, partial_buffer
        text_norm = stt_normalize_text(text)
        if not text_norm:
            return

        now = time.time()
        if text_norm == last_final_text and (now - last_final_at) < FINAL_DEDUPE_WINDOW_SEC:
            return

        last_final_text = text_norm
        last_final_at = now

        status = post_ingest(text_norm, is_final=True)
        print(f"[FINAL] ({reason}) {text_norm}")
        print(f"   -> {status}")
        print()

        with lock:
            partial_buffer = ""

    def build_recognizer() -> speechsdk.SpeechRecognizer:
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY,
            region=AZURE_SPEECH_REGION,
        )
        speech_config.speech_recognition_language = LANGUAGE

        if chosen_device:
            audio_config = speechsdk.audio.AudioConfig(device_name=chosen_device)
        else:
            audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

        return speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

    recognizer: Optional[speechsdk.SpeechRecognizer] = None

    def attach_handlers(rec: speechsdk.SpeechRecognizer) -> None:
        def on_recognizing(evt: speechsdk.SpeechRecognitionEventArgs):
            nonlocal partial_buffer, last_activity_at
            text = stt_normalize_text(getattr(evt.result, "text", "") or "")
            if not text:
                return
            with lock:
                partial_buffer = text
                last_activity_at = time.time()
            send_partial(text)

        def on_recognized(evt: speechsdk.SpeechRecognitionEventArgs):
            nonlocal partial_buffer, last_activity_at
            if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
                return
            text = stt_normalize_text(getattr(evt.result, "text", "") or "")
            if not text:
                return
            with lock:
                partial_buffer = text
                last_activity_at = time.time()
            send_final(text, reason="azure")

        def on_session_started(evt: speechsdk.SessionEventArgs):
            session_running.set()
            print("[STT] Session started.")

        def on_session_stopped(evt: speechsdk.SessionEventArgs):
            session_running.clear()
            print("[STT] Session stopped. (auto-restarting)")
            need_restart.set()

        def on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs):
            session_running.clear()
            print("[STT] CANCELED:", evt.reason)
            if evt.reason == speechsdk.CancellationReason.Error:
                print("[STT] Error details:", evt.error_details)
            print("[STT] (auto-restarting)")
            need_restart.set()

        rec.recognizing.connect(on_recognizing)
        rec.recognized.connect(on_recognized)
        rec.session_started.connect(on_session_started)
        rec.session_stopped.connect(on_session_stopped)
        rec.canceled.connect(on_canceled)

    def start_recognition() -> None:
        nonlocal recognizer, partial_buffer, last_activity_at, last_partial_sent_at

        with lock:
            partial_buffer = ""
            last_activity_at = time.time()
        last_partial_sent_at = 0.0

        recognizer = build_recognizer()
        attach_handlers(recognizer)

        need_restart.clear()
        session_running.clear()

        print("[STT] 🎤 Listening... (Ctrl+C to stop)\n")
        recognizer.start_continuous_recognition_async().get()

    def stop_recognition() -> None:
        nonlocal recognizer
        try:
            if recognizer is not None:
                recognizer.stop_continuous_recognition_async().get()
        except Exception:
            pass
        recognizer = None
        session_running.clear()

    def silence_flush_loop():
        nonlocal partial_buffer
        while not stop_event.is_set():
            time.sleep(0.12)
            with lock:
                buf = stt_normalize_text(partial_buffer)
                idle = time.time() - last_activity_at
            if buf and idle >= SILENCE_FINAL_SEC:
                send_final(buf, reason=f"silence_{SILENCE_FINAL_SEC:.0f}s")

    flush_thread = threading.Thread(target=silence_flush_loop, daemon=True)
    flush_thread.start()

    try:
        start_recognition()

        while True:
            time.sleep(0.25)

            if stop_event.is_set():
                break

            if need_restart.is_set():
                now = time.time()
                restart_times.append(now)
                restart_times[:] = [
                    t for t in restart_times
                    if now - t <= RAPID_RESTART_WINDOW_SEC
                ]

                if len(restart_times) > MAX_RAPID_RESTARTS:
                    print("\n[STT] Too many rapid restarts.")
                    print("[STT] Likely causes on Windows:")
                    print("  - Another app has the mic in Exclusive Mode")
                    print("  - Wrong input device / driver path")
                    print("  - Audio enhancements/driver quirks")
                    print("\n[STT] Exiting to avoid a restart loop.")
                    break

                need_restart.clear()
                stop_recognition()
                time.sleep(RESTART_DELAY_SEC)
                start_recognition()

    except KeyboardInterrupt:
        print("\n[STT] Stopping...")
    finally:
        stop_event.set()
        stop_recognition()
        print("[STT] Stopped.")


if __name__ == "__main__":
    run_stt_background()
