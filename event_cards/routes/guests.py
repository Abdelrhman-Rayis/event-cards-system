"""Guest CRUD + photo serving."""

import uuid
from datetime import datetime
from pathlib import Path

import io
import tarfile

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

from .. import config
from ..config import (
    EVENT,
    EVENT_CONFIG_FILE,
    GUESTS_FILE,
    PHOTOS_DIR,
    STATIC_DIR,
)
from ..models import companions_label, gen_code, load_guests, save_guests

guests_bp = Blueprint("guests", __name__)


def _coerce_field_value(field, raw):
    """Convert a form string to the storage type declared by the field schema."""
    ftype = field.get("type", "text")
    default = field.get("default", "")
    if ftype == "number":
        try:
            v = int(raw if raw not in (None, "") else default or 0)
        except (TypeError, ValueError):
            v = 0
        lo = field.get("min")
        hi = field.get("max")
        if lo is not None:
            v = max(int(lo), v)
        if hi is not None:
            v = min(int(hi), v)
        return v
    if ftype == "select":
        options = field.get("options") or []
        v = (raw or "").strip()
        if v in options:
            return v
        if default in options:
            return default
        return options[0] if options else v
    return (raw or "").strip() or (default or "")


def _format_field_value(field, value):
    """Mirror the renderer's display logic for the guest list."""
    if value is None or value == "":
        return ""
    fmt = field.get("display_format")
    if fmt == "companion_label":
        try:
            return companions_label(int(value))
        except (TypeError, ValueError):
            return str(value)
    if field.get("type") == "number":
        try:
            return f"+{int(value)}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _displayable_fields(cfg):
    """Fields the index page should render — both in the add-form and the list."""
    return [f for f in cfg.get("fields", []) if f.get("id") not in ("name", "photo")]


@guests_bp.route("/")
def index():
    cfg = config.CONFIG
    fields = _displayable_fields(cfg)
    guests = load_guests()
    return render_template(
        "index.html",
        guests=guests,
        event=EVENT,
        cfg=cfg,
        fields=fields,
        format_value=_format_field_value,
    )


@guests_bp.route("/add", methods=["POST"])
def add():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("guests.index"))

    photo_filename = None
    photo = request.files.get("photo")
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
            photo_filename = f"{uuid.uuid4().hex}{ext}"
            photo.save(str(PHOTOS_DIR / photo_filename))

    guest = {
        "id": gen_code(),
        "name": name,
        "photo": photo_filename,
        "checked_in": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    for field in _displayable_fields(config.CONFIG):
        guest[field["id"]] = _coerce_field_value(field, request.form.get(field["id"]))

    guests = load_guests()
    guests.append(guest)
    save_guests(guests)
    return redirect(url_for("guests.index"))


@guests_bp.route("/delete/<code>", methods=["POST"])
def delete(code):
    guests = [g for g in load_guests() if g["id"] != code]
    save_guests(guests)
    return redirect(url_for("guests.index"))


@guests_bp.route("/photo/<filename>")
def photo(filename):
    return send_from_directory(PHOTOS_DIR, filename)


@guests_bp.route("/export-all")
def export_all():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if GUESTS_FILE.exists():
            tar.add(GUESTS_FILE, arcname="guests.json")
        if EVENT_CONFIG_FILE.exists():
            tar.add(EVENT_CONFIG_FILE, arcname="event.json")
        if PHOTOS_DIR.exists():
            tar.add(PHOTOS_DIR, arcname="photos")
        for logo in sorted(STATIC_DIR.glob("logo*.png")):
            tar.add(logo, arcname=f"static/{logo.name}")
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/gzip",
        as_attachment=True,
        download_name=f"event-cards-export-{EVENT['date_code']}.tar.gz",
    )

import pandas as pd

@guests_bp.route("/import", methods=["POST"])
def import_excel():
    file = request.files.get("file")
    if not file or not file.filename:
        return redirect(url_for("guests.index"))

    try:
        df = pd.read_excel(file)
        # assuming names are in the first column or column named 'Name'/'name'
        name_col = None
        for col in df.columns:
            if str(col).strip().lower() in ('name', 'full name', 'fullname', 'names'):
                name_col = col
                break
        if name_col is None:
            name_col = df.columns[0] # fallback to first column
        
        guests = load_guests()
        for idx, row in df.iterrows():
            name = str(row[name_col]).strip()
            if not name or name.lower() == 'nan':
                continue
            
            guest = {
                "id": gen_code(),
                "name": name,
                "photo": None,
                "checked_in": False,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            
            # Default required logic:
            guest["role"] = "Guest"
            guest["ticket_type"] = "VIP Access"
            
            # Ensure other fields have defaults
            for field in _displayable_fields(config.CONFIG):
                if field["id"] not in ("role", "ticket_type"):
                    guest[field["id"]] = _coerce_field_value(field, None)
                    
            guests.append(guest)
            
        save_guests(guests)
    except Exception as e:
        print("Error importing:", e)
    
    return redirect(url_for("guests.index"))

@guests_bp.route("/edit/<code>", methods=["GET", "POST"])
def edit(code):
    guests = load_guests()
    guest_idx = next((i for i, g in enumerate(guests) if g["id"] == code), None)
    if guest_idx is None:
        return redirect(url_for("guests.index"))
        
    guest = guests[guest_idx]
    
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            guest["name"] = name
            
        photo = request.files.get("photo")
        if photo and photo.filename:
            ext = Path(photo.filename).suffix.lower()
            if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
                photo_filename = f"{uuid.uuid4().hex}{ext}"
                photo.save(str(PHOTOS_DIR / photo_filename))
                guest["photo"] = photo_filename
                
        for field in _displayable_fields(config.CONFIG):
            guest[field["id"]] = _coerce_field_value(field, request.form.get(field["id"]))
            
        guests[guest_idx] = guest
        save_guests(guests)
        return redirect(url_for("guests.index"))
        
    cfg = config.CONFIG
    fields = _displayable_fields(cfg)
    return render_template(
        "edit.html",
        guest=guest,
        event=EVENT,
        cfg=cfg,
        fields=fields,
    )
