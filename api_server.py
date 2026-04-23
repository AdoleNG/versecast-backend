# ======================================================
# KJV LIVE VERSE ENGINE — API SERVER (NO STT INSIDE)
# ======================================================
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
LISTENER_DATABASE_URL = os.getenv("LISTENER_DATABASE_URL")

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers.onboarding import router as onboarding_router
from routers.sessions import router as sessions_router
from routers.operators import router as operators_router

from core.supabase import get_admin_supabase
from core.auth import get_current_auth_user

import json
import time
import re
import logging
from collections import Counter
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import asyncpg
import requests
from core.websocket import broadcast_to_church   # or wherever this lives

import sys
print("SERVER STARTED", file=sys.stderr)
print("BACKEND STARTED — LOGGING WORKS")
print("STATIC EXISTS:", os.path.isdir("static"))

# -------------------------
# LOGGING
# -------------------------
# Configure logging ONCE
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# =========================================================
# IMPORT MATCH ENGINE
# =========================================================

from match_verse import (
    load_verses_index,
    load_json,
    build_phrase_lookup,
    match_scripture,
)

# =========================================================
# FILES
# =========================================================

VERSES_FILE = "verses_index_enriched.json"
FALLBACK_VERSES_FILE = "verses_index.json"
KEYWORD_INDEX_FILE = "keyword_index.json"
PHRASE_DICT_FILE = "phrase_dictionary.json"

# =========================================================
# LOAD MATCH DATA (BLOCK 1 — USING load_verses_index)
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
    "the",
    "and",
    "of",
    "to",
    "in",
    "that",
    "a",
    "an",
    "for",
    "is",
    "it",
    "as",
    "be",
    "with",
    "by",
    "this",
    "from",
    "or",
    "at",
    "was",
    "were",
    "are",
    "but",
    "not",
    "into",
    "unto",
    "thou",
    "thee",
    "thy",
    "ye",
    "you",
    "your",
    "yours",
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
# REFERENCE PARSING (WITH RANGE SUPPORT)
# =========================================================

