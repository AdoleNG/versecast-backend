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
    "verily","whosoever","begotten","thee","thou","thy","ye",
    "unto","hath","saith","wherefore","lest","thereof","therein"
}

# ============================================================
# One‑chapter books
# ============================================================

ONE_CHAPTER_BOOKS = {
    "obadiah","philemon","2 john","3 john","jude"
}

# ============================================================
# BOOK ALIASES + PATTERN
# ============================================================

BOOK_ALIASES = {
    "genesis":"Genesis","gen":"Genesis",
    "exodus":"Exodus","exo":"Exodus","exod":"Exodus",
    "leviticus":"Leviticus","lev":"Leviticus",
    "numbers":"Numbers","num":"Numbers",
    "deuteronomy":"Deuteronomy","deut":"Deuteronomy",

    "joshua":"Joshua","josh":"Joshua",
    "judges":"Judges","judg":"Judges",
    "ruth":"Ruth",

    "1 samuel":"1 Samuel","first samuel":"1 Samuel","1st samuel":"1 Samuel","i samuel":"1 Samuel",
    "2 samuel":"2 Samuel","second samuel":"2 Samuel","2nd samuel":"2 Samuel","ii samuel":"2 Samuel",

    "1 kings":"1 Kings","first kings":"1 Kings","1st kings":"1 Kings","i kings":"1 Kings",
    "2 kings":"2 Kings","second kings":"2 Kings","2nd kings":"2 Kings","ii kings":"2 Kings",

    "1 chronicles":"1 Chronicles","first chronicles":"1 Chronicles","1st chronicles":"1 Chronicles","i chronicles":"1 Chronicles",
    "2 chronicles":"2 Chronicles","second chronicles":"2 Chronicles","2nd chronicles":"2 Chronicles","ii chronicles":"2 Chronicles",

    "ezra":"Ezra","nehemiah":"Nehemiah","neh":"Nehemiah","esther":"Esther",
    "job":"Job","psalm":"Psalms","psalms":"Psalms","ps":"Psalms",
    "proverbs":"Proverbs","prov":"Proverbs","ecclesiastes":"Ecclesiastes","eccl":"Ecclesiastes",
    "song of solomon":"Song of Solomon","song of songs":"Song of Solomon","songs of solomon":"Song of Solomon","solomon":"Song of Solomon",

    "isaiah":"Isaiah","isa":"Isaiah","jeremiah":"Jeremiah","jer":"Jeremiah",
    "lamentations":"Lamentations","lam":"Lamentations","ezekiel":"Ezekiel","ezek":"Ezekiel",
    "daniel":"Daniel","dan":"Daniel",

    "hosea":"Hosea","joel":"Joel","amos":"Amos","obadiah":"Obadiah","obad":"Obadiah",
    "jonah":"Jonah","micah":"Micah","nahum":"Nahum","habakkuk":"Habakkuk","hab":"Habakkuk",
    "zephaniah":"Zephaniah","zeph":"Zephaniah","haggai":"Haggai","zechariah":"Zechariah","zech":"Zechariah",
    "malachi":"Malachi","mal":"Malachi",

    "matthew":"Matthew","matt":"Matthew","mark":"Mark","luke":"Luke","john":"John","acts":"Acts",

    "romans":"Romans","rom":"Romans","romance":"Romans",
    "1 corinthians":"1 Corinthians","1 cor":"1 Corinthians","first corinthians":"1 Corinthians","1st corinthians":"1 Corinthians","i corinthians":"1 Corinthians",
    "2 corinthians":"2 Corinthians","2 cor":"2 Corinthians","second corinthians":"2 Corinthians","2nd corinthians":"2 Corinthians","ii corinthians":"2 Corinthians",

    "galatians":"Galatians","gal":"Galatians","ephesians":"Ephesians","eph":"Ephesians",
    "philippians":"Philippians","phil":"Philippians","colossians":"Colossians","col":"Colossians",

    "1 thessalonians":"1 Thessalonians","first thessalonians":"1 Thessalonians","1st thessalonians":"1 Thessalonians","i thessalonians":"1 Thessalonians",
    "2 thessalonians":"2 Thessalonians","second thessalonians":"2 Thessalonians","2nd thessalonians":"2 Thessalonians","ii thessalonians":"2 Thessalonians",

    "1 timothy":"1 Timothy","first timothy":"1 Timothy","1st timothy":"1 Timothy","i timothy":"1 Timothy",
    "2 timothy":"2 Timothy","second timothy":"2 Timothy","2nd timothy":"2 Timothy","ii timothy":"2 Timothy",

    "titus":"Titus","philemon":"Philemon","hebrews":"Hebrews","heb":"Hebrews",
    "james":"James","1 peter":"1 Peter","first peter":"1 Peter","1st peter":"1 Peter","i peter":"1 Peter",
    "2 peter":"2 Peter","second peter":"2 Peter","2nd peter":"2 Peter","ii peter":"2 Peter",

    "1 john":"1 John","first john":"1 John","1st john":"1 John","i john":"1 John",
    "2 john":"2 John","second john":"2 John","2nd john":"2 John","ii john":"2 John",
    "3 john":"3 John","third john":"3 John","3rd john":"3 John","iii john":"3 John",

    "jude":"Jude","revelation":"Revelation","revelations":"Revelation","rev":"Revelation"
}

