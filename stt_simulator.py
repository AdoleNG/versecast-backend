import time
import json
import threading
import urllib.request
from typing import Dict, Any

API_BASE = "http://127.0.0.1:8000"
SESSION_ID = "demo"

# 🔥 FAST TEST MODE
SILENCE_GAP_SECONDS = 5.0

_last_update_lock = threading.Lock()
_last_update_at = 0.0
_stop_event = threading.Event()


def post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def mark_update() -> None:
    global _last_update_at
    with _last_update_lock:
        _last_update_at = time.time()


def get_last_update_age() -> float:
    with _last_update_lock:
        if _last_update_at <= 0:
            return 1e9
        return time.time() - _last_update_at


def silence_watcher() -> None:
    """
    Background thread:
    If no STT updates for SILENCE_GAP_SECONDS,
    trigger /ingest flush=true.
    """
    while not _stop_event.is_set():
        time.sleep(0.5)
        age = get_last_update_age()

        if age >= SILENCE_GAP_SECONDS:
            try:
                r = post_json("/ingest", {"session_id": SESSION_ID, "flush": True})
                print(f"\n🔥 [AUTO FLUSH after {SILENCE_GAP_SECONDS:.0f}s silence] -> {r.get('status')}\n")
            except Exception as e:
                print(f"\n[silence_flush error] {e}\n")

            # reset so it doesn't keep firing
            mark_update()


def simulate_utterance(final_text: str, delay_s: float = 0.25, end_with_final: bool = True) -> None:
    """
    Simulates STT partial results by progressively revealing words.
    If end_with_final=False → silence watcher will flush.
    """
    words = final_text.split()
    partial = ""

    print("\n==============================")
    print("SIMULATING:", final_text)
    print("==============================")

    for i, w in enumerate(words):
        partial = (partial + " " + w).strip()
        payload = {
            "session_id": SESSION_ID,
            "text": partial,
            "is_final": False,
            "flush": False,
        }
        r = post_json("/ingest", payload)
        mark_update()
        print(f"[partial {i+1:02d}/{len(words):02d}] '{partial}' -> {r.get('status')}")
        time.sleep(delay_s)

    if end_with_final:
        payload = {
            "session_id": SESSION_ID,
            "text": final_text,
            "is_final": True,
            "flush": False,
        }
        r = post_json("/ingest", payload)
        mark_update()
        print(f"[final] -> {r.get('status')}")

        result = r.get("result")
        if isinstance(result, dict) and result.get("best"):
            best = result["best"]
            print("---- BEST ----")
            print(best.get("reference"))
            print(best.get("text_kjv"))
            print("mode:", result.get("mode"), "| conf:", result.get("confidence"))
        else:
            print("(no verse staged/displayed)")
    else:
        print(f"(no final — auto flush will trigger in {SILENCE_GAP_SECONDS:.0f}s)")


def main() -> None:
    print("STT Simulator -> /ingest")
    print("Server must be running:")
    print("  python -m uvicorn api_server:app --reload")
    print("Control:", f"{API_BASE}/control/demo")
    print("Presenter:", f"{API_BASE}/presenter/demo")
    print(f"Silence auto-flush: {SILENCE_GAP_SECONDS:.0f}s")
    print()

    mark_update()

    # start silence monitor
    t = threading.Thread(target=silence_watcher, daemon=True)
    t.start()

    samples = [
        ("Proverbs chapter 5 verse 21", True),
        ("John 317", True),
        ("Isaiah chapter 54 verse 17", True),
        ("we wrestle not against flesh and blood", False),
    ]

    for s, end_with_final in samples:
        simulate_utterance(s, delay_s=0.22, end_with_final=end_with_final)
        time.sleep(1.0)

    print("\nWaiting so you can observe silence flush...")
    time.sleep(SILENCE_GAP_SECONDS + 3)

    _stop_event.set()
    print("Done.")


if __name__ == "__main__":
    main()
