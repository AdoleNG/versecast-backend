"""
stt_faster_whisper.py
Mic -> sounddevice -> resample to 16k -> faster-whisper -> POST /ingest

Includes:
- Auto-picks a working capture sample-rate, resamples to 16k for Whisper
- Partial buffering + silence flush FINAL
- Reference stitching:
    * stitches "Book chapter N" + later "verse M/was M" -> "Book chapter N verse M"
    * ALSO stitches split numbers: "Isaiah chapter 54" + later "was 17" -> "... verse 17"
    * ALSO stitches "Exodus chapter 20 verse" + later "20" -> "... verse 20"
- Extra cleanup to reduce garbage: maps common mishears (e.g., "exynos" -> "exodus", "judges" ok)
- Clean Ctrl+C shutdown (Windows friendly)
"""

import time
import queue
import threading
import signal
import re
from typing import Optional, Tuple

import numpy as np
import sounddevice as sd
import requests
from faster_whisper import WhisperModel


# -----------------------------
# CONFIG
# -----------------------------
API_BASE = "http://127.0.0.1:8000"
INGEST_URL = f"{API_BASE}/ingest"
SESSION_ID = "demo"

MODEL_SIZE = "tiny"          # tiny/base/small/medium/large-v3
DEVICE = "cpu"               # "cuda" if NVIDIA GPU + CUDA
COMPUTE_TYPE = "int8"        # cpu-friendly

# Whisper expects 16k input (we RESAMPLE to this)
WHISPER_SAMPLE_RATE = 16000
CHANNELS = 1

# Choose a device index, or None to use default input
# To list devices:
#   python -c "import sounddevice as sd; print(sd.query_devices())"
INPUT_DEVICE_INDEX: Optional[int] = None  # e.g. 1, 5, 9, etc.

# Chunking / cadence
TRANSCRIBE_WINDOW_SEC = 2.5
PARTIAL_SEND_EVERY_SEC = 0.8

# Silence flush
SILENCE_GAP_SEC = 5.0
SILENCE_RMS_THRESHOLD = 0.010

# Prevent runaway memory
MAX_BUFFER_SEC = 30.0

# Transcribe knobs (bias to English to reduce garbage)
LANGUAGE = "en"          # None for auto-detect
BEAM_SIZE = 1
VAD_FILTER = True


# -----------------------------
# Reference stitching (fix split references)
# -----------------------------
BOOKS_CANON = [
    "genesis","exodus","leviticus","numbers","deuteronomy",
    "joshua","judges","ruth",
    "1 samuel","2 samuel","1 kings","2 kings","1 chronicles","2 chronicles",
    "ezra","nehemiah","esther",
    "job","psalm","psalms","proverbs","ecclesiastes","song","song of solomon",
    "isaiah","jeremiah","lamentations","ezekiel","daniel",
    "hosea","joel","amos","obadiah","jonah","micah","nahum","habakkuk","zephaniah","haggai","zechariah","malachi",
    "matthew","mark","luke","john","acts","romans",
    "1 corinthians","2 corinthians","galatians","ephesians","philippians","colossians",
    "1 thessalonians","2 thessalonians",
    "1 timothy","2 timothy","titus","philemon",
    "hebrews","james","1 peter","2 peter","jude","revelation",
]

# Normalize common STT book mishears (keep this small + targeted)
BOOK_MISHEAR_MAP = {
    "exynos": "exodus",
    "judges": "judges",
    "jeremia": "jeremiah",
    "jeremias": "jeremiah",
    "psalms": "psalms",
    "psalm": "psalms",
}

# longest-first to avoid partial matches
BOOK_RE = r"(?:\b(?:1|2|3)\s+)?(?:%s)\b" % "|".join(sorted(set(BOOKS_CANON), key=len, reverse=True))

# "Daniel chapter 5" / "Judges 2" / "John chapter 3"
BOOK_CH_RE = re.compile(rf"(?i)\b({BOOK_RE})\s*(?:chapter\s*)?(\d{{1,3}})\b")

# "verse 8" / "vs 8" / "v 8" / "was 8"
VERSE_ONLY_RE = re.compile(r"(?i)\b(?:verse|vs|v|was)\s*(\d{1,3})\b")

# "chapter 20 verse" (verse number missing, often arrives as next chunk)
CH_VERSE_NO_NUM_RE = re.compile(rf"(?i)\b({BOOK_RE})\s*(?:chapter\s*)?(\d{{1,3}})\s*(?:verse|vs|v)\b(?!\s*\d)")

# Number-only chunk (e.g., "20", "17.")
NUMBER_ONLY_RE = re.compile(r"(?i)^\s*(\d{1,3})\s*\.?\s*$")

BOOK_CH_TTL_SEC = 12.0  # keep last "Book chapter N" for up to 12s waiting for "verse M"
VERSE_PROMPT_TTL_SEC = 8.0  # keep "Book chapter N verse" prompt for missing-number stitch


# -----------------------------
# Helpers
# -----------------------------
def now_s() -> float:
    return time.time()


