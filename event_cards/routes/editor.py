"""Style editor — color pickers + live preview that write template.overrides."""

import io
from contextlib import contextmanager

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .. import config
from ..models import load_guests
from ..rendering import card
from ..rendering.themes import THEMES, get_active_theme

editor_bp = Blueprint("editor", __name__)


_COLOR_KEYS = (
    "header_bg",
    "header_border",
    "card_bg",
    "primary",
    "text",
    "muted",
    "accent",
    "divider",
    "photo_placeholder_bg",
    "photo_placeholder_text",
)

_COLOR_LABELS = {
    "header_bg": "Header background",
    "header_border": "Header divider line",
    "card_bg": "Card background",
    "primary": "Primary (titles, accents)",
    "text": "Body text",
    "muted": "Muted / labels",
    "accent": "Accent (badges, underlines)",
    "divider": "Divider lines",
    "photo_placeholder_bg": "Photo placeholder fill",
    "photo_placeholder_text": "Photo placeholder text",
}


def _hex_to_rgb(s):
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return [int(s[i : i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return None


def _rgb_to_hex(rgb):
    if not rgb or len(rgb) < 3:
        return "#000000"
    return "#{:02X}{:02X}{:02X}".format(*[int(c) & 0xFF for c in rgb[:3]])


@contextmanager
def _temp_overrides(overrides):
    """Swap template.overrides into CONFIG for the duration of one render."""
    tpl = config.CONFIG.setdefault("template", {})
    old = tpl.get("overrides")
    tpl["overrides"] = overrides
    try:
        yield
    finally:
        if old is None:
            tpl.pop("overrides", None)
        else:
            tpl["overrides"] = old


def _colors_from_form(form):
    """Read ``color_<name>`` form fields into a {name: [r,g,b]} dict."""
    out = {}
    for k in _COLOR_KEYS:
        rgb = _hex_to_rgb(form.get(f"color_{k}", ""))
        if rgb is not None:
            out[k] = rgb
    return out


def _diff_overrides(colors, base_colors):
    """Keep only colors that actually differ from the base theme."""
    return {
        k: v
        for k, v in colors.items()
        if list(v) != list(base_colors.get(k, []))
    }


def _first_guest_id():
    guests = load_guests()
    return guests[0]["id"] if guests else None


@editor_bp.route("/editor", methods=["GET", "POST"])
def editor():
    if request.method == "POST":
        colors = _colors_from_form(request.form)
        cfg = dict(config.CONFIG)
        tpl = dict(cfg.get("template") or {})
        base = THEMES.get(tpl.get("id") or "classic_navy_gold", {}).get("colors", {})
        diff = _diff_overrides(colors, base)
        overrides = dict(tpl.get("overrides") or {})
        if diff:
            overrides["colors"] = diff
        else:
            overrides.pop("colors", None)
        tpl["overrides"] = overrides
        cfg["template"] = tpl
        config.save_config(cfg)
        config.reload_config()
        return redirect(url_for("editor.editor", saved=1))

    active = get_active_theme()
    colors = active.get("colors", {})
    color_rows = [
        {
            "key": k,
            "label": _COLOR_LABELS.get(k, k),
            "hex": _rgb_to_hex(colors.get(k)),
        }
        for k in _COLOR_KEYS
    ]
    theme_id = (config.CONFIG.get("template") or {}).get("id") or "classic_navy_gold"
    theme_name = THEMES.get(theme_id, {}).get("name", theme_id)
    return render_template(
        "editor.html",
        color_rows=color_rows,
        theme_id=theme_id,
        theme_name=theme_name,
        preview_code=_first_guest_id(),
        saved=request.args.get("saved") == "1",
    )


@editor_bp.route("/editor/preview")
def preview():
    """Render the first guest's card with the requested colors applied
    transiently (no event.json write). Used for live preview in the editor."""
    code = _first_guest_id()
    if not code:
        abort(404)
    guests = load_guests()
    guest = next((g for g in guests if g.get("id") == code), None)
    if not guest:
        abort(404)

    colors = {}
    for k in _COLOR_KEYS:
        rgb = _hex_to_rgb(request.args.get(f"color_{k}", ""))
        if rgb is not None:
            colors[k] = rgb

    overrides = {"colors": colors} if colors else {}
    with _temp_overrides(overrides):
        img = card.render_card(guest, "event")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")
