"""
stt_azure.py
Local PC microphone -> Azure Speech SDK -> POST /ingest

Fixes in this version
- Force a specific microphone by name (fixes Windows rapid restart mic-open failures)
- Optional env var AZURE_MIC_DEVICE to select mic (recommended)
- Auto-select best matching mic when AZURE_MIC_DEVICE is not set (prefers WASAPI)
- Keeps your script alive and continuously listening unless you press Ctrl+C
- Streams PARTIAL results (throttled)
- Sends FINAL on:
    (A) Azure final segment, and/or
    (B) Silence-based flush after SILENCE_FINAL_SEC (default 3.0s)
- Dedupe FINALs
- Prints HTTP error body (incl. 500) for debugging

Setup (recommended)
PowerShell:
  setx AZURE_SPEECH_KEY "YOUR_KEY_HERE"
  setx AZURE_SPEECH_REGION "canadaeast"
  setx AZURE_MIC_DEVICE "Microphone Array (Realtek High Definition Audio)"
Then CLOSE and reopen PowerShell (setx only applies to new terminals).
"""

import os
import time
import threading
from typing import Optional, List, Tuple

import requests
import azure.cognitiveservices.speech as speechsdk

# -----------------------------
# APP CONFIG
# -----------------------------
API_BASE = "http://127.0.0.1:8000"
INGEST_URL = f"{API_BASE}/ingest"
SESSION_ID = "demo"

LANGUAGE = "en-US"

# Silence-based final flush
SILENCE_FINAL_SEC = 3.0

# Reduce partial spam
PARTIAL_THROTTLE_SEC = 0.35

# Requests
HTTP_TIMEOUT_SEC = 8

# Auto-restart behavior
RESTART_DELAY_SEC = 0.75
MAX_RAPID_RESTARTS = 8
RAPID_RESTART_WINDOW_SEC = 10.0

# -----------------------------
# AZURE CONFIG
# Prefer environment variables.
# -----------------------------
SPEECH_KEY_FALLBACK = ""
SPEECH_REGION_FALLBACK = ""

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY") or SPEECH_KEY_FALLBACK
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION") or SPEECH_REGION_FALLBACK

# Optional: force a mic by exact device name (recommended on Windows)
# Example: "Microphone Array (Realtek High Definition Audio)"
AZURE_MIC_DEVICE = (os.getenv("AZURE_MIC_DEVICE") or "").strip()

# -----------------------------
# Helpers
# -----------------------------
def normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = " ".join(s.split())
    return s


def post_ingest(text: str, is_final: bool) -> str:
    text = normalize_text(text)
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


def list_azure_input_devices() -> List[str]:
    """
    Azure SDK can enumerate audio devices on Windows/macOS.
    On some machines this may return empty; we handle that.
    """
    try:
        devices = speechsdk.audio.AudioConfig.get_microphone_names()
        return [d for d in (devices or []) if isinstance(d, str) and d.strip()]
    except Exception:
        return []


def pick_best_mic_device(preferred: str = "") -> Tuple[Optional[str], str]:
    """
    Returns (device_name_or_none, reason)
    - If preferred provided and found (exact match), use it
    - Else try best auto-pick: prefer WASAPI device containing "Microphone Array"
    - Else fall back to any device containing "Microphone"
    - Else None (use default microphone)
    """
    devices = list_azure_input_devices()

    if preferred:
        if preferred in devices:
            return preferred, "env_exact_match"
        # try case-insensitive contains match
        low = preferred.lower()
        for d in devices:
            if low == d.lower():
                return d, "env_case_insensitive_match"
        for d in devices:
            if low in d.lower():
                return d, "env_contains_match"
        return None, "env_not_found_fallback_default"

    # Auto-pick logic
    # Prefer WASAPI if it appears in name; otherwise just pick a sensible mic-like device.
    # Note: device naming differs by machine.
    def score(name: str) -> int:
        n = name.lower()
        s = 0
        if "wasapi" in n:
            s += 50
        if "microphone array" in n:
            s += 30
        if "microphone" in n:
            s += 10
        # avoid virtual / mapper devices if present
        if "sound mapper" in n:
            s -= 20
        return s

    if devices:
        best = max(devices, key=score)
        if score(best) > 0:
            return best, "auto_best_match"
        return devices[0], "auto_first_device"

    return None, "no_device_list_use_default"


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        print("[STT] ERROR: Azure credentials not set.")
        print("Set environment variables (recommended):")
        print("  AZURE_SPEECH_KEY")
        print("  AZURE_SPEECH_REGION   (e.g. canadaeast)")
        print("\nPowerShell:")
        print('  setx AZURE_SPEECH_KEY "YOUR_KEY_HERE"')
        print('  setx AZURE_SPEECH_REGION "canadaeast"')
        print("Then CLOSE and reopen PowerShell.")
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

    # rapid restart tracking
    restart_times: List[float] = []

    # shared state for buffering + silence flush
    lock = threading.Lock()
    partial_buffer = ""
    last_activity_at = time.time()
    last_partial_sent_at = 0.0

    # final dedupe
    last_final_text = ""
    last_final_at = 0.0
    FINAL_DEDUPE_WINDOW_SEC = 4.0

    # recognizer lifecycle state
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
        text = normalize_text(text)
        if not text:
            return

        now = time.time()
        if text == last_final_text and (now - last_final_at) < FINAL_DEDUPE_WINDOW_SEC:
            return

        last_final_text = text
        last_final_at = now

        status = post_ingest(text, is_final=True)
        print(f"[FINAL] ({reason}) {text}")
        print(f"   -> {status}\n")

        with lock:
            partial_buffer = ""

    def build_recognizer() -> speechsdk.SpeechRecognizer:
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY,
            region=AZURE_SPEECH_REGION,
        )
        speech_config.speech_recognition_language = LANGUAGE

        # IMPORTANT: force mic device if we have one
        if chosen_device:
            audio_config = speechsdk.audio.AudioConfig(device_name=chosen_device)
        else:
            audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

        return speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    recognizer: Optional[speechsdk.SpeechRecognizer] = None

    def attach_handlers(rec: speechsdk.SpeechRecognizer) -> None:
        def on_recognizing(evt: speechsdk.SpeechRecognitionEventArgs):
            nonlocal partial_buffer, last_activity_at
            text = normalize_text(getattr(evt.result, "text", "") or "")
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
            text = normalize_text(getattr(evt.result, "text", "") or "")
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

    # Silence flush loop
    def silence_flush_loop():
        nonlocal partial_buffer
        while not stop_event.is_set():
            time.sleep(0.12)
            with lock:
                buf = normalize_text(partial_buffer)
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
                restart_times[:] = [t for t in restart_times if now - t <= RAPID_RESTART_WINDOW_SEC]

                if len(restart_times) > MAX_RAPID_RESTARTS:
                    print("\n[STT] Too many rapid restarts.")
                    print("[STT] Likely causes on Windows:")
                    print("  - Another app has the mic in Exclusive Mode")
                    print("  - Wrong input device / driver path (try setting AZURE_MIC_DEVICE)")
                    print("  - Audio enhancements/driver quirks (try disabling enhancements)")
                    print("\n[STT] Tip: set AZURE_MIC_DEVICE to your mic name exactly, e.g.:")
                    print('  setx AZURE_MIC_DEVICE "Microphone Array (Realtek High Definition Audio)"')
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
    main()
