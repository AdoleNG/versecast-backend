# ======================================================
# KJV LIVE VERSE ENGINE — UPDATED WITH RANGE SUPPORT
# + Azure STT integrated as background task (session: demo)
# ======================================================

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

import json
import time
import re
import os
import threading
from collections import Counter
from typing import Dict, Any, List, Optional, Tuple

import requests
import azure.cognitiveservices.speech as speechsdk

# =========================================================
# FILES
# =========================================================

VERSES_FILE = "verses_index_enriched.json"
FALLBACK_VERSES_FILE = "verses_index.json"
KEYWORD_INDEX_FILE = "keyword_index.json"
PHRASE_DICT_FILE = "phrase_dictionary.json"

# =========================================================
# DISPLAY / WORKFLOW CONFIG
# =========================================================

DISPLAY_MODE = "assist"  # assist | auto
HOLD_SECONDS = 10.0
REFERENCE_OVERRIDES_HOLD = True
REFERENCE_AUTODISPLAY_IN_ASSIST = True
DEBOUNCE_MS = 700
REF_HOST = "openbible.hold.fun"
OBEDIENCE_MID = 700

# =========================================================
# MATCHING THRESHOLDS
# =========================================================

PHRASE_CONFIDENCE = 0.98
KEYWORD_MIN_CONFIDENCE_TO_DISPLAY = 0.60
KEYWORD_MIN_CONFIDENCE_TO_SUGGEST = 0.35
TOP_K_SUGGESTIONS = 3
MIN_TOKENS_FOR_KEYWORD_MODE = 4

# =========================================================
# TOKENIZATION
# =========================================================

STOPWORDS = {
    "the","and","of","to","in","that","a","an","for","is","it","as","be",
    "with","by","this","from","or","at","was","were","are","but","not",
    "into","unto","thou","thee","thy","ye","you","your","yours",
}
TOKEN_RE = re.compile(r"[a-z0-9']+")


def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'").replace("`", "'")
    # keep "-" for reference parsing patterns that use raw text
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(s: str) -> List[str]:
    tokens = TOKEN_RE.findall(normalize_text(s))
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def is_quote_like(tokens: List[str]) -> bool:
    return len(tokens) >= MIN_TOKENS_FOR_KEYWORD_MODE

# =========================================================
# LOAD DATA
# =========================================================

def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

try:
    VERSES: Dict[str, Dict[str, Any]] = load_json(VERSES_FILE)
except FileNotFoundError:
    VERSES = load_json(FALLBACK_VERSES_FILE)

KEYWORD_INDEX: Dict[str, List[str]] = load_json(KEYWORD_INDEX_FILE)

try:
    PHRASE_ENTRIES = load_json(PHRASE_DICT_FILE)
except FileNotFoundError:
    PHRASE_ENTRIES = []

PHRASE_LOOKUP: Dict[str, List[Dict[str, Any]]] = {}
for e in PHRASE_ENTRIES:
    p = normalize_text(e.get("phrase", ""))
    if p:
        PHRASE_LOOKUP.setdefault(p, []).append(e)

# =========================================================
# REFERENCE PARSING (WITH RANGE SUPPORT)
# =========================================================

BOOK_ALIASES = {
    "genesis":"Genesis","gen":"Genesis",
    "exodus":"Exodus","exo":"Exodus",
    "leviticus":"Leviticus","lev":"Leviticus",
    "numbers":"Numbers","num":"Numbers",
    "deuteronomy":"Deuteronomy","deut":"Deuteronomy",
    "joshua":"Joshua","josh":"Joshua",
    "judges":"Judges",
    "ruth":"Ruth",
    "1 samuel":"1 Samuel","2 samuel":"2 Samuel",
    "1 kings":"1 Kings","2 kings":"2 Kings",
    "psalm":"Psalms","psalms":"Psalms",
    "proverbs":"Proverbs",
    "isaiah":"Isaiah",
    "jeremiah":"Jeremiah",
    "ezekiel":"Ezekiel",
    "daniel":"Daniel",
    "matthew":"Matthew",
    "mark":"Mark",
    "luke":"Luke",
    "john":"John",
    "acts":"Acts",
    "romans":"Romans",
    "1 corinthians":"1 Corinthians",
    "2 corinthians":"2 Corinthians",
    "galatians":"Galatians",
    "ephesians":"Ephesians",
    "philippians":"Philippians",
    "colossians":"Colossians",
    "1 thessalonians":"1 Thessalonians",
    "2 thessalonians":"2 Thessalonians",
    "1 timothy":"1 Timothy",
    "2 timothy":"2 Timothy",
    "hebrews":"Hebrews",
    "james":"James",
    "1 peter":"1 Peter",
    "2 peter":"2 Peter",
    "revelation":"Revelation",
}

