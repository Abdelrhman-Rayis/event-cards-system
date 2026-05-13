"""Setup wizard — edits event.json (title, fields, template, languages)."""

from collections import defaultdict

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import config
from ..rendering.themes import list_themes

setup_bp = Blueprint("setup", __name__)


_FIELD_TYPES = ("text", "select", "number")


_FORM_KNOWN_KEYS = {
    "id",
    "label",
    "type",
    "show_on_card",
    "default",
    "options",
    "options_text",
    "hint",
    "min",
    "max",
}


def _parse_fields(form, existing_fields):
    """Convert flat ``fields[i][key]`` form keys into a list of field dicts.

    Keys not exposed by the wizard (e.g. ``display_format``, ``placeholder``)
    are carried over from ``existing_fields`` when a field id matches, so the
    wizard never silently drops advanced configuration.
    """
    by_id_existing = {f.get("id"): f for f in (existing_fields or [])}

    by_idx: dict[int, dict] = defaultdict(dict)
    for key, value in form.items(multi=True):
        if not key.startswith("fields["):
            continue
        try:
            idx_str, rest = key[len("fields[") :].split("]", 1)
            idx = int(idx_str)
        except ValueError:
            continue
        # rest looks like "[id]" or "[options]"
        sub = rest.strip("[]")
        if sub == "options":
            by_idx[idx].setdefault("options", []).append(value)
        else:
            by_idx[idx][sub] = value

    fields = []
    for idx in sorted(by_idx.keys()):
        f = by_idx[idx]
        fid = (f.get("id") or "").strip()
        label = (f.get("label") or "").strip()
        if not fid or not label:
            continue
        ftype = f.get("type", "text")
        if ftype not in _FIELD_TYPES:
            ftype = "text"
        out = {
            "id": fid,
            "label": label,
            "type": ftype,
            "show_on_card": f.get("show_on_card") == "on",
            "default": (f.get("default") or "").strip(),
        }
        if ftype == "select":
            opts = [o.strip() for o in f.get("options", []) if o.strip()]
            # also accept newline-separated options textarea
            raw = f.get("options_text", "")
            if raw:
                opts = [o.strip() for o in raw.splitlines() if o.strip()]
            out["options"] = opts or ["Option 1"]
            if out["default"] and out["default"] not in out["options"]:
                out["default"] = out["options"][0]
        if ftype == "number":
            try:
                out["min"] = int(f.get("min", 0))
            except ValueError:
                out["min"] = 0
            try:
                out["max"] = int(f.get("max", 10))
            except ValueError:
                out["max"] = 10
            try:
                out["default"] = int(out["default"]) if out["default"] != "" else 0
            except ValueError:
                out["default"] = 0
        hint = (f.get("hint") or "").strip()
        if hint:
            out["hint"] = hint

        prev = by_id_existing.get(fid)
        if prev:
            for k, v in prev.items():
                if k not in out and k not in _FORM_KNOWN_KEYS:
                    out[k] = v
        fields.append(out)
    return fields


@setup_bp.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        cfg = dict(config.CONFIG)
        for key in (
            "title_primary",
            "title_secondary",
            "title_primary_ar",
            "title_secondary_ar",
            "date",
            "time",
            "location",
            "date_code",
        ):
            cfg[key] = request.form.get(key, "").strip()

        langs = request.form.getlist("languages")
        cfg["languages"] = [l for l in langs if l in ("en", "ar")] or ["en"]

        fields = _parse_fields(request.form, config.CONFIG.get("fields"))
        if fields:
            cfg["fields"] = fields

        template_id = request.form.get("template_id", "").strip()
        if template_id:
            tpl = dict(cfg.get("template") or {})
            tpl["id"] = template_id
            cfg["template"] = tpl

        config.save_config(cfg)
        config.reload_config()
        return redirect(url_for("setup.setup", saved=1))

    return render_template(
        "setup.html",
        cfg=config.CONFIG,
        themes=list_themes(),
        saved=request.args.get("saved") == "1",
    )
