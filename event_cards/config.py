"""Paths, event metadata, and card visual constants.

The event is now configured by ``event.json`` at the project root. If the
file is missing we fall back to a generic placeholder event so a fresh
clone still boots — the setup wizard (Phase 5) writes a real config.
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("EVENT_CARDS_ROOT", Path(__file__).resolve().parent.parent)
)

PHOTOS_DIR = PROJECT_ROOT / "photos"
OUTPUT_DIR = PROJECT_ROOT / "output"
STATIC_DIR = PROJECT_ROOT / "static"
GUESTS_FILE = PROJECT_ROOT / "guests.json"
EVENT_CONFIG_FILE = PROJECT_ROOT / "event.json"

for d in (PHOTOS_DIR, OUTPUT_DIR, STATIC_DIR):
    d.mkdir(exist_ok=True)


# ----------------- Config defaults (used when event.json is missing) -----------------

DEFAULT_CONFIG = {
    "schema_version": 1,
    "title_primary": "My Event",
    "title_secondary": "",
    "title_primary_ar": "",
    "title_secondary_ar": "",
    "date": "TBD",
    "time": "",
    "location": "TBD",
    "date_code": "00000000",
    "languages": ["en"],
    "fields": [
        {
            "id": "role",
            "label": "Role",
            "type": "text",
            "show_on_card": True,
            "default": "Guest",
        },
        {
            "id": "ticket_type",
            "label": "Ticket Type",
            "type": "select",
            "show_on_card": True,
            "options": ["VIP", "Standard"],
            "default": "Standard",
        },
        {
            "id": "companions",
            "label": "Companions",
            "type": "number",
            "show_on_card": True,
            "min": 0,
            "max": 10,
            "default": 0,
        },
    ],
    "template": {"id": "classic_navy_gold", "overrides": {}},
}


def load_config():
    """Read event.json, falling back to defaults for missing keys."""
    if EVENT_CONFIG_FILE.exists():
        try:
            data = json.loads(EVENT_CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    merged = {**DEFAULT_CONFIG, **data}
    # Make sure nested template dict has both keys
    merged["template"] = {**DEFAULT_CONFIG["template"], **merged.get("template", {})}
    return merged


def save_config(cfg):
    EVENT_CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _event_shape(cfg):
    """Legacy EVENT dict shape so existing renderer code keeps working until
    Phase 3 rewrites it to consume CONFIG directly.
    """
    return {
        "title_en_l1": cfg.get("title_primary", ""),
        "title_en_l2": cfg.get("title_secondary", ""),
        "title_ar_l1": cfg.get("title_primary_ar", ""),
        "title_ar_l2": cfg.get("title_secondary_ar", ""),
        "date": cfg.get("date", ""),
        "time": cfg.get("time", ""),
        "location": cfg.get("location", ""),
        "date_code": cfg.get("date_code", ""),
    }


# Mutated in place by reload_config so ``from .config import EVENT`` keeps
# referencing the live data instead of a stale snapshot.
CONFIG: dict = {}
EVENT: dict = {}


def _refresh_globals():
    new_cfg = load_config()
    CONFIG.clear()
    CONFIG.update(new_cfg)
    EVENT.clear()
    EVENT.update(_event_shape(new_cfg))


_refresh_globals()


def reload_config():
    """Reload config from disk; used by the setup wizard after writes."""
    _refresh_globals()
    return CONFIG


# ----------------- Card visual constants -----------------
# Colors now come from rendering.themes (driven by template.id in event.json).

CARD_W, CARD_H = 1950, 1340
CONFERENCE_CARD_W = int(round(3.375 * 300))
CONFERENCE_CARD_H = int(round(2.125 * 300))


def normalize_card_format(value):
    v = (value or "event").strip().lower()
    if v in ("conference", "cr80", "badge"):
        return "conference"
    return "event"


def card_layout_pixels(card_format):
    if normalize_card_format(card_format) == "conference":
        return CONFERENCE_CARD_W, CONFERENCE_CARD_H
    return CARD_W, CARD_H
