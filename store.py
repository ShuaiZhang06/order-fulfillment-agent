"""
store.py - read and write the JSON files under state/.

data/seed/ holds the original sample data. reset() copies it into state/,
and the tools only ever read and write state/, so every demo can start fresh.
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
SEED_DIR = ROOT / "data" / "seed"
STATE_DIR = ROOT / "state"   # the tests point this at a temporary folder


def reset():
    """Copy the seed data into state/ and start with empty records."""
    STATE_DIR.mkdir(exist_ok=True)
    shutil.copy(SEED_DIR / "product.json", STATE_DIR / "product.json")
    shutil.copy(SEED_DIR / "orders.json", STATE_DIR / "orders.json")
    write_json("shipments.json", [])
    for name in ["approvals.jsonl", "outbox.jsonl", "trace.jsonl"]:
        (STATE_DIR / name).write_text("")


def read_json(name):
    with open(STATE_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def write_json(name, data):
    with open(STATE_DIR / name, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def append_jsonl(name, record):
    """Add one record as one line. Used for logs that only ever grow."""
    with open(STATE_DIR / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_jsonl(name):
    with open(STATE_DIR / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
