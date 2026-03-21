# ======================================================
# KJV LIVE VERSE ENGINE — API SERVER (NO STT INSIDE)
# ======================================================

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import json
import time
import re
import logging
from collections import Counter
from typing import Dict, Any, List, Optional

# =========================================================
# IMPORT MATCH ENGINE
# =========================================================

from match_verse import (
    load_verses_index,
    load_json,
    build_phrase_lookup,
    match_scripture
)

# =========================================================
# FILES
# =========================================================

VERSES_FILE = "verses_index_enriched.json"
FALLBACK_VERSES_FILE = "verses_index.json"
KEYWORD_INDEX_FILE = "keyword_index.json"
PHRASE_DICT_FILE = "phrase_dictionary.json"

# =========================================================
# LOAD MATCH DATA
# =========================================================

VERSES = load_verses_index()
KEYWORD_INDEX = load_json(KEYWORD_INDEX_FILE)

try:
    phrase_entries = load_json(PHRASE_DICT_FILE)
    if not isinstance(phrase_entries, list):
        phrase_entries = []
except FileNotFoundError:
    phrase_entries = []

PHRASE_LOOKUP = build_phrase_lookup(phrase_entries)

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
# DEBUG / LOGGING
# =========================================================

DEBUG_MATCH_LOGS = False

def debug_log(*args):
    if DEBUG_MATCH_LOGS:
        print(*args)

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

    # RANGE: John 3:16-18
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
    return match_scripture(text, VERSES, KEYWORD_INDEX, PHRASE_LOOKUP)

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
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


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

    debug_log("MATCH_ROUTE_TEXT:", repr(text))

    if debounce(s, text):
        debug_log("MATCH_ROUTE_RESULT: duplicate")
        return {"status": "duplicate"}

    r = match_text(text)
    debug_log("MATCH_ROUTE_MATCH_TEXT_RESULT:", r)

    if not r.get("best"):
        debug_log("MATCH_ROUTE_RESULT: no_match")
        return {"status": "no_match"}

    if held(s, r["mode"]):
        debug_log("MATCH_ROUTE_RESULT: held")
        return {"status": "held"}

    if DISPLAY_MODE == "assist" and not (
        REFERENCE_AUTODISPLAY_IN_ASSIST and r["mode"] in ("reference", "reference_range")
    ):
        if r["mode"] == "keyword" and r["confidence"] < KEYWORD_MIN_CONFIDENCE_TO_SUGGEST:
            debug_log("MATCH_ROUTE_RESULT: no_match(keyword low confidence)")
            return {"status": "no_match"}
        s["pending"] = r
        debug_log("MATCH_ROUTE_RESULT: pending")
        return {"status": "pending", "result": r}

    s["current"] = r
    s["current_at"] = time.time()
    s["pending"] = None
    debug_log("MATCH_ROUTE_RESULT: displayed")
    return {"status": "displayed", "result": r}

# =========================================================
# INGEST (for STT OR any external client)
# =========================================================

@app.post("/ingest")
def ingest(payload: Dict[str, Any]):
    sid = payload.get("session_id", "demo")
    text = payload.get("text", "").strip()
    is_final = bool(payload.get("is_final"))

    s = get_session(sid)

    if text:
        s["buffer"] = text

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
# CONTROL PANEL (rich UI, with /control redirect)
# =========================================================

@app.get("/control")
def control_root():
    return RedirectResponse("/control/demo")


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
    background: #ffffff;
    padding: 30px 40px;
    border-radius: 12px;
    max-width: 1000px;
    margin: 40px auto;
    box-shadow: 0 10px 28px rgba(0,0,0,0.08);
    border: 1px solid #f0f0f0;
}}
h1 {{
  margin-top: 0;
  font-size: 30px;
  font-weight: 800;
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
  <h1>VerseCast Control Panel (session: {sid})</h1>

<div class="config-line">
Mode: {DISPLAY_MODE} | Hold: {int(HOLD_SECONDS)}s
</div>

  <div class="section-title">Enter Reference or Phrase</div>
  <div class="input-row">
    <input id="t" value=""/>
    <button onclick="match()">Match</button>
  </div>
  <div class="hint"></div>

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

  <div class="section-title">Status</div>
  <pre id="status_box">{{ "status": "idle" }}</pre>
</div>

<script>
async function refresh() {{
  let r = await fetch('/current/{sid}');
  let s = await r.json();
  let p = s.pending;

  if (p && p.best) {{
    document.getElementById('pending_box').style.display = 'block';

    const v = p.best || {{}};
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

refresh();
setInterval(refresh, 1500);
</script>
</body>
</html>
"""

# ================================================================
# PRESENTER (redesigned, supports ranges + styling + auto font size)
# ================================================================

@app.get("/presenter")
def presenter_root():
    return RedirectResponse("/presenter/demo")


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
  background: #2b124c;
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
  color: #f9e79f;
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
  line-height: 1.5;
  white-space: pre-wrap;
  text-shadow: 0 0 12px rgba(0,0,0,0.7);
  transition: font-size 0.25s ease-in-out;
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
  color: #f1c40f;
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
  const container = document.getElementById('text');

  if (!rawText) {{
    container.innerHTML = "";
    return;
  }}

  const lines = rawText.split(/\\r?\\n/).filter(l => l.trim().length > 0);

  let fontSize;
  if (lines.length === 1) {{
    fontSize = 50;
  }} else if (lines.length === 2) {{
    fontSize = 40;
  }} else if (lines.length <= 4) {{
    fontSize = 36;
  }} else if (lines.length <= 7) {{
    fontSize = 25;
  }} else {{
    fontSize = 20;
  }}

  container.style.fontSize = fontSize + "px";

  if (lines.length > 3) {{
    container.classList.add('scrollable');
  }} else {{
    container.classList.remove('scrollable');
  }}

  const htmlLines = lines.map(line => {{
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

    if (j.current && j.current.best) {{
      const v = j.current.best;
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