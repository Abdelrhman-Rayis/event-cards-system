"""Guest persistence and helpers."""

import json
import uuid

from .config import EVENT, GUESTS_FILE


def load_guests():
    if not GUESTS_FILE.exists():
        return []
    try:
        return json.loads(GUESTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_guests(guests):
    GUESTS_FILE.write_text(
        json.dumps(guests, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def gen_code():
    return f"EVT-{EVENT['date_code']}-{uuid.uuid4().hex[:7].upper()}"


def get_guest(code):
    for g in load_guests():
        if g["id"] == code:
            return g
    return None


def companions_label(n):
    if n <= 0:
        return "Single entry"
    if n == 1:
        return "+1 Companion"
    return f"+{n} Companions"