BOOK_ALIASES = {
    "genesis": "Genesis",
    "gen": "Genesis",
    "exodus": "Exodus",
    "exo": "Exodus",
    "exod": "Exodus",
    "leviticus": "Leviticus",
    "lev": "Leviticus",
    "numbers": "Numbers",
    "num": "Numbers",
    "deuteronomy": "Deuteronomy",
    "deut": "Deuteronomy",
    "joshua": "Joshua",
    "josh": "Joshua",
    "judges": "Judges",
    "judg": "Judges",
    "ruth": "Ruth",
    "1 samuel": "1 Samuel",
    "first samuel": "1 Samuel",
    "1st samuel": "1 Samuel",
    "i samuel": "1 Samuel",
    "2 samuel": "2 Samuel",
    "second samuel": "2 Samuel",
    "2nd samuel": "2 Samuel",
    "ii samuel": "2 Samuel",
    "1 kings": "1 Kings",
    "first kings": "1 Kings",
    "1st kings": "1 Kings",
    "i kings": "1 Kings",
    "2 kings": "2 Kings",
    "second kings": "2 Kings",
    "2nd kings": "2 Kings",
    "ii kings": "2 Kings",
    "1 chronicles": "1 Chronicles",
    "first chronicles": "1 Chronicles",
    "1st chronicles": "1 Chronicles",
    "i chronicles": "1 Chronicles",
    "2 chronicles": "2 Chronicles",
    "second chronicles": "2 Chronicles",
    "2nd chronicles": "2 Chronicles",
    "ii chronicles": "2 Chronicles",
    "ezra": "Ezra",
    "nehemiah": "Nehemiah",
    "neh": "Nehemiah",
    "esther": "Esther",
    "job": "Job",
    "psalm": "Psalms",
    "psalms": "Psalms",
    "ps": "Psalms",
    "proverbs": "Proverbs",
    "prov": "Proverbs",
    "ecclesiastes": "Ecclesiastes",
    "eccl": "Ecclesiastes",
    "song of solomon": "Song of Solomon",
    "song of songs": "Song of Solomon",
    "songs of solomon": "Song of Solomon",
    "solomon": "Song of Solomon",
    "isaiah": "Isaiah",
    "isa": "Isaiah",
    "jeremiah": "Jeremiah",
    "jer": "Jeremiah",
    "lamentations": "Lamentations",
    "lam": "Lamentations",
    "ezekiel": "Ezekiel",
    "ezek": "Ezekiel",
    "daniel": "Daniel",
    "dan": "Daniel",
    "hosea": "Hosea",
    "joel": "Joel",
    "amos": "Amos",
    "obadiah": "Obadiah",
    "obad": "Obadiah",
    "jonah": "Jonah",
    "micah": "Micah",
    "nahum": "Nahum",
    "habakkuk": "Habakkuk",
    "hab": "Habakkuk",
    "zephaniah": "Zephaniah",
    "zeph": "Zephaniah",
    "haggai": "Haggai",
    "zechariah": "Zechariah",
    "zech": "Zechariah",
    "malachi": "Malachi",
    "mal": "Malachi",
    "matthew": "Matthew",
    "matt": "Matthew",
    "mark": "Mark",
    "luke": "Luke",
    "john": "John",
    "acts": "Acts",
    "romans": "Romans",
    "rom": "Romans",
    "romance": "Romans",
    "1 corinthians": "1 Corinthians",
    "1 cor": "1 Corinthians",
    "first corinthians": "1 Corinthians",
    "1st corinthians": "1 Corinthians",
    "i corinthians": "1 Corinthians",
    "2 corinthians": "2 Corinthians",
    "2 cor": "2 Corinthians",
    "second corinthians": "2 Corinthians",
    "2nd corinthians": "2 Corinthians",
    "ii corinthians": "2 Corinthians",
    "galatians": "Galatians",
    "gal": "Galatians",
    "ephesians": "Ephesians",
    "eph": "Ephesians",
    "philippians": "Philippians",
    "phil": "Philippians",
    "colossians": "Colossians",
    "col": "Colossians",
    "1 thessalonians": "1 Thessalonians",
    "first thessalonians": "1 Thessalonians",
    "1st thessalonians": "1 Thessalonians",
    "i thessalonians": "1 Thessalonians",
    "2 thessalonians": "2 Thessalonians",
    "second thessalonians": "2 Thessalonians",
    "2nd thessalonians": "2 Thessalonians",
    "ii thessalonians": "2 Thessalonians",
    "1 timothy": "1 Timothy",
    "first timothy": "1 Timothy",
    "1st timothy": "1 Timothy",
    "i timothy": "1 Timothy",
    "2 timothy": "2 Timothy",
    "second timothy": "2 Timothy",
    "2nd timothy": "2 Timothy",
    "ii timothy": "2 Timothy",
    "titus": "Titus",
    "philemon": "Philemon",
    "hebrews": "Hebrews",
    "heb": "Hebrews",
    "james": "James",
    "1 peter": "1 Peter",
    "first peter": "1 Peter",
    "1st peter": "1 Peter",
    "i peter": "1 Peter",
    "2 peter": "2 Peter",
    "second peter": "2 Peter",
    "2nd peter": "2 Peter",
    "ii peter": "2 Peter",
    "1 john": "1 John",
    "first john": "1 John",
    "1st john": "1 John",
    "i john": "1 John",
    "2 john": "2 John",
    "second john": "2 John",
    "2nd john": "2 John",
    "ii john": "2 John",
    "3 john": "3 John",
    "third john": "3 John",
    "3rd john": "3 John",
    "iii john": "3 John",
    "jude": "Jude",
    "revelation": "Revelation",
    "revelations": "Revelation",
    "rev": "Revelation",
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
    m = re.search(
        rf"\b({BOOK_PATTERN})\s+(\d+):(\d+)\s*[-–]\s*(\d+)\b", raw, re.IGNORECASE
    )
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
    m = re.search(
        rf"\b({BOOK_PATTERN})\s+(\d+):(\d+)\b", t, re.IGNORECASE
    )
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
# SESSION STATE (IN-MEMORY)
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


def get_session(sid: str):
    if sid not in SESSIONS:
        SESSIONS[sid] = new_session()
    return SESSIONS[sid]


def debounce(session, text):
    now = time.time()
    if (
        session["last_input"] == text
        and (now - session["last_at"]) * 1000 < DEBOUNCE_MS
    ):
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

# -------------------------------
# Supabase DELETE event listener
# -------------------------------

async def handle_session_deleted(conn, pid, channel, payload):
    """
    Called automatically when a session row is deleted in Supabase.
    """
    try:
        data = json.loads(payload)
        church_id = data.get("church_id")

        if church_id:
            print(f"[Supabase] Session deleted for church {church_id}. Forcing end.")
            await force_end_session_internal(church_id)

    except Exception as e:
        print("Error handling session_deleted event:", e)


async def listen_for_session_deletes():
    """
    Opens a persistent live connection to Supabase Postgres
    and listens for delete events with auto-reconnect.
    """
    print("DEBUG: Starting listener...", flush=True)
    print("DEBUG: Listener DB URL loaded", flush=True)

    while True:
        conn = None

        try:
            conn = await asyncpg.connect(
                LISTENER_DATABASE_URL,
                timeout=20,
                command_timeout=60,
                ssl="require",
            )

            await conn.add_listener("session_deleted", handle_session_deleted)
            print("Listening for Supabase session delete events...", flush=True)

            while True:
                await asyncio.sleep(30)

        except Exception as e:
            print("Listener error:", repr(e), flush=True)

        finally:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass

        print("Reconnecting listener in 5 seconds...", flush=True)
        await asyncio.sleep(5)


async def force_end_session_internal(church_id: str):
    """
    Forcefully end a session even if the Supabase row is gone.
    """
    # Stop STT worker
    try:
        response = requests.post(
            "https://versecast-backend-websocket.onrender.com/stop-worker",
            timeout=10,
        )
        print(f"STT stop-worker response: {response.status_code}", flush=True)
    except Exception as e:
        print(f"Failed to stop STT worker: {e}", flush=True)

    # Broadcast to Control Panel + Presenter
    await broadcast_to_church(church_id, {"type": "session_ended"})

    print(f"Force-ended session for church {church_id}")

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# ------------------------------
# CORS CONFIGURATION
# ------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "https://versecast-site.onrender.com",
        "https://www.versecast.ca",
        "https://versecast.ca",
        "https://app.versecast.ca",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# -------------------------
# HEALTH CHECK
# -------------------------
@app.get("/", tags=["health"])
async def health_check():
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(listen_for_session_deletes())

# ============================================================
# MANUAL MATCH ROUTE — MUST BE ABOVE ROUTER INCLUDES
# ============================================================

@app.post("/match")
def match_route(payload: Dict[str, Any]):
    try:
        sid = payload.get("session_id", "demo")
        text = payload.get("text", "").strip()
        s = get_session(sid)

        # -----------------------------------------
        # START TIMER
        # -----------------------------------------
        import time
        start = time.time()

        r = match_text(text)
        # -----------------------------------------
        # END TIMER
        # -----------------------------------------
        duration = time.time() - start
        print(f"MATCH_TIME: {duration:.4f} seconds")

        if not r.get("best"):
            return {"status": "no_match"}

        mode = r.get("mode")

        # -----------------------------------------
        # AUTO‑APPROVE EXPLICIT REFERENCES
        # -----------------------------------------
        if mode in ("reference", "reference_range"):
            s["current"] = r
            s["current_at"] = time.time()
            s["pending"] = None
            return {"status": "displayed", "result": r}

        # -----------------------------------------
        # OTHERWISE → PENDING (normal behavior)
        # -----------------------------------------
        s["pending"] = r
        return {"status": "pending", "result": r}

    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ============================================================
# ROUTERS — MUST COME AFTER /match
# ============================================================

app.include_router(onboarding_router)
app.include_router(sessions_router)
app.include_router(operators_router)


# -------------------------
# GLOBAL EXCEPTION HANDLER
# -------------------------

@app.exception_handler(Exception)
async def handler(request, exc):
    origin = request.headers.get("origin")
    headers = {}

    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"

    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
        headers=headers
    )