BOOK_PATTERN = "|".join(sorted(BOOK_ALIASES.keys(), key=len, reverse=True))


def normalize_book(b: str) -> str:
    return BOOK_ALIASES.get(b.lower().strip(), b.title())


def verse_id(book: str, ch: int, v: int) -> str:
    b = re.sub(r"[^A-Z0-9]+", "_", book.upper()).strip("_")
    return f"{b}_{ch}_{v}"


def parse_reference(text: str):
    raw = text or ""
    t = normalize_text(text or "")

    # RANGE: John 3:16-18 (use raw to keep "-")
    m = re.search(rf"\b({BOOK_PATTERN})\s+(\d+):(\d+)\s*[-–]\s*(\d+)\b", raw, re.IGNORECASE)
    if m:
        return {
            "type": "range",
            "book": normalize_book(m.group(1)),
            "chapter": int(m.group(2)),
            "start": int(m.group(3)),
            "end": int(m.group(4)),
        }

    # RANGE: John chapter 3 reading from verse 16 to 18
    m = re.search(
        rf"\b({BOOK_PATTERN}).*?chapter\s+(\d+).*?(?:reading\s+from\s+)?verse\s+(\d+)\s*(?:to|-|–)\s*(\d+)\b",
        t,
        re.IGNORECASE,
    )
    if m:
        return {
            "type": "range",
            "book": normalize_book(m.group(1)),
            "chapter": int(m.group(2)),
            "start": int(m.group(3)),
            "end": int(m.group(4)),
        }

    # SINGLE: John chapter 3 reading from verse 16
    m = re.search(
        rf"\b({BOOK_PATTERN}).*?chapter\s+(\d+).*?(?:reading\s+from\s+)?verse\s+(\d+)\b",
        t,
        re.IGNORECASE,
    )
    if m:
        return {
            "type": "single",
            "book": normalize_book(m.group(1)),
            "chapter": int(m.group(2)),
            "verse": int(m.group(3)),
        }

    # SINGLE: John 3:16
    m = re.search(rf"\b({BOOK_PATTERN})\s+(\d+):(\d+)\b", t, re.IGNORECASE)
    if m:
        return {
            "type": "single",
            "book": normalize_book(m.group(1)),
            "chapter": int(m.group(2)),
            "verse": int(m.group(3)),
        }

    return None

# =========================================================
# RANGE HANDLER
# =========================================================

def build_range(book: str, chapter: int, start: int, end: int):
    if end < start:
        start, end = end, start

    lines = []
    for v in range(start, end + 1):
        vid = verse_id(book, chapter, v)
        verse = VERSES.get(vid)
        if not verse:
            continue
        ref = verse.get("reference") or verse.get("ref") or f"{book} {chapter}:{v}"
        text = verse.get("text_kjv") or verse.get("text") or ""
        lines.append(f"{ref} {text}")

    if not lines:
        return None

    return {
        "mode": "reference_range",
        "confidence": 1.0,
        "verse": {
            "ref": f"{book} {chapter}:{start}–{end}",
            "text": "\n".join(lines),
        },
    }

# =========================================================
# MATCH ENGINE
# =========================================================

def phrase_match(text: str):
    norm = normalize_text(text)
    for p, entries in PHRASE_LOOKUP.items():
        if p in norm:
            vid = entries[0].get("verse_id")
            if vid and vid in VERSES:
                return {
                    "mode": "phrase",
                    "confidence": PHRASE_CONFIDENCE,
                    "verse": VERSES[vid],
                }
    return None


def keyword_match(text: str):
    tokens = tokenize(text)
    if not is_quote_like(tokens):
        return {"mode": "none"}

    counts = Counter(tokens)
    cands = set()
    for t in counts:
        for vid in KEYWORD_INDEX.get(t, []):
            cands.add(vid)

    scored = []
    for vid in cands:
        v = VERSES.get(vid)
        if not v:
            continue
        w = v.get("keyword_weights", {})
        overlap = sum(min(counts[t], w.get(t, 0)) for t in counts)
        conf = overlap / float(sum(counts.values()))
        scored.append((conf, v))

    if not scored:
        return {"mode": "none"}

    scored.sort(key=lambda x: x[0], reverse=True)
    conf, verse = scored[0]
    return {"mode": "keyword", "confidence": round(conf, 3), "verse": verse}