def post_ingest(text: str, is_final: bool) -> str:
    try:
        payload = {"session_id": SESSION_ID, "text": text, "is_final": bool(is_final)}
        r = requests.post(INGEST_URL, json=payload, timeout=5)
        if r.ok:
            j = r.json()
            return j.get("status", "ok")
        return f"http_{r.status_code}"
    except Exception as e:
        return f"error:{type(e).__name__}"


def rms(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float32)
    return float(np.sqrt(np.mean(x * x) + 1e-12))


def normalize_stt_text(s: str) -> str:
    s = (s or "").strip()
    s = " ".join(s.split())
    return s


def canonicalize_books_in_text(text: str) -> str:
    """
    Light cleanup for common mishears. We only replace whole words.
    """
    t = " " + text.lower() + " "
    for bad, good in BOOK_MISHEAR_MAP.items():
        t = re.sub(rf"\b{re.escape(bad)}\b", good, t)
    return t.strip()


def resample_linear(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Simple linear resampler (no scipy dependency)."""
    if sr_in == sr_out:
        return x.reshape(-1).astype(np.float32)

    x1 = x.reshape(-1).astype(np.float32)
    n_in = len(x1)
    if n_in < 2:
        return x1

    duration = n_in / float(sr_in)
    n_out = int(duration * sr_out)
    if n_out < 2:
        return x1

    t_in = np.linspace(0.0, duration, num=n_in, endpoint=False)
    t_out = np.linspace(0.0, duration, num=n_out, endpoint=False)
    y = np.interp(t_out, t_in, x1).astype(np.float32)
    return y


def pick_working_input_settings(device_index: Optional[int]) -> Tuple[int, int]:
    """
    Returns (device_index, capture_sample_rate) that can open.
    Tries 16000 then falls back to device default sample rate.
    """
    if device_index is None:
        if isinstance(sd.default.device, (list, tuple)):
            device_index = sd.default.device[0]
        else:
            device_index = int(sd.default.device)

    dev = sd.query_devices(device_index, "input")
    default_sr = int(dev.get("default_samplerate", 48000))

    # Try 16k first
    try:
        sd.check_input_settings(device=device_index, samplerate=WHISPER_SAMPLE_RATE, channels=CHANNELS)
        return device_index, WHISPER_SAMPLE_RATE
    except Exception:
        pass

    # Fall back to device default
    sd.check_input_settings(device=device_index, samplerate=default_sr, channels=CHANNELS)
    return device_index, default_sr


# -----------------------------
# Audio buffer
# -----------------------------
class RingAudioBuffer:
    def __init__(self, sample_rate: int, max_seconds: float):
        self.sample_rate = sample_rate
        self.max_samples = int(sample_rate * max_seconds)
        self._buf = np.zeros((0, 1), dtype=np.float32)
        self._lock = threading.Lock()

    def append(self, x: np.ndarray) -> None:
        with self._lock:
            self._buf = np.concatenate([self._buf, x], axis=0)
            if len(self._buf) > self.max_samples:
                self._buf = self._buf[-self.max_samples :]

    def get_last_seconds(self, seconds: float) -> np.ndarray:
        n = int(self.sample_rate * seconds)
        with self._lock:
            if len(self._buf) == 0:
                return np.zeros((0, 1), dtype=np.float32)
            return self._buf[-n:].copy()

    def clear(self) -> None:
        with self._lock:
            self._buf = np.zeros((0, 1), dtype=np.float32)


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    print(f"[STT] Loading faster-whisper model: {MODEL_SIZE} ({DEVICE}/{COMPUTE_TYPE}) ...")
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    print("[STT] Model loaded.")
    print(f"[STT] Posting to: {INGEST_URL} (session_id={SESSION_ID})")
    print(f"[STT] Silence flush: {SILENCE_GAP_SEC:.1f}s (RMS<thr {SILENCE_RMS_THRESHOLD})")

    try:
        device_index, capture_sr = pick_working_input_settings(INPUT_DEVICE_INDEX)
    except Exception as e:
        print("[STT] ERROR: Could not find working mic settings.")
        print(f"[STT] {type(e).__name__}: {e}")
        print('\nRun: python -c "import sounddevice as sd; print(sd.query_devices())"')
        return

    dev = sd.query_devices(device_index, "input")
    print(f"[STT] Using input device {device_index}: {dev.get('name')}")
    print(f"[STT] Capture sample rate: {capture_sr} Hz  -> resample to {WHISPER_SAMPLE_RATE} Hz for Whisper")

    audio_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=50)
    ring = RingAudioBuffer(int(capture_sr), MAX_BUFFER_SEC)

    stop_event = threading.Event()

    last_voice_at = now_s()
    last_partial_send_at = 0.0
    last_partial_text = ""
    last_transcribe_at = 0.0

    # Reference stitch state
    last_book_ch = ""            # "isaiah chapter 54"
    last_book_ch_at = 0.0
    last_need_verse_num = ""     # "exodus chapter 20 verse" (waiting for number)
    last_need_verse_num_at = 0.0

    def audio_callback(indata, frames, time_info, status):
        try:
            audio_q.put_nowait(indata.copy())
        except queue.Full:
            pass

    def request_stop(*_args):
        stop_event.set()

    # Ctrl+C handling: signal + fallback (works well on Windows)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        print("[STT] Starting microphone stream...")
        stream = sd.InputStream(
            samplerate=capture_sr,
            channels=CHANNELS,
            dtype="float32",
            device=device_index,
            callback=audio_callback,
        )
    except Exception as e:
        print(f"[STT] ERROR: Unable to initialize microphone (device={device_index}).")
        print(f"[STT] {type(e).__name__}: {e}")
        print('\nTry: python -c "import sounddevice as sd; print(sd.query_devices())"')
        return

    with stream:
        print("\n[STT] 🎤 Listening... (Ctrl+C to stop)\n")

        while not stop_event.is_set():
            drained = False
            while True:
                try:
                    chunk = audio_q.get_nowait()
                    drained = True
                    ring.append(chunk)
                    if rms(chunk) >= SILENCE_RMS_THRESHOLD:
                        last_voice_at = now_s()
                except queue.Empty:
                    break

            if not drained:
                time.sleep(0.03)

            tnow = now_s()

            # periodic rolling-window transcription
            if tnow - last_transcribe_at >= TRANSCRIBE_WINDOW_SEC:
                last_transcribe_at = tnow

                window = ring.get_last_seconds(TRANSCRIBE_WINDOW_SEC)
                if len(window) == 0:
                    continue

                audio_16k = resample_linear(window, int(capture_sr), WHISPER_SAMPLE_RATE)

                segments, _info = model.transcribe(
                    audio_16k,
                    language=LANGUAGE,
                    beam_size=BEAM_SIZE,
                    vad_filter=VAD_FILTER,
                )

                text = " ".join([seg.text.strip() for seg in segments]).strip()
                text = normalize_stt_text(text)
                if not text:
                    continue

                text = canonicalize_books_in_text(text)

                # ---- capture "Book chapter N" if present ----
                m_bc = BOOK_CH_RE.search(text)
                if m_bc:
                    book = m_bc.group(1).strip().lower()
                    ch = m_bc.group(2)
                    last_book_ch = f"{book} chapter {ch}"
                    last_book_ch_at = now_s()

                # ---- capture "Book chapter N verse" missing number ----
                m_need = CH_VERSE_NO_NUM_RE.search(text)
                if m_need:
                    book = m_need.group(1).strip().lower()
                    ch = m_need.group(2)
                    last_need_verse_num = f"{book} chapter {ch} verse"
                    last_need_verse_num_at = now_s()

                # ---- stitch: if text is number-only and we recently saw "... verse" ----
                m_numonly = NUMBER_ONLY_RE.match(text)
                if (
                    m_numonly
                    and last_need_verse_num
                    and (now_s() - last_need_verse_num_at) <= VERSE_PROMPT_TTL_SEC
                ):
                    vnum = m_numonly.group(1)
                    text = f"{last_need_verse_num} {vnum}"

                # ---- stitch Verse-only with prior Book+Chapter ----
                m_vo = VERSE_ONLY_RE.search(text)
                if m_vo and last_book_ch and (now_s() - last_book_ch_at) <= BOOK_CH_TTL_SEC:
                    verse = m_vo.group(1)
                    text = f"{last_book_ch} verse {verse}"

                # send partials (throttled)
                if (tnow - last_partial_send_at) >= PARTIAL_SEND_EVERY_SEC and text != last_partial_text:
                    last_partial_send_at = tnow
                    last_partial_text = text
                    status = post_ingest(text, is_final=False)
                    print(f"[PARTIAL] {text}")
                    print(f"   -> {status}\n")

            # silence-based finalization
            if (tnow - last_voice_at) >= SILENCE_GAP_SEC:
                last_voice_at = tnow

                final_text = normalize_stt_text(last_partial_text)
                if not final_text:
                    continue

                final_text = canonicalize_books_in_text(final_text)

                # final stitch: number-only after "... verse"
                m_numonly2 = NUMBER_ONLY_RE.match(final_text)
                if (
                    m_numonly2
                    and last_need_verse_num
                    and (now_s() - last_need_verse_num_at) <= VERSE_PROMPT_TTL_SEC
                ):
                    vnum = m_numonly2.group(1)
                    final_text = f"{last_need_verse_num} {vnum}"

                # final stitch: verse-only (was/verse/vs)
                m_vo2 = VERSE_ONLY_RE.search(final_text)
                if m_vo2 and last_book_ch and (now_s() - last_book_ch_at) <= BOOK_CH_TTL_SEC:
                    verse = m_vo2.group(1)
                    final_text = f"{last_book_ch} verse {verse}"

                status = post_ingest(final_text, is_final=True)
                print(f"[FINAL] {final_text}")
                print(f"   -> {status}\n")

                last_partial_text = ""
                ring.clear()

        print("\n[STT] Stopping microphone...")

    print("[STT] Stopped.")


if __name__ == "__main__":
    main()
