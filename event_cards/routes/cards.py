"""Card preview + PDF generation."""

import io

from flask import Blueprint, abort, redirect, request, send_file, url_for

from ..config import EVENT, normalize_card_format
from ..models import get_guest, load_guests
from ..rendering.card import render_card
from ..rendering.pdf import build_print_sheets_pdf

cards_bp = Blueprint("cards", __name__)


@cards_bp.route("/preview/<code>")
def preview(code):
    g = get_guest(code)
    if not g:
        abort(404)
    fmt = normalize_card_format(request.args.get("format"))
    img = render_card(g, fmt)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@cards_bp.route("/generate")
def generate():
    guests = load_guests()
    if not guests:
        return redirect(url_for("guests.index"))
    fmt = normalize_card_format(request.args.get("format"))
    cards = [render_card(g, fmt).convert("RGB") for g in guests]
    buf = io.BytesIO()
    if len(cards) == 1:
        cards[0].save(buf, format="PDF", resolution=300)
    else:
        cards[0].save(
            buf,
            format="PDF",
            save_all=True,
            append_images=cards[1:],
            resolution=300,
        )
    buf.seek(0)
    suffix = "-cr80" if fmt == "conference" else ""
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"guest-cards-{EVENT['date_code']}{suffix}.pdf",
    )



@cards_bp.route("/generate/print-sheets")
def generate_print_sheets():
    guests = load_guests()
    if not guests:
        return redirect(url_for("guests.index"))
    paper = request.args.get("paper", "a4").strip().lower()
    if paper not in ("a4", "letter", "a3"):
        paper = "a4"
    fmt = normalize_card_format(request.args.get("format"))
    size = request.args.get("size", "standard").strip().lower()

    buf = build_print_sheets_pdf(guests, paper=paper, card_format=fmt, size=size)
    suffix = paper
    cr = "-cr80" if fmt == "conference" else ""
    sz = "-large" if size == "large" else ("-xlarge" if size == "xlarge" else "")
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"print-sheets-{EVENT['date_code']}-{suffix}{cr}{sz}.pdf",
    )