# =========================================================
# SUPABASE HELPERS FOR MULTI-TENANCY
# =========================================================

def get_current_session_for_church(church_id: str):
    supabase = get_admin_supabase()

    res = (
        supabase.table("service_sessions")
        .select("id, church_id, title, started_at, ended_at")
        .eq("church_id", church_id)
        .is_("ended_at", None)
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )

    rows = res.data or []
    if not rows:
        return None

    return rows[0]


def get_user_church_id(user_id: str):
    supabase = get_admin_supabase()

    res = (
        supabase.table("users")
        .select("church_id")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    rows = res.data or []
    if not rows:
        return None

    return rows[0]["church_id"]


def get_current_session_for_user(user_id: str):
    church_id = get_user_church_id(user_id)
    if not church_id:
        return None

    return get_current_session_for_church(church_id)

# =========================================================
# SAAS SESSION ENDPOINTS (TENANT-AWARE)
# =========================================================

@app.get("/saas/session/current")
def saas_current_session(auth_user=Depends(get_current_auth_user)):
    """
    Return the current active session for the authenticated user's church.
    """
    session = get_current_session_for_user(auth_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session found for this user.",
        )

    return session


@app.post("/saas/session/start")
def saas_start_session(auth_user=Depends(get_current_auth_user)):
    """
    Start a new service session for the authenticated user's church.
    """
    church_id = get_user_church_id(auth_user.id)
    if not church_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a church.",
        )

    supabase = get_admin_supabase()

    res = (
        supabase.table("service_sessions")
        .insert(
            {
                "church_id": church_id,
                "title": "Live Service",
                "started_at": datetime.utcnow().isoformat() + "Z",
                "ended_at": None,
            }
        )
        .select("id, church_id, title, started_at, ended_at")
        .single()
        .execute()
    )

    session = res.data
    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create session.",
        )

    return session

