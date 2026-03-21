import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

INPUT_KJV_FILE = "kjv.txt"
OUT_VERSES_INDEX = "verses_index.json"
OUT_KEYWORD_INDEX = "keyword_index.json"
OUT_STATS = "stats.json"

# -----------------------------
# Tokenization normalization
# -----------------------------
STOPWORDS = {
    # basic (keep small to avoid harming recall)
    "the", "and", "of", "to", "in", "that", "a", "an", "for", "is", "it", "as", "be",
    "with", "by", "this", "from", "or", "at", "was", "were", "are", "but", "not",
    "into", "unto", "thou", "thee", "thy", "ye", "you", "your", "yours",
}

TOKEN_RE = re.compile(r"[a-z0-9']+")

def normalize_text(s: str) -> str:
    """
    Normalize for KJV matching:
    - lowercase
    - convert hyphens to spaces (battle-axe -> battle axe)
    - normalize apostrophes/quotes
    - remove non-token punctuation (we tokenize later)
    - collapse whitespace
    """
    s = s.lower()
    s = s.replace("’", "'").replace("`", "'").replace("“", '"').replace("”", '"')
    s = s.replace("-", " ")  # IMPORTANT: hyphen -> space
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(s: str) -> List[str]:
    s = normalize_text(s)
    tokens = TOKEN_RE.findall(s)

    # optional: normalize very common KJV forms (keep conservative)
    # example: "battle axe" should match regardless of axe/ax differences
    # We'll keep both if encountered:
    expanded = []
    for t in tokens:
        expanded.append(t)
        if t == "axe":
            expanded.append("ax")
        elif t == "ax":
            expanded.append("axe")

    # remove stopwords (but keep "not" if you want; currently included)
    out = [t for t in expanded if t not in STOPWORDS and len(t) > 1]
    return out

def parse_kjv_line(line: str) -> Tuple[str, int, int, str]:
    """
    Expected format:
    Book Chapter:Verse Text
    Example:
    John 3:16 For God so loved the world...
    """
    line = line.strip()
    if not line:
        raise ValueError("Empty line")

    m = re.match(r"^(.+?)\s+(\d+):(\d+)\s+(.*)$", line)
    if not m:
        raise ValueError(f"Line does not match expected format: {line[:80]}")

    book = m.group(1).strip()
    chapter = int(m.group(2))
    verse = int(m.group(3))
    text = m.group(4).strip()
    return book, chapter, verse, text

def make_verse_id(book: str, chapter: int, verse: int) -> str:
    book_id = re.sub(r"[^A-Z0-9]+", "_", book.upper()).strip("_")
    return f"{book_id}_{chapter}_{verse}"

def main() -> None:
    verses_index: Dict[str, dict] = {}
    keyword_index: Dict[str, List[str]] = defaultdict(list)

    parsed = 0
    all_keywords = set()

    with open(INPUT_KJV_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue

            try:
                book, chapter, verse, text_kjv = parse_kjv_line(raw)
            except ValueError:
                # skip malformed lines safely
                continue

            verse_id = make_verse_id(book, chapter, verse)
            ref = f"{book} {chapter}:{verse}"

            tokens = tokenize(text_kjv)
            token_counts = Counter(tokens)

            verses_index[verse_id] = {
                "verse_id": verse_id,
                "reference": ref,
                "book": book,
                "chapter": chapter,
                "verse": verse,
                "text_kjv": text_kjv,
                "tokens": tokens,
                "keyword_weights": dict(token_counts),
                "phrases": [],
                "tiers": [],
            }

            # keyword -> list of verse_ids
            for kw in token_counts.keys():
                keyword_index[kw].append(verse_id)
                all_keywords.add(kw)

            parsed += 1

    # write outputs
    with open(OUT_VERSES_INDEX, "w", encoding="utf-8") as f:
        json.dump(verses_index, f, ensure_ascii=False, indent=2)

    with open(OUT_KEYWORD_INDEX, "w", encoding="utf-8") as f:
        json.dump(keyword_index, f, ensure_ascii=False, indent=2)

    stats = {
        "parsed_verses": parsed,
        "unique_keywords": len(all_keywords),
        "input_file": INPUT_KJV_FILE,
        "outputs": [OUT_VERSES_INDEX, OUT_KEYWORD_INDEX, OUT_STATS],
    }
    with open(OUT_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print("DONE.")
    print(f"Parsed verses: {parsed}")
    print(f"Unique keywords: {len(all_keywords)}")
    print(f"Wrote: {OUT_VERSES_INDEX}, {OUT_KEYWORD_INDEX}, {OUT_STATS}")

if __name__ == "__main__":
    main()