def match_text(text: str):
    ref = parse_reference(text)
    if ref:
        if ref["type"] == "range":
            r = build_range(ref["book"], ref["chapter"], ref["start"], ref["end"])
            if r:
                return r
        elif ref["type"] == "single":
            vid = verse_id(ref["book"], ref["chapter"], ref["verse"])
            if vid in VERSES:
                return {
                    "mode": "reference",
                    "confidence": 1.0,
                    "verse": VERSES[vid],
                }

    pm = phrase_match(text)
    if pm:
        return pm

    km = keyword_match(text)
    if km.get("verse"):
        return km

    return {"mode": "none"}

# =========================================================
# SESSION STATE
# =========================================================

def new_session():
    return {
        "current": None,
        "current_at": 0.0,
        "pending": None,
        "last_input": "",
        "last_at": 0.0,
        "buffer": "",
    }

SESSIONS: Dict[str, Dict[str, Any]] = {}


def get_session(sid):
    if sid not in SESSIONS:
        SESSIONS[sid] = new_session()
    return SESSIONS[sid]


def debounce(session, text):
    now = time.time()
    if session["last_input"] == text and (now - session["last_at"]) * 1000 < DEBOUNCE_MS:
        return True
    session["last_input"] = text
    session["last_at"] = now
    return False


def held(session, mode):
    if not session["current"]:
        return False
    if REFERENCE_OVERRIDES_HOLD and mode == "reference":
        return False
    return (time.time() - session["current_at"]) < HOLD_SECONDS

# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI()


@app.exception_handler(Exception)
async def handler(request, exc):
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/health")
def health():
    return {"ok": True}

# =========================================================
# MANUAL MATCH
# =========================================================

@app.post("/match")
def match_route(payload: Dict[str, Any]):
    sid = payload.get("session_id", "demo")
    text = payload.get("text", "").strip()
    s = get_session(sid)

    if debounce(s, text):
        return {"status": "duplicate"}

    r = match_text(text)
    if "verse" not in r:
        return {"status": "no_match"}

    if held(s, r["mode"]):
        return {"status": "held"}

    if DISPLAY_MODE == "assist" and not (
        REFERENCE_AUTODISPLAY_IN_ASSIST and r["mode"] == "reference"
    ):
        if r["mode"] == "keyword" and r["confidence"] < KEYWORD_MIN_CONFIDENCE_TO_SUGGEST:
            return {"status": "no_match"}
        s["pending"] = r
        return {"status": "pending", "result": r}

    s["current"] = r
    s["current_at"] = time.time()
    s["pending"] = None
    return {"status": "displayed", "result": r}

# =========================================================
# INGEST (STT)
# =========================================================

@app.post("/ingest")
def ingest(payload: Dict[str, Any]):
    sid = payload.get("session_id", "demo")
    text = payload.get("text", "").strip()
    is_final = bool(payload.get("is_final"))

    s = get_session(sid)

    if text:
        s["buffer"] = (s["buffer"] + " " + text).strip()

    if not is_final:
        return {"status": "buffered"}

    final = s["buffer"]
    s["buffer"] = ""
    return match_route({"session_id": sid, "text": final})

# =========================================================
# APPROVAL
# =========================================================

@app.post("/approve/{sid}")
def approve(sid: str):
    s = get_session(sid)
    if not s["pending"]:
        return {"status": "no_pending"}
    if held(s, s["pending"]["mode"]):
        return {"status": "held"}
    s["current"] = s["pending"]
    s["current_at"] = time.time()
    s["pending"] = None
    return {"status": "approved_displayed"}


@app.post("/clear_pending/{sid}")
def clear_pending(sid: str):
    s = get_session(sid)
    s["pending"] = None
    return {"status": "cleared_pending"}


@app.post("/clear_all/{sid}")
def clear_all(sid: str):
    SESSIONS[sid] = new_session()
    return {"status": "cleared_all"}


@app.get("/current/{sid}")
def current(sid: str):
    s = get_session(sid)
    return {"current": s["current"], "pending": s["pending"]}

# =========================================================
# CONTROL PANEL (rich, updated, with auto-refresh for STT)
# =========================================================