@app.post("/saas/session/end")
def saas_end_session(auth_user=Depends(get_current_auth_user)):
    """
    End the current active service session for the authenticated user's church.
    """
    church_id = get_user_church_id(auth_user.id)
    if not church_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a church.",
        )

    # Find the active session
    supabase = get_admin_supabase()
    res = (
        supabase.table("service_sessions")
        .select("id, ended_at")
        .eq("church_id", church_id)
        .is_("ended_at", None)
        .single()
        .execute()
    )

    session = res.data
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session to end.",
        )

    # Mark it ended
    update_res = (
        supabase.table("service_sessions")
        .update({"ended_at": datetime.utcnow().isoformat() + "Z"})
        .eq("id", session["id"])
        .execute()
    )

    return {"status": "ended", "session_id": session["id"]}

@app.get("/saas/session/history")
def saas_session_history(auth_user=Depends(get_current_auth_user)):
    """
    Return recent sessions for the authenticated user's church.
    """
    church_id = get_user_church_id(auth_user.id)
    if not church_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a church.",
        )

    supabase = get_admin_supabase()

    res = (
        supabase.table("service_sessions")
        .select("id, church_id, title, started_at, ended_at")
        .eq("church_id", church_id)
        .order("started_at", desc=True)
        .limit(50)
        .execute()
    )

    return res.data or []

# =========================================================
# LIVE REDIRECTS (TENANT-AWARE)
# =========================================================

@app.get("/control/live")
def control_live(auth_user=Depends(get_current_auth_user)):
    session = get_current_session_for_user(auth_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session found for this user.",
        )

    sid = session["id"]
    return RedirectResponse(url=f"/control/{sid}", status_code=307)


@app.get("/presenter/live")
def presenter_live(auth_user=Depends(get_current_auth_user)):
    session = get_current_session_for_user(auth_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session found for this user.",
        )

    sid = session["id"]
    return RedirectResponse(url=f"/presenter/{sid}", status_code=307)

# =========================================================
# INGEST (for STT OR any external client)
# =========================================================

@app.post("/ingest")
def ingest(payload: Dict[str, Any]):
    sid = payload.get("session_id")
    if not sid:
        return {"status": "error", "detail": "Missing session_id in ingest payload"}

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
# REAL-TIME SESSION ACTIONS (PUBLIC, SESSION-ID–SCOPED)
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
def get_current_state(sid: str):
    s = get_session(sid)
    return {
        "status": s.get("status", "idle"),
        "pending": s.get("pending"),
        "current": s.get("current"),
    }

# =========================================================
# CONTROL PANEL (rich UI, with /control redirect)
# =========================================================
@app.get("/control/{sid}", response_class=HTMLResponse)
def control(sid: str):
    short_sid = "…" + sid[-12:]

    # ================================================================
    # HTML START
    # ================================================================
    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>VerseCast Control Panel</title>
<link rel="icon" type="image/x-icon" href="/favicon.ico">
"""

    # ================================================================
    # CSS STYLES
    # ================================================================
    html += """
