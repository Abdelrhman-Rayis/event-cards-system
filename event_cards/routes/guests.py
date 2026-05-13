"""Guest CRUD + photo serving."""

import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from ..config import EVENT, PHOTOS_DIR
from ..models import gen_code, load_guests, save_guests

guests_bp = Blueprint("guests", __name__)


@guests_bp.route("/")
def index():
    return render_template("index.html", guests=load_guests(), event=EVENT)


@guests_bp.route("/add", methods=["POST"])
def add():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("guests.index"))

    role = request.form.get("role", "").strip() or "Guest"
    ticket_type = request.form.get("ticket_type", "").strip() or "Standard"
    try:
        companions = int(request.form.get("companions", "0") or 0)
    except ValueError:
        companions = 0
    companions = max(0, min(companions, 10))

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
        "role": role,
        "ticket_type": ticket_type,
        "companions": companions,
        "photo": photo_filename,
        "checked_in": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
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
