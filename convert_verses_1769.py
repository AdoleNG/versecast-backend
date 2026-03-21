import json
import re

INPUT_FILE = "verses-1769.json"
OUTPUT_FILE = "kjv.txt"

def clean_text(t: str) -> str:
    # Remove paragraph markers and italic brackets
    t = t.strip()
    t = re.sub(r"^\s*#\s*", "", t)
    t = re.sub(r"\[(.*?)\]", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    verses = json.load(f)  # dict: "John 3:16" -> "For God so loved..."

count = 0
with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
    for ref, text in verses.items():
        out.write(f"{ref} {clean_text(text)}\n")
        count += 1

print(f"kjv.txt created with {count} verses")
