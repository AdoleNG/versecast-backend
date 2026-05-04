import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, Union
from rapidfuzz import fuzz

# ============================================================
# DEBUG / LOGGING
# ============================================================

DEBUG_MATCHER_LOGS = False

def debug_log(*args):
    if DEBUG_MATCHER_LOGS:
        print(*args)

# ============================================================
# File paths
# ============================================================
VERSES_FILE = "verses_index_enriched.json"
FALLBACK_VERSES_FILE = "verses_index.json"
KEYWORD_INDEX_FILE = "keyword_index.json"
PHRASE_DICT_FILE = "phrase_dictionary.json"

# ============================================================
# Matching thresholds
# ============================================================
PHRASE_CONFIDENCE = 0.98

KEYWORD_MIN_CONFIDENCE_TO_DISPLAY = 0.60
KEYWORD_MIN_CONFIDENCE_TO_SUGGEST = 0.35
TOP_K_SUGGESTIONS = 3

MIN_TOKENS_FOR_KEYWORD_MODE = 4

KJV_FINGERPRINT_TOKENS = {
    "verily", "whosoever", "begotten", "thee", "thou", "thy", "ye",
    "unto", "hath", "saith", "wherefore", "lest", "thereof", "therein"
}

# ============================================================
# NEW: One-chapter books
# ============================================================
ONE_CHAPTER_BOOKS = {
    "obadiah",
    "philemon",
    "2 john",
    "3 john",
    "jude",
}

# ============================================================
# Tokenization + normalization
# ============================================================
STOPWORDS = {
    "the", "and", "of", "to", "in", "that", "a", "an", "for", "is", "it",
    "as", "be", "with", "by", "this", "from", "or", "at", "was", "were",
    "are", "but", "not", "into", "unto", "thou", "thee", "thy", "ye",
    "you", "your", "yours",
}

TOKEN_RE = re.compile(r"[a-z0-9']+")

def normalize_text(s: str) -> str:
    s = s.lower()
    s = s.replace("’", "'").replace("`", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(s: str) -> List[str]:
    s = normalize_text(s)
    tokens = TOKEN_RE.findall(s)

    expanded: List[str] = []
    for t in tokens:
        expanded.append(t)
        if t == "axe":
            expanded.append("ax")
        elif t == "ax":
            expanded.append("axe")

    return [t for t in expanded if t not in STOPWORDS and len(t) > 1]

def is_quote_like(quote: str, tokens: List[str]) -> bool:
    if any(t in KJV_FINGERPRINT_TOKENS for t in tokens):
        return True
    return len(tokens) >= MIN_TOKENS_FOR_KEYWORD_MODE

# ============================================================
# Loaders
# ============================================================
def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_verses_index() -> Dict[str, Dict[str, Any]]:
    try:
        return load_json(VERSES_FILE)
    except FileNotFoundError:
        return load_json(FALLBACK_VERSES_FILE)

# ============================================================
# Reference parsing
# ============================================================
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

ORDINAL_WORDS = {
    "first": "1",
    "second": "2",
    "third": "3",
    "1st": "1",
    "2nd": "2",
    "3rd": "3",
}

NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}

def normalize_book_name(book_raw: str):
    if not book_raw:
        return None

    b = book_raw.lower().strip()
    b = re.sub(r"[.,:;]", "", b)
    b = re.sub(r"\bthe book of\s+", "", b)
    b = re.sub(r"\bfirst\b", "1", b)
    b = re.sub(r"\bsecond\b", "2", b)
    b = re.sub(r"\bthird\b", "3", b)
    b = re.sub(r"\b1st\b", "1", b)
    b = re.sub(r"\b2nd\b", "2", b)
    b = re.sub(r"\b3rd\b", "3", b)
    b = re.sub(r"\biii\b", "3", b)
    b = re.sub(r"\bii\b", "2", b)
    b = re.sub(r"\bi\b", "1", b)
    b = re.sub(r"\s+", " ", b).strip()

    if b in BOOK_ALIASES:
        return BOOK_ALIASES[b]

    if b == "psalm":
        return "Psalms"

    return None

