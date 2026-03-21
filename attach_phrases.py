import json
import re
from collections import defaultdict

VERSES_IN = "verses_index.json"
PHRASES_IN = "phrase_dictionary.json"
VERSES_OUT = "verses_index_enriched.json"
COLLISION_OUT = "collision_report.json"

def normalize_phrase(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)      # remove punctuation
    s = re.sub(r"\s+", " ", s).strip()  # normalize whitespace
    return s

def main():
    # Load verse index
    with open(VERSES_IN, "r", encoding="utf-8") as f:
        verses = json.load(f)

    # Load phrase dictionary
    with open(PHRASES_IN, "r", encoding="utf-8") as f:
        phrase_entries = json.load(f)

    # Collision tracking
    phrase_to_verses = defaultdict(set)
    invalid_entries = []
    attached_count = 0

    # Attach phrases + tiers to verses
    for entry in phrase_entries:
        phrase_raw = entry.get("phrase", "")
        verse_id = entry.get("verse_id", "")
        tier = entry.get("tier", None)
        weight = entry.get("weight", 5)
        exclusive = bool(entry.get("exclusive", False))

        phrase = normalize_phrase(phrase_raw)

        # Validate minimal requirements
        if not phrase or not verse_id or tier is None:
            invalid_entries.append({"reason": "missing required fields", "entry": entry})
            continue

        if verse_id not in verses:
            invalid_entries.append({"reason": "verse_id not found in verses_index", "entry": entry})
            continue

        # Track collisions
        phrase_to_verses[phrase].add(verse_id)

        # Ensure verse record has phrases/tiers lists
        if "phrases" not in verses[verse_id] or verses[verse_id]["phrases"] is None:
            verses[verse_id]["phrases"] = []
        if "tiers" not in verses[verse_id] or verses[verse_id]["tiers"] is None:
            verses[verse_id]["tiers"] = []

        # Attach phrase anchor object (store more than just the string)
        verses[verse_id]["phrases"].append({
            "phrase": phrase,
            "tier": int(tier),
            "weight": int(weight),
            "exclusive": exclusive
        })

        # Attach tier (unique)
        if int(tier) not in verses[verse_id]["tiers"]:
            verses[verse_id]["tiers"].append(int(tier))

        attached_count += 1

    # Build collision report
    collisions = []
    for phrase, verse_ids in phrase_to_verses.items():
        if len(verse_ids) > 1:
            collisions.append({
                "phrase": phrase,
                "verse_ids": sorted(list(verse_ids)),
                "collision_type": "one_phrase_multiple_verses"
            })

    report = {
        "attached_phrase_entries": attached_count,
        "invalid_entries_count": len(invalid_entries),
        "collision_count": len(collisions),
        "collisions": collisions[:200],  # cap for readability
        "invalid_entries_sample": invalid_entries[:50]
    }

    # Write enriched index + report
    with open(VERSES_OUT, "w", encoding="utf-8") as f:
        json.dump(verses, f, ensure_ascii=False, indent=2)

    with open(COLLISION_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("DONE")
    print(f"Attached entries: {attached_count}")
    print(f"Wrote: {VERSES_OUT}")
    print(f"Wrote: {COLLISION_OUT}")
    if report["invalid_entries_count"] > 0:
        print(f"WARNING: {report['invalid_entries_count']} invalid entries (see collision_report.json)")
    if report["collision_count"] > 0:
        print(f"WARNING: {report['collision_count']} phrase collisions (see collision_report.json)")

if __name__ == "__main__":
    main()