<style>
body {
  font-family: "Segoe UI", Arial, sans-serif;
  background: #f5f5f5;
  padding: 30px;
}
.panel {
  background: #ffffff;
  padding: 30px 40px;
  border-radius: 12px;
  max-width: 1000px;
  margin: 40px auto;
  box-shadow: 0 10px 28px rgba(0,0,0,0.08);
  border: 1px solid #f0f0f0;
}
h1 {
  margin-top: 0;
  font-size: 30px;
  font-weight: 800;
}
.section-title {
  margin-top: 30px;
  margin-bottom: 10px;
  font-size: 20px;
  font-weight: 700;
}
.input-row {
  display: flex;
  gap: 10px;
}
.input-row input {
  flex: 1;
  padding: 10px;
  font-size: 16px;
}
button {
  padding: 10px 18px;
  font-size: 15px;
  border-radius: 6px;
  cursor: pointer;
  border: none;
  background: #2563eb;
  color: white;
}
button.danger {
  background: #dc2626;
}
.pending-box {
  background: #fef3c7;
  padding: 15px;
  border-radius: 8px;
  border: 1px solid #fcd34d;
}
.pending-header {
  font-weight: bold;
  margin-bottom: 8px;
}
.verse-box {
  white-space: pre-wrap;
  font-size: 18px;
  margin-bottom: 8px;
}
.pending-meta {
  font-size: 14px;
  color: #555;
}
pre {
  background: #1e1e1e;
  color: #0f0;
  padding: 18px;
  border-radius: 6px;
  margin-top: 10px;
  white-space: pre-wrap;
  font-size: 14px;
}
</style>
"""

    # ================================================================
    # BODY START
    # ================================================================
    html += f"""
</head>
<body>

<div class="panel">
<h1>VerseCast Control Panel (session: {short_sid})</h1>
"""

    # ================================================================
    # HEADER + PRESENTER BUTTON
    # ================================================================
    html += f"""
<div style="margin-top: 10px; margin-bottom: 20px;">
  <button onclick="window.open('/presenter/{sid}', '_blank')" style='background:#16a34a;'>
    Open Presenter
  </button>
"""

    # ================================================================
    # STT BUTTONS
    # ================================================================
    html += """
  <div style="margin-top: 20px; margin-bottom: 20px;">
    <button id="enable_stt_btn" style="background:#2563eb;">Enable STT</button>
    <button id="disable_stt_btn" style="background:#dc2626; display:none;">Disable STT</button>
  </div>
</div>
"""

    # ================================================================
    # MANUAL MATCH INPUT
    # ================================================================
    html += """
<div class="section-title">Enter Reference or Phrase</div>
<div class="input-row">
  <input id="t" value=""/>
  <button onclick="match()">Match</button>
</div>
"""

    # ================================================================
    # PENDING BEST MATCH
    # ================================================================
    html += """
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
"""

    # ================================================================
    # STATUS BOX
    # ================================================================
    html += """
<div class="section-title">Status</div>
<pre id="status_box">{ "status": "idle" }</pre>

</div> <!-- END PANEL -->
"""

    # ================================================================
    # STT BACKGROUND ENGINE
    # ================================================================
    html += f"""
<script>
let audioContext = null;
let workletNode = null;
let mediaStream = null;
let ws = null;

async function enableSTT() {{
  const urlParams = new URLSearchParams(window.location.search);
  const token = urlParams.get("token");
  const sessionId = "{sid}";

  if (!token) {{
    alert("Missing token. Please start session from dashboard.");
    return;
  }}

  ws = new WebSocket(`wss://api.versecast.ca/stt/stream?token=${{token}}&session_id=${{sessionId}}`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {{
    console.log("STT WebSocket connected");
    ws.send(JSON.stringify({{
      type: "start",
      token: token,
      session_id: sessionId
    }}));
  }};

  ws.onclose = () => {{
    console.log("STT WebSocket closed");
  }};

  mediaStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
  audioContext = new AudioContext({{ sampleRate: 48000 }});

  await audioContext.audioWorklet.addModule("/static/audio-worklet-processor.js");

  const source = audioContext.createMediaStreamSource(mediaStream);
  workletNode = new AudioWorkletNode(audioContext, "versecast-processor");

  workletNode.port.onmessage = (event) => {{
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(event.data);
    }}
  }};

  source.connect(workletNode);
  workletNode.connect(audioContext.destination);

  document.getElementById("enable_stt_btn").style.display = "none";
  document.getElementById("disable_stt_btn").style.display = "inline-block";
}}

function disableSTT() {{
  try {{ ws?.send(JSON.stringify({{ type: "stop" }})); }} catch {{}}
  try {{ ws?.close(); }} catch {{}}
  try {{ workletNode?.disconnect(); }} catch {{}}
  try {{ audioContext?.close(); }} catch {{}}
  try {{ mediaStream?.getTracks().forEach(t => t.stop()); }} catch {{}}

  ws = null;
  audioContext = null;
  workletNode = null;
  mediaStream = null;

  document.getElementById("enable_stt_btn").style.display = "inline-block";
  document.getElementById("disable_stt_btn").style.display = "none";
}}