BOOK_PATTERN = "|".join(sorted(BOOK_ALIASES.keys(), key=len, reverse=True))

# ============================================================
# Normalization helpers
# ============================================================

def normalize_text(s: str) -> str:
    s = s.lower()
    s = s.replace("’","'").replace("`","'")
    s = s.replace("“",'"').replace("”",'"')
    s = s.replace("-", " ")
    s = re.sub(r"\s+"," ",s).strip()
    return s

def normalize_book_name(book_raw: str):
    if not book_raw:
        return None
    b = book_raw.lower().strip()
    b = re.sub(r"[.,:;]","",b)
    b = re.sub(r"\bthe book of\s+","",b)
    b = re.sub(r"\bfirst\b","1",b)
    b = re.sub(r"\bsecond\b","2",b)
    b = re.sub(r"\bthird\b","3",b)
    b = re.sub(r"\b1st\b","1",b)
    b = re.sub(r"\b2nd\b","2",b)
    b = re.sub(r"\b3rd\b","3",b)
    b = re.sub(r"\biii\b","3",b)
    b = re.sub(r"\bii\b","2",b)
    b = re.sub(r"\bi\b","1",b)
    b = re.sub(r"\s+"," ",b).strip()
    return BOOK_ALIASES.get(b)

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

# ============================================================
# Universal reference parser
# ============================================================

def parse_reference(text: str):
    raw = text or ""
    t = normalize_text(raw)
    t = replace_spoken_numbers(t)

    # 1) John 3:16-18
    m = re.search(
        rf"\b({BOOK_PATTERN})\s+(\d+):(\d+)\s*[-–]\s*(\d+)\b",
        raw, re.IGNORECASE
    )
    if m:
        return {
            "type":"range",
            "book": normalize_book_name(m.group(1)),
            "chapter": int(m.group(2)),
            "start": int(m.group(3)),
            "end": int(m.group(4)),
        }

    # 2) John 3:16
    m = re.search(
        rf"\b({BOOK_PATTERN})\s+(\d+):(\d+)\b",
        raw, re.IGNORECASE
    )
    if m:
        return {
            "type":"single",
            "book": normalize_book_name(m.group(1)),
            "chapter": int(m.group(2)),
            "verse": int(m.group(3)),
        }

    # 3) John 317 → John 3:17
    m = re.search(
        rf"\b({BOOK_PATTERN})\s+(\d{{3,5}})\b",
        t, re.IGNORECASE
    )
    if m:
        book = normalize_book_name(m.group(1))
        digits = m.group(2)
        if len(digits) == 3:
            ch = int(digits[0])
            vs = int(digits[1:])
        elif len(digits) == 4:
            ch = int(digits[:2])
            vs = int(digits[2:])
        else:
            ch = int(digits[:3])
            vs = int(digits[3:])
        return {
            "type":"single",
            "book": book,
            "chapter": ch,
            "verse": vs,
        }

    # 4) Universal fallback: book + numbers
    m = re.search(rf"\b({BOOK_PATTERN})\b", t, re.IGNORECASE)
    if not m:
        return None

    book = normalize_book_name(m.group(1))
    tail = t[m.end():]

    nums = re.findall(r"\d+", tail)
    if len(nums) < 2:
        return None

    chapter = int(nums[0])
    verse_start = int(nums[1])
    verse_end = int(nums[2]) if len(nums) >= 3 else None

    if verse_end and verse_end > verse_start:
        return {
            "type":"range",
            "book": book,
            "chapter": chapter,
            "start": verse_start,
            "end": verse_end,
        }

    return {
        "type":"single",
        "book": book,
        "chapter": chapter,
        "verse": verse_start,
    }

# ============================================================
# Phrase matching
# ============================================================

def build_phrase_lookup(entries: List[Dict[str,Any]]) -> Dict[str,List[Dict[str,Any]]]:
    lookup = {}
    for e in entries:
        p = e.get("phrase","")
        if not p:
            continue
        key = normalize_text(p)
        lookup.setdefault(key,[]).append(e)
    return lookup

