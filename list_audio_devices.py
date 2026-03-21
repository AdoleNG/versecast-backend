"""
Lists only microphone devices and shows which one is the Windows default.

Run:
    python list_mics_with_default.py
"""

import sounddevice as sd

# default input device index
default_input, _ = sd.default.device

print("\n=== MICROPHONES ===\n")

for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        marker = "⭐ DEFAULT" if i == default_input else ""
        print(f"[{i}] {d['name']} {marker}")
