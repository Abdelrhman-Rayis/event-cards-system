"""Built-in card themes (colors only for now; layout is shared).

Each theme is a flat dict so the style editor (Phase 6) can patch any
leaf via ``template.overrides`` in event.json.
"""

import copy

from .. import config

THEMES = {
    "classic_navy_gold": {
        "id": "classic_navy_gold",
        "name": "Classic Navy & Gold",
        "description": "Cream header with deep navy and warm gold accents.",
        "colors": {
            "header_bg": [250, 244, 230],
            "header_border": [224, 216, 184],
            "card_bg": [255, 255, 255],
            "primary": [28, 76, 92],
            "text": [40, 50, 60],
            "muted": [130, 130, 130],
            "accent": [180, 142, 70],
            "divider": [210, 210, 210],
            "photo_placeholder_bg": [235, 235, 235],
            "photo_placeholder_text": [170, 170, 170],
        },
    },
    "minimal_bw": {
        "id": "minimal_bw",
        "name": "Minimal Black & White",
        "description": "Magazine-clean monochrome, no accent color.",
        "colors": {
            "header_bg": [245, 245, 245],
            "header_border": [220, 220, 220],
            "card_bg": [255, 255, 255],
            "primary": [20, 20, 20],
            "text": [40, 40, 40],
            "muted": [130, 130, 130],
            "accent": [20, 20, 20],
            "divider": [220, 220, 220],
            "photo_placeholder_bg": [235, 235, 235],
            "photo_placeholder_text": [170, 170, 170],
        },
    },
    "modern_vibrant": {
        "id": "modern_vibrant",
        "name": "Modern Vibrant",
        "description": "Bold coral accent over a soft slate header.",
        "colors": {
            "header_bg": [243, 244, 248],
            "header_border": [220, 222, 230],
            "card_bg": [255, 255, 255],
            "primary": [35, 41, 66],
            "text": [45, 50, 70],
            "muted": [120, 125, 145],
            "accent": [238, 86, 90],
            "divider": [225, 228, 235],
            "photo_placeholder_bg": [232, 234, 240],
            "photo_placeholder_text": [165, 170, 185],
        },
    },
    "corporate_blue": {
        "id": "corporate_blue",
        "name": "Corporate Blue",
        "description": "Crisp white header with a confident corporate blue.",
        "colors": {
            "header_bg": [255, 255, 255],
            "header_border": [220, 226, 236],
            "card_bg": [255, 255, 255],
            "primary": [25, 76, 144],
            "text": [40, 50, 65],
            "muted": [120, 130, 145],
            "accent": [60, 142, 220],
            "divider": [220, 226, 236],
            "photo_placeholder_bg": [235, 238, 244],
            "photo_placeholder_text": [165, 175, 190],
        },
    },
    "wedding_elegant": {
        "id": "wedding_elegant",
        "name": "Wedding Elegant",
        "description": "Soft ivory with rose-gold accents for warmer events.",
        "colors": {
            "header_bg": [251, 244, 240],
            "header_border": [232, 218, 210],
            "card_bg": [255, 252, 250],
            "primary": [108, 67, 70],
            "text": [70, 50, 55],
            "muted": [150, 130, 130],
            "accent": [183, 132, 109],
            "divider": [232, 218, 210],
            "photo_placeholder_bg": [243, 235, 230],
            "photo_placeholder_text": [180, 160, 155],
        },
    },
}


DEFAULT_THEME_ID = "classic_navy_gold"


def _deep_merge(base, overrides):
    out = copy.deepcopy(base)
    if not isinstance(overrides, dict):
        return out
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def list_themes():
    """Return [(id, name, description), ...] for the theme picker."""
    return [(t["id"], t["name"], t["description"]) for t in THEMES.values()]


def get_active_theme():
    """Resolved theme = preset + event.json overrides."""
    cfg = config.CONFIG
    tpl = cfg.get("template", {}) or {}
    theme_id = tpl.get("id") or DEFAULT_THEME_ID
    base = THEMES.get(theme_id, THEMES[DEFAULT_THEME_ID])
    return _deep_merge(base, tpl.get("overrides") or {})


def color(name):
    """Pull an (R, G, B) tuple out of the active theme's colors."""
    c = get_active_theme()["colors"]
    v = c.get(name)
    if v is None:
        return (0, 0, 0)
    return tuple(int(x) for x in v)
