import json
import sys
import os

"""
Usage:
    python write_session_info.py <token> <session_id>
"""

if len(sys.argv) != 3:
    print("Usage: python write_session_info.py <token> <session_id>")
    sys.exit(1)

token = sys.argv[1]
session_id = sys.argv[2]

data = {
    "token": token,
    "session_id": session_id
}

with open("session_info.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print("session_info.json written successfully.")