@app.get("/control/{sid}", response_class=HTMLResponse)
def control(sid: str):
    return f"""
<html>
<head>
<style>
body {{
  font-family: "Segoe UI", Arial, sans-serif;
  background: #f5f5f5;
  padding: 30px;
}}
.panel {{
  background: white;
  padding: 25px;
  border-radius: 10px;
  max-width: 900px;
  margin: auto;
  box-shadow: 0 3px 10px rgba(0,0,0,0.12);
}}
h1 {{
  margin-top: 0;
  font-size: 26px;
  font-weight: 600;
}}
.config-line {{
  font-size: 13px;
  color: #555;
  margin-bottom: 20px;
}}
.section-title {{
  font-size: 18px;
  font-weight: 600;
  margin-top: 25px;
  margin-bottom: 10px;
}}
.input-row {{
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}}
.input-row input {{
  flex: 1;
  height: 48px;
  font-size: 18px;
  padding: 8px 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
}}
button {{
  background: #0078ff;
  color: white;
  border: none;
  padding: 10px 18px;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
}}
button:hover {{
  background: #005fcc;
}}
.danger {{
  background: #d9534f;
}}
.danger:hover {{
  background: #b52b27;
}}
.pending-box {{
  background: #fff8e1;
  border-left: 5px solid #ffb300;
  padding: 15px;
  border-radius: 6px;
  margin-top: 10px;
}}
.pending-header {{
  font-weight: 600;
  margin-bottom: 5px;
}}
.pending-meta {{
  font-size: 13px;
  color: #555;
  margin-top: 5px;
}}
.verse-box {{
  background: #f0f0f0;
  padding: 12px;
  border-radius: 6px;
  margin-top: 8px;
  white-space: pre-wrap;
  font-size: 14px;
}}
pre {{
  background: #1e1e1e;
  color: #0f0;
  padding: 18px;
  border-radius: 6px;
  margin-top: 10px;
  white-space: pre-wrap;
  font-size: 14px;
}}
.hint {{
  font-size: 12px;
  color: #777;
  margin-top: 10px;
}}
</style>
</head>
<body>
<div class="panel">
  <h1>Control Panel (session: {sid})</h1>
  <div class="config-line">
    DISPLAY_MODE: {DISPLAY_MODE} &nbsp;|&nbsp;
    HOLD_SECONDS: {int(HOLD_SECONDS)} &nbsp;|&nbsp;
    REF: {REF_HOST} &nbsp;|&nbsp;
    OBEDIENCE_MID: {OBEDIENCE_MID}
  </div>

  <!-- INPUT + MATCH -->
  <div class="section-title">Enter Reference or Phrase</div>
  <div class="input-row">
    <input id="t" value="John 3:16"/>
    <button onclick="match()">Match</button>
  </div>
  <div class="hint"></div>

  <!-- PENDING SECTION -->
  <div class="section-title">Pending (Best)</div>
  <div id="pending_box" class="pending-box" style="display:none;">
    <div class="pending-header" id="pending_ref"></div>
    <div class="verse-box" id="pending_text"></div>
    <div class="pending-meta">
      Mode: <span id="pending_mode"></span>
      &nbsp;|&nbsp;
      Confidence: <span id="pending_conf"></span>
    </div>
    <div style="margin-top:12px;">
      <button onclick="approve()">Approve / Display</button>
      <button class="danger" onclick="clearPending()">Clear Pending</button>
      <button class="danger" onclick="clearAll()">Clear All</button>
    </div>
  </div>

  <!-- STATUS -->
  <div class="section-title">Status</div>
  <pre id="status_box">{{ "status": "idle" }}</pre>
</div>

<script>
async function refresh() {{
  let r = await fetch('/current/{sid}');
  let s = await r.json();
  let p = s.pending;
  if (p && p.verse) {{
    document.getElementById('pending_box').style.display = 'block';
    const v = p.verse || {{}};
    const ref = v.reference || v.ref || '';
    const text = v.text_kjv || v.text || '';
    document.getElementById('pending_ref').textContent = ref;
    document.getElementById('pending_text').textContent = text;
    document.getElementById('pending_mode').textContent = p.mode || '';
    document.getElementById('pending_conf').textContent = p.confidence ?? '';
  }} else {{
    document.getElementById('pending_box').style.display = 'none';
  }}
}}

function setStatusFromResponse(j) {{
  document.getElementById('status_box').textContent =
    JSON.stringify({{ status: j.status }}, null, 2);
}}

async function match() {{
  let r = await fetch('/match', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{
      session_id:'{sid}',
      text:document.getElementById('t').value
    }})
  }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}

async function approve() {{
  let r = await fetch('/approve/{sid}', {{ method:'POST' }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}

async function clearPending() {{
  let r = await fetch('/clear_pending/{sid}', {{ method:'POST' }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}

async function clearAll() {{
  let r = await fetch('/clear_all/{sid}', {{ method:'POST' }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}

// Initial load
refresh();
// 🔁 Auto-refresh so STT pending appears without Match or manual refresh
setInterval(refresh, 1500);
</script>
</body>
</html>
"""

# =========================================================
# PRESENTER (redesigned, supports ranges + styling)
# =========================================================