def phrase_match(user_text: str, lookup: Dict[str,List[Dict[str,Any]]]):
    norm = normalize_text(user_text)
    best = None
    best_len = 0
    best_weight = 0
    for phrase_norm, entries in lookup.items():
        if phrase_norm and phrase_norm in norm:
            for e in entries:
                w = int(e.get("weight",1))
                L = len(phrase_norm)
                if L > best_len or (L == best_len and w > best_weight):
                    best = e
                    best_len = L
                    best_weight = w
    if not best:
        return None
    return {
        "mode":"phrase",
        "confidence": PHRASE_CONFIDENCE,
        "trigger_phrase": best.get("phrase"),
        "tier": best.get("tier"),
        "weight": best.get("weight",1),
        "verse_id": best.get("verse_id"),
    }

# ============================================================
# Text similarity matching
# ============================================================

def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]"," ",s)
    s = re.sub(r"\s+"," ",s).strip()
    return s

def compute_similarity(query: str, verse: str, full: bool) -> float:
    q_tokens = set(query.split())
    v_tokens = set(verse.split())
    token_score = len(q_tokens & v_tokens) / len(q_tokens | v_tokens) if q_tokens and v_tokens else 0
    char_score = fuzz.WRatio(query, verse) / 100.0
    return 0.25*token_score + 0.75*char_score if full else 0.60*token_score + 0.40*char_score

def match_text_to_reference(user_text: str, verses: Dict[str,Dict[str,Any]]):
    query = normalize(user_text)
    if not query:
        return None
    full = len(query.split()) >= 10
    FULL_THRESHOLD = 0.80
    PARTIAL_THRESHOLD = 0.65
    best_vid = None
    best_ref = None
    best_score = 0.0
    for vid, v in verses.items():
        verse_norm = normalize(v.get("text_kjv",""))
        score = compute_similarity(query, verse_norm, full)
        if score > best_score:
            best_score = score
            best_vid = vid
            best_ref = v.get("reference")
    if not best_vid:
        return None
    if full and best_score >= FULL_THRESHOLD:
        return {"verse_id":best_vid,"reference":best_ref,"score":best_score,"type":"full"}
    if not full and best_score >= PARTIAL_THRESHOLD:
        return {"verse_id":best_vid,"reference":best_ref,"score":best_score,"type":"partial"}
    return None
# ============================================================
# Keyword matching
# ============================================================

def keyword_match(tokens: List[str],
                  verses: Dict[str, Dict[str, Any]],
                  index: Dict[str, List[str]]):

    if not tokens:
        return None, []

    q_counts = Counter(tokens)

    candidate_ids = set()
    for t in q_counts:
        for vid in index.get(t, []):
            candidate_ids.add(vid)

    if not candidate_ids:
        return None, []

    scored: List[Dict[str, Any]] = []
    for vid in candidate_ids:
        v = verses.get(vid)
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
# Tokenization
# ============================================================

STOPWORDS = {
    "the","and","of","to","in","that","a","an","for","is","it",
    "as","be","with","by","this","from","or","at","was","were",
    "are","but","not","into","unto","thou","thee","thy","ye",
    "you","your","yours",
}

TOKEN_RE = re.compile(r"[a-z0-9']+")

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
# Implicit chapter rule
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
    book_l = (book_norm or "").lower().strip()

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
# Main matcher
# ============================================================

