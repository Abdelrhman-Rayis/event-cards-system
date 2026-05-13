"""Paths, event metadata, and card visual constants.

Phase 1 keeps the hardcoded EVENT dict in place. Phase 2 will replace it
with a JSON-driven config loaded at startup.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("EVENT_CARDS_ROOT", Path(__file__).resolve().parent.parent)
)

PHOTOS_DIR = PROJECT_ROOT / "photos"
OUTPUT_DIR = PROJECT_ROOT / "output"
STATIC_DIR = PROJECT_ROOT / "static"
GUESTS_FILE = PROJECT_ROOT / "guests.json"

for d in (PHOTOS_DIR, OUTPUT_DIR, STATIC_DIR):
    d.mkdir(exist_ok=True)

EVENT = {
    "title_en_l1": "Sudanese Forum",
    "title_en_l2": "for the Homeland",
    "title_ar_l1": "ملتقى السودانيين",
    "title_ar_l2": "من أجل الوطن",
    "date": "Saturday, 16 May 2026",
    "time": "18:00 – 23:00",
    "location": "Manchester, UK",
    "date_code": "20260516",
}

# Card visual constants
CARD_W, CARD_H = 1950, 1340
# ISO CR80 / common conference badge insert, landscape, at 300 dpi (3.375" × 2.125")
CONFERENCE_CARD_W = int(round(3.375 * 300))
CONFERENCE_CARD_H = int(round(2.125 * 300))

BG_CREAM = (250, 244, 230)
BG_HEADER_BORDER = (224, 216, 184)
COLOR_DARK = (28, 76, 92)
COLOR_TEXT = (40, 50, 60)
COLOR_GRAY = (130, 130, 130)
COLOR_GOLD = (180, 142, 70)
COLOR_DIVIDER = (210, 210, 210)
COLOR_FIGURE_RED = (200, 60, 50)
COLOR_FIGURE_BLACK = (40, 40, 50)
COLOR_FIGURE_GREEN = (60, 140, 70)
COLOR_FIGURE_GOLD = (190, 145, 60)


def normalize_card_format(value):
    v = (value or "event").strip().lower()
    if v in ("conference", "cr80", "badge"):
        return "conference"
    return "event"


def card_layout_pixels(card_format):
    """Output pixel size for tiling PDFs (matches render_card after scaling)."""
    if normalize_card_format(card_format) == "conference":
        return CONFERENCE_CARD_W, CONFERENCE_CARD_H
    return CARD_W, CARD_H