def verse_id_from_reference(book: str, chapter: int, verse: int) -> str:
    book_id = re.sub(r"[^A-Z0-9]+", "_", book.upper()).strip("_")
    return f"{book_id}_{chapter}_{verse}"

RefSingle = Tuple[str, int, int]
RefRange = Tuple[str, int, int, int]
RefParsed = Union[RefSingle, RefRange]

# ============================================================
# Reference helpers
# ============================================================

def strip_reference_leadin(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"[.,;!?]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    leadins = [
        r"^(?:let us|let's)\s+read\s+",
        r"^(?:we are|we're)\s+reading\s+from\s+",
        r"^(?:i am|i'm)\s+reading\s+from\s+",
        r"^reading\s+from\s+",
        r"^read\s+from\s+",
        r"^from\s+",
        r"^(?:please\s+)?turn\s+to\s+",
        r"^(?:please\s+)?open(?:\s+your\s+bibles?)?\s+to\s+",
    ]

    changed = True
    while changed:
        before = s
        for pat in leadins:
            s = re.sub(pat, "", s).strip()
        changed = (s != before)

    return s

def clean_for_reference(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'").replace("`", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = re.sub(r"[^a-z0-9:\-\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ============================================================
# Spoken numbers → digits
# ============================================================
_UNITS = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
    "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,
    "fourteen":14,"fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,
    "nineteen":19
}

_TENS = {
    "twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,
    "seventy":70,"eighty":80,"ninety":90
}

def words_to_int(tokens: List[str]) -> Optional[int]:
    if not tokens:
        return None

    t = [x for x in tokens if x != "and"]
    total = 0
    current = 0
    consumed = 0

    for w in t:
        if w in _UNITS:
            current += _UNITS[w]
            consumed += 1
        elif w in _TENS:
            current += _TENS[w]
            consumed += 1
        elif w == "hundred":
            if current == 0:
                current = 1
            current *= 100
            consumed += 1
        else:
            return None

    total += current
    return total if consumed > 0 else None

_NUMWORD_RE = re.compile(
    r"\b("
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|and)"
    r"(?:\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|and))*"
    r")\b"
)

def replace_spoken_numbers(s: str) -> str:
    def repl(m: re.Match) -> str:
        phrase = m.group(1)
        toks = phrase.split()
        val = words_to_int(toks)
        return str(val) if val is not None else phrase

    return _NUMWORD_RE.sub(repl, s)