document.getElementById("enable_stt_btn").onclick = enableSTT;
document.getElementById("disable_stt_btn").onclick = disableSTT;
</script>
"""

    # ================================================================
    # REFRESH PANEL
    # ================================================================
    html += f"""
<script>
async function refresh() {{
  let r = await fetch('/current/{sid}', {{
    headers: {{ "Content-Type": "application/json" }}
  }});
  let s = await r.json();
  let p = s.pending;

  if (p && p.best) {{
    document.getElementById('pending_box').style.display = 'block';
    const v = p.best;
    document.getElementById('pending_ref').textContent = v.reference || v.ref || '';
    document.getElementById('pending_text').textContent = v.text_kjv || v.text || '';
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
</script>
"""

    # ================================================================
    # MATCH
    # ================================================================
    html += f"""
<script>
async function match() {{
  let r = await fetch('/match', {{
    method: 'POST',
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{
      session_id: '{sid}',
      text: document.getElementById('t').value
    }})
  }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}
</script>
"""

    # ================================================================
    # APPROVE / CLEAR
    # ================================================================
    html += f"""
<script>
async function approve() {{
  let r = await fetch('/approve/{sid}', {{
    method: 'POST',
    headers: {{ "Content-Type": "application/json" }}
  }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}

async function clearPending() {{
  let r = await fetch('/clear_pending/{sid}', {{
    method: 'POST',
    headers: {{ "Content-Type": "application/json" }}
  }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}

async function clearAll() {{
  let r = await fetch('/clear_all/{sid}', {{
    method: 'POST',
    headers: {{ "Content-Type": "application/json" }}
  }});
  let j = await r.json();
  setStatusFromResponse(j);
  await refresh();
}}

refresh();
setInterval(refresh, 1500);
</script>
"""

    # ================================================================
    # HTML END
    # ================================================================
    html += """
</body>
</html>
"""

    return HTMLResponse(html)


# ================================================================
# FAVICON ROUTE (must be outside control())
# ================================================================
from fastapi.responses import FileResponse

@app.get("/favicon.ico")
def favicon():
    return FileResponse("static/favicon.ico")


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
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 40px;
}}
.reference {{
  font-size: 40px;
  font-weight: bold;
  margin-bottom: 20px;
}}
.passage-container {{
  flex: 1;
  overflow-y: auto;
}}
.passage {{
  white-space: pre-wrap;
  line-height: 1.4;
}}
.verse-line {{
  display: block;
  margin-bottom: 10px;
}}
.verse-number {{
  font-weight: bold;
  margin-right: 8px;
}}
.status-bar {{
  padding: 10px;
  font-size: 14px;
  color: #ddd;
}}
#versecast-tagline {{
  position: absolute;
  top: 10px;
  right: 20px;
  font-size: 1.2rem;
  color: #f5f5f5;
  opacity: 0.8;
  text-align: right;
  pointer-events: none;
}}

</style>
</head>

<body>
<div id="versecast-tagline">
  Thy word is a lamp unto my feet, and a light unto my path. (Psalm 119:105)
</div>

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
  if (lines.length === 1) fontSize = 50;
  else if (lines.length === 2) fontSize = 40;
  else if (lines.length <= 4) fontSize = 36;
  else if (lines.length <= 7) fontSize = 25;
  else fontSize = 20;

  container.style.fontSize = fontSize + "px";

  const htmlLines = lines.map(line => {{
    const match = line.match(/^\\s*([A-Za-z0-9 ]+\\s+\\d+:\\d+)(.*)$/);
    if (match) {{
      return `<span class="verse-line"><span class="verse-number">${{match[1].trim()}}</span>${{match[2].trimStart()}}</span>`;
    }}
    return `<span class="verse-line">${{line}}</span>`;
  }});

  container.innerHTML = htmlLines.join("\\n");
}}

async function refresh() {{
  try {{
    const r = await fetch('/current/{sid}', {{
      headers: {{ "Content-Type": "application/json" }}
    }});
    const j = await r.json();

    if (j.current && j.current.best) {{
      const v = j.current.best;
      document.getElementById('ref').innerText = v.reference || v.ref || '';
      renderPassage(v.text_kjv || v.text || '');
      document.getElementById('status').innerText = '';
    }} else {{
      document.getElementById('ref').innerText = 'Waiting...';
      document.getElementById('text').innerHTML = '';
      document.getElementById('status').innerText = j.status ? `Status: ${{j.status}}` : '';
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