def match_scripture(user_text: str,
                    verses_index: Dict[str, Dict[str, Any]],
                    keyword_index: Dict[str, List[str]],
                    phrase_lookup: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:

    # Remove Azure STT prefix like: [final] (azure) -
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

    # 1) Try explicit reference parsing
    ref = parse_reference(cleaned_input)
    debug_log("PARSED_REF:", ref)

    if ref:

        # ------------------------------------------------------
        # SINGLE VERSE
        # ------------------------------------------------------
        if ref["type"] == "single":
            book = ref["book"]
            ch = ref["chapter"]
            v = ref["verse"]

            vid = f"{re.sub(r'[^A-Z0-9]+', '_', book.upper()).strip('_')}_{ch}_{v}"
            verse = verses_index.get(vid)

            if verse:
                return {
                    "mode": "reference",
                    "best": {
                        "reference": verse.get("reference"),
                        "text_kjv": verse.get("text_kjv"),
                    },
                    "raw_input": user_text,
                    "normalized_input": cleaned_input,
                }

        # ------------------------------------------------------
        # RANGE OF VERSES
        # ------------------------------------------------------
        elif ref["type"] == "range":
            book = ref["book"]
            ch = ref["chapter"]
            v_start = ref["start"]
            v_end = ref["end"]

            vids = []
            for v in range(v_start, v_end + 1):
                vid = f"{re.sub(r'[^A-Z0-9]+', '_', book.upper()).strip('_')}_{ch}_{v}"
                if vid in verses_index:
                    vids.append(vid)

            if vids:

                if v_start == v_end:
                    ref_str = f"{book} {ch}:{v_start}"
                else:
                    ref_str = f"{book} {ch}:{v_start}-{v_end}"

                combined_text = ""
                for vid in vids:
                    verse = verses_index.get(vid)
                    if verse:
                        ref_full = verse.get("reference")
                        verse_num = ref_full.split(":")[1] if ref_full and ":" in ref_full else ""
                        combined_text += f"{verse_num}. {verse.get('text_kjv')}\n\n"

                return {
                    "mode": "reference_range",
                    "best": {
                        "reference": ref_str,
                        "text_kjv": combined_text.strip(),
                    },
                    "raw_input": user_text,
                    "normalized_input": cleaned_input,
                }

    # ------------------------------------------------------
    # 2) Implicit chapter rule
    # ------------------------------------------------------
    implicit = apply_implicit_chapter_rule(reference_input)
    debug_log("IMPLICIT:", implicit)

    if implicit:
        book, ch, v = implicit
        if book:
            vid = f"{re.sub(r'[^A-Z0-9]+', '_', book.upper()).strip('_')}_{ch}_{v}"
            verse = verses_index.get(vid)

            if verse:
                return {
                    "mode": "reference",
                    "best": {
                        "reference": verse.get("reference"),
                        "text_kjv": verse.get("text_kjv"),
                    },
                    "raw_input": user_text,
                    "normalized_input": cleaned_input,
                }

    # ------------------------------------------------------
    # 3) Phrase match
    # ------------------------------------------------------
    phrase_result = phrase_match(cleaned_input, phrase_lookup)
    debug_log("PHRASE_RESULT:", phrase_result)

    if phrase_result:
        vid = phrase_result["verse_id"]
        verse = verses_index.get(vid)

        if verse:
            return {
                "mode": "phrase",
                "confidence": phrase_result["confidence"],
                "best": {
                    "reference": verse.get("reference"),
                    "text_kjv": verse.get("text_kjv"),
                },
                "raw_input": user_text,
                "normalized_input": cleaned_input,
            }

    # ------------------------------------------------------
    # 4) Text similarity
    # ------------------------------------------------------
    sim = match_text_to_reference(cleaned_input, verses_index)
    debug_log("SIMILARITY_RESULT:", sim)

    if sim:
        vid = sim["verse_id"]
        verse = verses_index.get(vid)

        if verse:
            return {
                "mode": "similarity",
                "confidence": sim["score"],
                "best": {
                    "reference": verse.get("reference"),
                    "text_kjv": verse.get("text_kjv"),
                },
                "raw_input": user_text,
                "normalized_input": cleaned_input,
            }

    # ------------------------------------------------------
    # 5) Keyword mode
    # ------------------------------------------------------
    tokens = tokenize(cleaned_input)
    quote_like = is_quote_like(cleaned_input, tokens)
    debug_log("TOKENS:", tokens, "QUOTE_LIKE:", quote_like)

    if not quote_like:
        return {
            "mode": "none",
            "quote_like": False,
            "best": None,
            "suggestions": [],
            "raw_input": user_text,
            "normalized_input": cleaned_input,
        }

    best_kw, suggestions_kw = keyword_match(tokens, verses_index, keyword_index)
    debug_log("KEYWORD_BEST:", best_kw)
    debug_log("KEYWORD_SUGGESTIONS:", suggestions_kw)

    if not best_kw:
        return {
            "mode": "none",
            "quote_like": True,
            "best": None,
            "suggestions": [],
            "raw_input": user_text,
            "normalized_input": cleaned_input,
        }

    if best_kw["confidence"] < KEYWORD_MIN_CONFIDENCE_TO_SUGGEST:
        return {
            "mode": "none",
            "quote_like": True,
            "best": None,
            "suggestions": [],
            "raw_input": user_text,
            "normalized_input": cleaned_input,
        }

    mode = "keyword"
    if best_kw["confidence"] >= KEYWORD_MIN_CONFIDENCE_TO_DISPLAY:
        mode = "keyword_confident"

    return {
        "mode": mode,
        "quote_like": True,
        "confidence": best_kw["confidence"],
        "best": best_kw,
        "suggestions": suggestions_kw,
        "raw_input": user_text,
        "normalized_input": cleaned_input,
    }