def parse_reference(user_text: str) -> Optional[RefParsed]:
    t = clean_for_reference(user_text)
    t = replace_spoken_numbers(t)
    t = t.replace("–", "-").replace("—", "-")
    t = re.sub(r"[.,;!?()]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    alias_keys = sorted(BOOK_ALIASES.keys(), key=len, reverse=True)
    alias_pattern = r"\b(" + "|".join(re.escape(k) for k in alias_keys) + r")\b"

    for m_book in re.finditer(alias_pattern, t, flags=re.IGNORECASE):
        raw_book = m_book.group(1)
        book = normalize_book_name(raw_book)
        if not book:
            continue

        tail = t[m_book.end():].strip()
        if not tail:
            continue

        tail_norm = tail.lower()
        tail_norm = re.sub(r"\bchapter\b", " ", tail_norm)
        tail_norm = re.sub(r"\bverses?\b", " :", tail_norm)
        tail_norm = re.sub(r"\bvs\b", " :", tail_norm)
        tail_norm = re.sub(r"\bv\b", " :", tail_norm)
        tail_norm = re.sub(r"\bto\b", "-", tail_norm)
        tail_norm = re.sub(r"\bthrough\b", "-", tail_norm)
        tail_norm = re.sub(r"\s*-\s*", "-", tail_norm)
        tail_norm = re.sub(r"\s*:\s*", " : ", tail_norm)
        tail_norm = re.sub(r"\s+", " ", tail_norm).strip()

        m = re.match(r"^(\d+)\s*:\s*(\d+)-(\d+)\b", tail_norm)
        if m:
            ch, v1, v2 = map(int, m.groups())
            if ch > 0 and v1 > 0 and v2 >= v1:
                return (book, ch, v1, v2)

        m = re.match(r"^(\d+)\s+:\s+(\d+)-(\d+)\b", tail_norm)
        if m:
            ch, v1, v2 = map(int, m.groups())
            if ch > 0 and v1 > 0 and v2 >= v1:
                return (book, ch, v1, v2)

        m = re.match(r"^(\d+)\s+(\d+)-(\d+)\b", tail_norm)
        if m:
            ch, v1, v2 = map(int, m.groups())
            if ch > 0 and v1 > 0 and v2 >= v1:
                return (book, ch, v1, v2)

        m = re.match(r"^(\d+)\s*:\s*(\d+)\b", tail_norm)
        if m:
            ch, v1 = map(int, m.groups())
            if ch > 0 and v1 > 0:
                return (book, ch, v1)

        m = re.match(r"^(\d+)\s+:\s+(\d+)\b", tail_norm)
        if m:
            ch, v1 = map(int, m.groups())
            if ch > 0 and v1 > 0:
                return (book, ch, v1)

        m = re.match(r"^(\d+)\s+(\d+)\b", tail_norm)
        if m:
            ch, v1 = map(int, m.groups())
            if ch > 0 and v1 > 0:
                return (book, ch, v1)

        m = re.match(r"^(\d{3,5})\b", tail_norm)
        if m:
            digits = m.group(1)
            ch = int(digits[:-2])
            v1 = int(digits[-2:])
            if ch > 0 and v1 > 0:
                return (book, ch, v1)

    return None

def build_range_verse_ids(book: str, chapter: int, v_start: int, v_end: int) -> List[str]:
    MAX_RANGE = 15
    if v_end - v_start + 1 > MAX_RANGE:
        v_end = v_start + MAX_RANGE - 1

    return [
        verse_id_from_reference(book, chapter, v)
        for v in range(v_start, v_end + 1)
    ]

# ============================================================
# Implicit chapter detection
# ============================================================
def apply_implicit_chapter_rule(user_text: str) -> Optional[Tuple[str, int, int]]:
    cleaned = normalize_text(user_text)
    cleaned = re.sub(r"[.,;!?]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if re.search(r"\bverse\s+\d+\s*(?:to|-)\s*\d+\b", cleaned):
        return None

    tokens = cleaned.split()
    if len(tokens) < 4:
        return None

    book_raw = tokens[0]
    book_norm = normalize_book_name(book_raw)
    book_l = book_raw.lower().strip()

    if not tokens[1].isdigit():
        return None
    if tokens[2] != "verse":
        return None
    if not tokens[3].isdigit():
        return None

    if len(tokens) > 4 and tokens[4] in ("to", "-"):
        return None

    chapter_num = int(tokens[1])
    verse_num = int(tokens[3])

    if book_l in ONE_CHAPTER_BOOKS:
        return (book_norm, 1, chapter_num)

    return (book_norm, chapter_num, verse_num)

# ============================================================
# Phrase matching
# ============================================================
def build_phrase_lookup(phrase_entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    lookup: Dict[str, List[Dict[str, Any]]] = {}
    for e in phrase_entries:
        p = e.get("phrase", "")
        if not p:
            continue
        key = normalize_text(p)
        lookup.setdefault(key, []).append(e)
    return lookup

def phrase_match(user_text: str, phrase_lookup: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    norm = normalize_text(user_text)

    best: Optional[Dict[str, Any]] = None
    best_len = 0
    best_weight = 0

    for phrase_norm, entries in phrase_lookup.items():
        if phrase_norm and phrase_norm in norm:
            for e in entries:
                w = int(e.get("weight", 1))
                L = len(phrase_norm)
                if L > best_len or (L == best_len and w > best_weight):
                    best = e
                    best_len = L
                    best_weight = w

    if not best:
        return None

    return {
        "mode": "phrase",
        "confidence": PHRASE_CONFIDENCE,
        "trigger_phrase": best.get("phrase"),
        "tier": best.get("tier"),
        "weight": best.get("weight", 1),
        "verse_id": best.get("verse_id"),
    }

# ============================================================
# Text similarity matching
# ============================================================
def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def compute_similarity(query: str, verse: str, full_verse_mode: bool) -> float:
    q_tokens = set(query.split())
    v_tokens = set(verse.split())

    if not q_tokens or not v_tokens:
        token_score = 0
    else:
        token_score = len(q_tokens & v_tokens) / len(q_tokens | v_tokens)

    char_score = fuzz.WRatio(query, verse) / 100.0

    if full_verse_mode:
        return 0.25 * token_score + 0.75 * char_score
    else:
        return 0.60 * token_score + 0.40 * char_score

def match_text_to_reference(user_text: str,
                            verses_index: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    query = normalize(user_text)
    if not query:
        return None

    word_count = len(query.split())
    full_verse_mode = word_count >= 10

    FULL_THRESHOLD = 0.80
    PARTIAL_THRESHOLD = 0.65

    best_vid = None
    best_ref = None
    best_score = 0.0

    for vid, v in verses_index.items():
        text_kjv = v.get("text_kjv", "")
        verse_norm = normalize(text_kjv)
        score = compute_similarity(query, verse_norm, full_verse_mode)
        if score > best_score:
            best_score = score
            best_vid = vid
            best_ref = v.get("reference")

    if not best_vid:
        return None

    if full_verse_mode:
        if best_score >= FULL_THRESHOLD:
            return {
                "verse_id": best_vid,
                "reference": best_ref,
                "score": best_score,
                "type": "full",
            }
    else:
        if best_score >= PARTIAL_THRESHOLD:
            return {
                "verse_id": best_vid,
                "reference": best_ref,
                "score": best_score,
                "type": "partial",
            }

    return None

# ============================================================
# Keyword matching
# ============================================================
def keyword_match(tokens: List[str],
                  verses_index: Dict[str, Dict[str, Any]],
                  keyword_index: Dict[str, List[str]]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:

    if not tokens:
        return None, []

    q_counts = Counter(tokens)

    candidate_ids = set()
    for t in q_counts.keys():
        for vid in keyword_index.get(t, []):
            candidate_ids.add(vid)

    if not candidate_ids:
        return None, []

    scored: List[Dict[str, Any]] = []
    for vid in candidate_ids:
        v = verses_index.get(vid)
        if not v:
            continue

        v_weights: Dict[str, int] = v.get("keyword_weights", {})
        overlap = 0.0
        max_possible = float(sum(q_counts.values())) or 1.0

        for t, qc in q_counts.items():
            if t in v_weights:
                overlap += float(min(qc, v_weights.get(t, 0)))

        confidence = overlap / max_possible

        scored.append({
            "verse_id": vid,
            "reference": v.get("reference"),
            "text_kjv": v.get("text_kjv"),
            "confidence": round(confidence, 4),
        })

    scored.sort(key=lambda x: x["confidence"], reverse=True)

    best = scored[0] if scored else None
    suggestions = scored[1:TOP_K_SUGGESTIONS] if len(scored) > 1 else []

    return best, suggestions

# ============================================================
# Main matcher
# ============================================================
def match_scripture(user_text: str,
                    verses_index: Dict[str, Dict[str, Any]],
                    keyword_index: Dict[str, List[str]],
                    phrase_lookup: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:

    cleaned_input = re.sub(
        r'^\s*\[\s*final\s*\]\s*\(\s*azure\s*\)\s*[:\-]?\s*',
        '',
        user_text,
        flags=re.IGNORECASE
    ).strip()

    cleaned_input = cleaned_input.replace(",", " ")
    cleaned_input = cleaned_input.rstrip(".")
    reference_input = cleaned_input

    debug_log("RAW:", repr(user_text))
    debug_log("CLEANED:", repr(cleaned_input))

    
    ref = parse_reference(cleaned_input)
    debug_log("PARSE_REF:", ref)

    if ref:
        if len(ref) == 4:
            book, ch, v1, v2 = ref
            ids = build_range_verse_ids(book, ch, v1, v2)
            verses = []
            for vid in ids:
                v = verses_index.get(vid)
                if v:
                    verses.append({
                        "verse_id": vid,
                        "reference": v.get("reference"),
                        "text_kjv": v.get("text_kjv"),
                    })

            if verses:
                book_id = re.sub(r"[^A-Z0-9]+", "_", book.upper()).strip("_")
                ref_label = f"{book} {ch}:{v1}-{v2}"
                return {
                    "mode": "reference_range",
                    "quote_like": True,
                    "confidence": 1.0,
                    "best": {
                        "verse_id": f"{book_id}_{ch}_{v1}-{v2}",
                        "reference": ref_label,
                        "text_kjv": "\n".join(
                            f"{vv['reference'].split(':')[-1]} {vv['text_kjv']}"
                            for vv in verses
                        ),
                        "verses": verses,
                    },
                    "suggestions": [],
                }

        if len(ref) == 3:
            book, ch, vs = ref
            vid = verse_id_from_reference(book, ch, vs)
            debug_log("VID_FROM_REF:", vid, "exists:", vid in verses_index)
            v = verses_index.get(vid)
            if v:
                return {
                    "mode": "reference",
                    "quote_like": True,
                    "confidence": 1.0,
                    "best": {
                        "verse_id": vid,
                        "reference": v.get("reference"),
                        "text_kjv": v.get("text_kjv"),
                    },
                    "suggestions": [],
                }

    implicit = apply_implicit_chapter_rule(cleaned_input)
    debug_log("IMPLICIT:", implicit)

    if implicit:
        book, ch, vs = implicit
        vid = verse_id_from_reference(book, ch, vs)
        debug_log("VID_FROM_IMPLICIT:", vid, "exists:", vid in verses_index)
        v = verses_index.get(vid)
        if v:
            return {
                "mode": "reference",
                "quote_like": True,
                "confidence": 1.0,
                "best": {
                    "verse_id": vid,
                    "reference": v.get("reference"),
                    "text_kjv": v.get("text_kjv"),
                },
                "suggestions": [],
            }

    pm = phrase_match(cleaned_input, phrase_lookup)
    if pm:
        vid = pm["verse_id"]
        v = verses_index.get(vid)
        if v:
            return {
                "mode": "phrase",
                "quote_like": True,
                "confidence": pm["confidence"],
                "best": {
                    "verse_id": vid,
                    "reference": v.get("reference"),
                    "text_kjv": v.get("text_kjv"),
                    "trigger_phrase": pm.get("trigger_phrase"),
                    "tier": pm.get("tier"),
                    "weight": pm.get("weight"),
                },
                "suggestions": [],
            }

    text_result = match_text_to_reference(cleaned_input, verses_index)
    if text_result:
        vid = text_result["verse_id"]
        v = verses_index.get(vid)
        if v:
            return {
                "mode": "text",
                "quote_like": True,
                "confidence": text_result["score"],
                "best": {
                    "verse_id": vid,
                    "reference": text_result["reference"],
                    "text_kjv": v.get("text_kjv"),
                },
                "suggestions": [],
            }

    tokens = tokenize(cleaned_input)
    quote_like = is_quote_like(cleaned_input, tokens)

    best, suggestions = keyword_match(tokens, verses_index, keyword_index)

    if not quote_like:
        return {
            "mode": "keyword",
            "quote_like": False,
            "confidence": 0.0,
            "best": None,
            "suggestions": [],
            "note": "blocked by quote-likeness gate",
        }

    if best and best["confidence"] >= KEYWORD_MIN_CONFIDENCE_TO_DISPLAY:
        return {
            "mode": "keyword",
            "quote_like": True,
            "confidence": best["confidence"],
            "best": best,
            "suggestions": []
        }

    if best and best["confidence"] >= KEYWORD_MIN_CONFIDENCE_TO_SUGGEST:
        return {
            "mode": "keyword",
            "quote_like": True,
            "confidence": best["confidence"],
            "best": None,
            "suggestions": [best] + suggestions
        }

    return {
        "mode": "keyword",
        "quote_like": True,
        "confidence": 0.0,
        "best": None,
        "suggestions": []
    }

# ============================================================
# Quick tests + interactive REPL
# ============================================================
AUTO_TESTS = [
    "John 3:16-18",
    "John chapter 3 verse 16 to 18",
    "Proverbs chapter 5 verse 21",
    "John 317",
    "Isaiah chapter 54, verse 17.",
    "Isaiah chapter fifty four verse seventeen",
    "Do you remember Jeremiah chapter one verse five?",
]

def main() -> None:
    verses_index = load_verses_index()

    print("Loaded verse count:", len(verses_index))
    print("GENESIS_1_1 exists:", "GENESIS_1_1" in verses_index)
    print("NUMBERS_5_7 exists:", "NUMBERS_5_7" in verses_index)
    print("EXODUS_3_20 exists:", "EXODUS_3_20" in verses_index)
    print("MATTHEW_11_20 exists:", "MATTHEW_11_20" in verses_index)
    print("JEREMIAH_3_5 exists:", "JEREMIAH_3_5" in verses_index)
    print("EXODUS_3_20 exists:", "EXODUS_3_20" in verses_index)

    if "NUMBERS_5_7" in verses_index:
        print("NUMBERS_5_7 entry reference:", verses_index["NUMBERS_5_7"].get("reference"))

    keys = list(verses_index.keys())
    print("Sample keys:", keys[:10])
    first = verses_index[keys[0]]
    print("Sample fields:", first.keys())

    keyword_index = load_json(KEYWORD_INDEX_FILE)

    try:
        phrase_entries = load_json(PHRASE_DICT_FILE)
        if not isinstance(phrase_entries, list):
            phrase_entries = []
    except FileNotFoundError:
        phrase_entries = []

    phrase_lookup = build_phrase_lookup(phrase_entries)

    print("Type scripture reference or quote (type 'exit' to quit)\n")
    print("Running auto tests...\n")

    for t in AUTO_TESTS:
        print("=== TEST ===")
        print(t)
        r = match_scripture(t, verses_index, keyword_index, phrase_lookup)
        print(f"MODE: {r['mode'].upper()}  CONF: {r.get('confidence')}")
        if r.get("best"):
            b = r["best"]
            print(b.get("reference"))
            print(b.get("text_kjv"))
        else:
            print("BEST: None")
        print()

    print("Auto tests complete.\n")

    while True:
        user_input = input(">>> ").strip()
        if user_input.lower() == "exit":
            break

        r = match_scripture(user_input, verses_index, keyword_index, phrase_lookup)

        if not r.get("best") and not r.get("suggestions"):
            print("No match found.\n")
            continue

        b = r.get("best")
        if b:
            print(f"\nMODE: {r['mode'].upper()}  CONF: {r.get('confidence')}")
            print(b.get("reference"))
            print(b.get("text_kjv"))
            print()
        else:
            print("\nNo BEST; suggestions exist.\n")

if __name__ == "__main__":
    main()