@app.get("/presenter/{sid}", response_class=HTMLResponse)
def presenter(sid: str):
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Presenter – {sid}</title>
<style>
body {{
  margin: 0;
  padding: 0;
  background: #2b124c; /* deep purple */
  color: #f5f5f5;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  display: flex;
  flex-direction: column;
  height: 100vh;
}}
.wrapper {{
  padding: 48px 72px;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}}
.reference {{
  font-size: 32px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #f9e79f; /* soft gold */
  margin-bottom: 24px;
}}
.passage-container {{
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  max-width: 1200px;
}}
.passage {{
  font-size: 40px;
  line-height: 1.5;
  white-space: pre-wrap;
  text-shadow: 0 0 12px rgba(0,0,0,0.7);
}}
.scrollable {{
  max-height: 60vh;
  overflow-y: auto;
}}
.verse-line {{
  display: block;
  margin-bottom: 12px;
}}
.verse-number {{
  color: #f1c40f; /* gold */
  font-weight: 600;
  margin-right: 8px;
}}
.status-bar {{
  font-size: 14px;
  opacity: 0.6;
  margin-top: 16px;
}}
</style>
</head>
<body>
<div class="wrapper">
  <div id="ref" class="reference">Waiting...</div>
  <div class="passage-container">
    <div id="text" class="passage"></div>
  </div>
  <div class="status-bar" id="status"></div>
</div>

<script>
function renderPassage(rawText) {{
  if (!rawText) {{
    document.getElementById('text').innerHTML = "";
    return;
  }}
  const lines = rawText.split(/\\r?\\n/).filter(l => l.trim().length > 0);
  const container = document.getElementById('text');

  // Add scroll if more than 3 lines
  if (lines.length > 3) {{
    container.classList.add('scrollable');
  }} else {{
    container.classList.remove('scrollable');
  }}

  const htmlLines = lines.map(line => {{
    // Try to detect "Book 3:5 ..." or "Luke 3:5 ..."
    const match = line.match(/^\\s*([A-Za-z0-9 ]+\\s+\\d+:\\d+)(.*)$/);
    if (match) {{
      const num = match[1].trim();
      const rest = match[2] || "";
      return `<span class="verse-line"><span class="verse-number">${{num}}</span>${{rest.trimStart()}}</span>`;
    }} else {{
      return `<span class="verse-line">${{line}}</span>`;
    }}
  }});
  container.innerHTML = htmlLines.join("\\n");
}}

async function refresh() {{
  try {{
    const r = await fetch('/current/{sid}');
    const j = await r.json();
    const statusEl = document.getElementById('status');
    if (j.current && j.current.verse) {{
      const v = j.current.verse;
      const ref = v.reference || v.ref || '';
      const text = v.text_kjv || v.text || '';
      document.getElementById('ref').innerText = ref || ' ';
      renderPassage(text);
      statusEl.innerText = '';
    }} else {{
      document.getElementById('ref').innerText = 'Waiting...';
      document.getElementById('text').innerHTML = '';
      statusEl.innerText = j.status ? `Status: ${{j.status}}` : '';
    }}
  }} catch (e) {{
    document.getElementById('status').innerText = 'Connection error – retrying...';
  }}
}}

refresh();
setInterval(refresh, 700);
</script>
</body>
</html>
"""

# =========================================================
# AZURE STT (embedded, HTTP calls preserved, session_id="demo")
# =========================================================

# STT config
API_BASE = "http://127.0.0.1:8000"
INGEST_URL = f"{API_BASE}/ingest"
MATCH_URL = f"{API_BASE}/match"
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

# Azure config (env preferred)
SPEECH_KEY_FALLBACK = ""
SPEECH_REGION_FALLBACK = ""

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY") or SPEECH_KEY_FALLBACK
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION") or SPEECH_REGION_FALLBACK

AZURE_MIC_DEVICE = (os.getenv("AZURE_MIC_DEVICE") or "").strip()


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


def post_match(text: str) -> str:
    text = stt_normalize_text(text)
    if not text:
        return "empty"

    payload = {"session_id": SESSION_ID, "text": text}
    try:
        r = requests.post(MATCH_URL, json=payload, timeout=HTTP_TIMEOUT_SEC)
        if r.ok:
            try:
                return r.json().get("status", "ok")
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


def run_stt_background() -> None:
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

        if status == "pending":
            m = post_match(text_norm)
            print(f"   [AUTO-MATCH] -> {m}")

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


@app.on_event("startup")
def start_stt_on_startup():
    # Run STT in a background thread; HTTP calls preserved; session_id="demo"
    threading.Thread(target=run_stt_background, daemon=True).start()
