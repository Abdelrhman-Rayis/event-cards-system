"""
Sudanese Forum for the Homeland — Guest Card Generator
======================================================

Run:
    python3 -m pip install -r requirements.txt
    python3 app.py
    open http://127.0.0.1:5151

What it does:
    • Form-based UI to add guests one by one (name, role, ticket type,
      companions, photo)
    • Each guest gets a unique scannable Code 128 barcode (EVT-YYYYMMDD-XXXXX)
    • "Generate PDF" — one full page per guest (event size or CR80 conference)
    • "Print sheets" — several cards per sheet (event or CR80) with cut gaps
    • "Door verification" — security scans the barcode, sees the guest's
      photo + details; check-in is logged so the same code can't be reused

The dev server listens on 127.0.0.1 only (not exposed on your LAN).
"""

import io
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import (Flask, abort, redirect, render_template_string, request,
                   send_file, send_from_directory, url_for)
from PIL import Image, ImageDraw, ImageFont, ImageOps
import barcode
from barcode.writer import ImageWriter
import arabic_reshaper
from bidi.algorithm import get_display

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

# ----------------- Paths & event config -----------------

APP_DIR = Path(__file__).parent
PHOTOS_DIR = APP_DIR / "photos"
OUTPUT_DIR = APP_DIR / "output"
STATIC_DIR = APP_DIR / "static"
GUESTS_FILE = APP_DIR / "guests.json"

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

# ----------------- Card visual constants -----------------

CARD_W, CARD_H = 1950, 1200
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


def finalize_card_for_format(img, card_format):
    """Scale design to CR80 conference badge; event = full design canvas."""
    if normalize_card_format(card_format) != "conference":
        return img
    tw, th = CONFERENCE_CARD_W, CONFERENCE_CARD_H
    scale = min(tw / img.width, th / img.height)
    nw = max(1, int(round(img.width * scale)))
    nh = max(1, int(round(img.height * scale)))
    resized = img.resize((nw, nh), Image.LANCZOS)
    out = Image.new("RGB", (tw, th), "white")
    out.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return out

# ----------------- Font helpers -----------------

_FONT_CACHE = {}

def _font_try(paths_with_index, size, **truetype_kw):
    for path, idx in paths_with_index:
        try:
            return ImageFont.truetype(path, size, index=idx, **truetype_kw)
        except (OSError, IOError, TypeError, ValueError):
            continue
    return ImageFont.load_default()


def _ar_truetype(path, size, index=0):
    """Load Arabic-capable font with BASIC layout.

    We pre-shape user text with arabic_reshaper + python-bidi. Pillow's
    default RAQM layout re-shapes that output and often yields missing glyphs
    (tofu). BASIC matches our manual shaping.
    """
    try:
        return ImageFont.truetype(
            path, size, index=index, layout_engine=ImageFont.Layout.BASIC
        )
    except TypeError:
        # Older Pillow without layout_engine
        return ImageFont.truetype(path, size, index=index)
    except (OSError, IOError, ValueError):
        return None

def font(size, bold=False):
    key = ("en", size, bold)
    if key not in _FONT_CACHE:
        if bold:
            cands = [
                ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
                ("/System/Library/Fonts/Helvetica.ttc", 1),
                ("/Library/Fonts/Arial Bold.ttf", 0),
                ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
            ]
        else:
            cands = [
                ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
                ("/System/Library/Fonts/Helvetica.ttc", 0),
                ("/Library/Fonts/Arial.ttf", 0),
                ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
            ]
        _FONT_CACHE[key] = _font_try(cands, size)
    return _FONT_CACHE[key]

def ar_font(size, bold=False):
    key = ("ar", size, bold)
    if key not in _FONT_CACHE:
        idx_bold = 1 if bold else 0
        # Order: common macOS paths first, then wide-coverage fallbacks (Linux/Homebrew).
        cands = [
            ("/System/Library/Fonts/GeezaPro.ttc", idx_bold),
            ("/System/Library/Fonts/Supplemental/GeezaPro.ttc", idx_bold),
            ("/System/Library/Fonts/Geeza Pro.ttf", 0),
            ("/Library/Fonts/Arial Unicode.ttf", 0),
            ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
            ("/Library/Fonts/Arial Unicode MS.ttf", 0),
            ("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf", 0),
            ("/opt/homebrew/share/fonts/noto/NotoNaskhArabic-Bold.ttf" if bold else "/opt/homebrew/share/fonts/noto/NotoNaskhArabic-Regular.ttf", 0),
            ("/System/Library/Fonts/Helvetica.ttc", 0),
        ]
        chosen = None
        for path, idx in cands:
            if not Path(path).exists():
                continue
            chosen = _ar_truetype(path, size, index=idx)
            if chosen is not None:
                break
            # Some .ttc builds reject a face index; try 0 as fallback.
            if path.lower().endswith(".ttc") and idx != 0:
                chosen = _ar_truetype(path, size, index=0)
                if chosen is not None:
                    break
        _FONT_CACHE[key] = chosen if chosen is not None else ImageFont.load_default()
    return _FONT_CACHE[key]

def ar_shape(text):
    return get_display(arabic_reshaper.reshape(text))

# Arabic script ranges (primary + presentation forms + extended Arabic blocks)
_ARABIC_SCRIPT_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)


def has_arabic(text):
    if not text:
        return False
    return _ARABIC_SCRIPT_RE.search(text) is not None


def display_bidi(text):
    """User-entered text ready for PIL (reshape + bidi when Arabic is present)."""
    text = text or ""
    if has_arabic(text):
        return ar_shape(text)
    return text


def text_font(size, bold, sample_text):
    """Use an Arabic-capable font when the string contains Arabic script."""
    return ar_font(size, bold) if has_arabic(sample_text) else font(size, bold)


def fit_text_for_width(draw, text, max_w, size_start, bold, min_size=18, step=2):
    """Largest font size so display_bidi(text) fits within max_w pixels."""
    text = text or ""
    disp = display_bidi(text)
    size = int(size_start)
    while size >= min_size:
        fnt = text_font(size, bold, text)
        try:
            w = float(draw.textlength(disp, font=fnt))
        except Exception:
            bbox = draw.textbbox((0, 0), disp, font=fnt)
            w = float(bbox[2] - bbox[0])
        if w <= max_w:
            return fnt, disp, size
        size -= step
    fnt = text_font(min_size, bold, text)
    return fnt, disp, min_size


def initials_from_name(name):
    """Two-letter placeholder for photo (Latin or Arabic)."""
    name = (name or "").strip()
    if not name:
        return "?"
    parts = name.split()
    if len(parts) >= 2:
        return parts[0][0] + parts[1][0]
    if len(name) >= 2:
        return name[:2]
    return name[0]

# ----------------- Data helpers -----------------

def load_guests():
    if not GUESTS_FILE.exists():
        return []
    try:
        return json.loads(GUESTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

def save_guests(guests):
    GUESTS_FILE.write_text(json.dumps(guests, indent=2, ensure_ascii=False), encoding="utf-8")

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

# ----------------- Icon drawing (no emoji-font dependency) -----------------

def draw_pin(d, x, y, s, color):
    d.ellipse([x + s * 0.10, y, x + s * 0.90, y + s * 0.78], outline=color, width=2)
    d.polygon([(x + s * 0.30, y + s * 0.55),
               (x + s * 0.70, y + s * 0.55),
               (x + s * 0.50, y + s * 0.98)], fill=color)
    d.ellipse([x + s * 0.36, y + s * 0.22, x + s * 0.64, y + s * 0.50], fill=color)

def draw_lock(d, x, y, s, color):
    d.arc([x + s * 0.20, y, x + s * 0.80, y + s * 0.55], 180, 360, fill=color, width=3)
    d.rounded_rectangle([x + s * 0.10, y + s * 0.40, x + s * 0.90, y + s * 0.95],
                        radius=int(s * 0.08), fill=color)

# Cached resized logo for header (RGBA). Only cache successful loads — never
# cache "missing file" or the logo never appears until process restart.
_logo_cache_mtime = None
_logo_cache_image = None


def _resolve_logo_path():
    """First existing logo file wins (absolute paths)."""
    base = Path(__file__).resolve().parent
    for name in ("logo.png", "logo.jpg", "logo.webp"):
        p = base / "static" / name
        if p.is_file():
            return p
    return None


def _header_logo_image():
    """RGBA logo scaled for header, or None if missing/unreadable."""
    global _logo_cache_mtime, _logo_cache_image
    path = _resolve_logo_path()
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _logo_cache_image is not None and _logo_cache_mtime == mtime:
        return _logo_cache_image
    try:
        im = Image.open(path).convert("RGBA")
        max_h = 200
        sc = min(1.0, max_h / max(im.height, 1))
        nw = max(1, int(im.width * sc))
        nh = max(1, int(im.height * sc))
        resized = im.resize((nw, nh), Image.LANCZOS)
        _logo_cache_image = resized
        _logo_cache_mtime = mtime
        return resized
    except (OSError, ValueError):
        return None


def _paste_header_logo(card):
    """Paste logo on cream header; return x for English title start."""
    lg = _header_logo_image()
    if lg is None:
        return 100
    lx, ly = 48, 48
    # Explicit alpha composite (reliable across Pillow versions)
    if lg.mode == "RGBA":
        rgb = Image.merge("RGB", lg.split()[:3])
        alpha = lg.split()[3]
        card.paste(rgb, (lx, ly), alpha)
    else:
        card.paste(lg, (lx, ly))
    return lx + lg.width + 28

# ----------------- Header rendering -----------------

def render_header(card):
    """Bilingual title on a cream strip, then a thin row with date/time/location."""
    top_h = 290
    draw = ImageDraw.Draw(card)
    draw.rectangle([0, 0, CARD_W, top_h], fill=BG_CREAM)

    en_x = _paste_header_logo(card)
    draw = ImageDraw.Draw(card)

    title_font = font(86, bold=True)
    draw.text((en_x, 60), EVENT["title_en_l1"], font=title_font, fill=COLOR_DARK)
    draw.text((en_x, 165), EVENT["title_en_l2"], font=title_font, fill=COLOR_DARK)

    ar_title_font = ar_font(88, bold=True)
    for i, line in enumerate([EVENT["title_ar_l1"], EVENT["title_ar_l2"]]):
        txt = ar_shape(line)
        w = draw.textlength(txt, font=ar_title_font)
        draw.text((CARD_W - 100 - w, 60 + i * 105), txt, font=ar_title_font, fill=COLOR_DARK)

    # Event info strip (date · time · location)
    info_strip_h = 100
    draw.rectangle([0, top_h, CARD_W, top_h + info_strip_h], fill=BG_CREAM)
    draw.line([(0, top_h + info_strip_h), (CARD_W, top_h + info_strip_h)],
              fill=BG_HEADER_BORDER, width=2)

    info_y = top_h + (info_strip_h - 44) // 2
    info_font_obj = font(44)
    text = EVENT["location"]
    text_w = int(draw.textlength(text, font=info_font_obj))
    item_w = 44 + 14 + text_w
    x = (CARD_W - item_w) // 2
    draw_pin(draw, x, info_y, 44, COLOR_DARK)
    draw.text((x + 44 + 14, info_y + 2), text, font=info_font_obj, fill=COLOR_TEXT)

    return top_h + info_strip_h

# ----------------- Card rendering -----------------

def render_card(guest, card_format="event"):
    card = Image.new("RGB", (CARD_W, CARD_H), "white")
    header_h = render_header(card)
    draw = ImageDraw.Draw(card)

    # ---------- BODY ----------
    body_top = header_h + 30
    photo_size = 440
    photo_x = 110
    photo_y = body_top + 20

    # Photo background
    draw.rectangle([photo_x, photo_y, photo_x + photo_size, photo_y + photo_size],
                   fill=(235, 235, 235))

    drew_photo = False
    if guest.get("photo"):
        ppath = PHOTOS_DIR / guest["photo"]
        if ppath.exists():
            try:
                ph = Image.open(ppath).convert("RGB")
                ph = ImageOps.exif_transpose(ph)
                ph = ImageOps.fit(ph, (photo_size, photo_size), Image.LANCZOS)
                card.paste(ph, (photo_x, photo_y))
                drew_photo = True
            except Exception:
                pass

    if not drew_photo:
        initials = initials_from_name(guest.get("name", ""))
        ifont = text_font(130, True, initials)
        bbox = draw.textbbox((0, 0), initials, font=ifont)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((photo_x + (photo_size - tw) // 2 - bbox[0],
                   photo_y + (photo_size - th) // 2 - bbox[1] - 10),
                  initials, font=ifont, fill=(170, 170, 170))

    # VERIFIED badge
    badge_w, badge_h = 200, 56
    bx = photo_x + (photo_size - badge_w) // 2
    by = photo_y + photo_size - badge_h - 16
    draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h], radius=6, fill=COLOR_GOLD)
    bfont = font(30, bold=True)
    bw = draw.textlength("VERIFIED", font=bfont)
    draw.text((bx + (badge_w - bw) // 2, by + 11), "VERIFIED", font=bfont, fill="white")

    # Right-side info column
    info_x = photo_x + photo_size + 90

    draw.text((info_x, photo_y + 10), "GUEST NAME", font=font(36), fill=COLOR_GRAY)
    nm = guest.get("name", "") or ""
    name_max_w = float(CARD_W - info_x - 90)
    name_f, name_disp, _ = fit_text_for_width(draw, nm, name_max_w, 124, True, min_size=64)
    draw.text((info_x, photo_y + 64), name_disp, font=name_f, fill=COLOR_DARK)

    col_label_y = photo_y + 268
    col_value_y = photo_y + 318
    cols = [
        ("TICKET TYPE", guest.get("ticket_type", "Standard")),
        ("ROLE", guest.get("role", "Guest")),
        ("GUESTS", companions_label(guest.get("companions", 0))),
    ]
    col_w = (CARD_W - info_x - 100) // 3
    col_text_max_w = float(col_w - 24)
    for i, (label, value) in enumerate(cols):
        cx = info_x + i * col_w
        draw.text((cx, col_label_y), label, font=font(36), fill=COLOR_GRAY)
        val = value if value is not None else ""
        val_f, val_disp, _ = fit_text_for_width(draw, val, col_text_max_w, 60, True, min_size=32)
        draw.text((cx, col_value_y), val_disp, font=val_f, fill=COLOR_TEXT)

    # Secured line
    sec_y = col_value_y + 110
    draw.ellipse([info_x, sec_y + 8, info_x + 16, sec_y + 24], fill=COLOR_DARK)
    draw.text((info_x + 28, sec_y),
              "SECURED  ·  HOLOGRAPHIC SEAL  ·  TAMPER-PROOF",
              font=font(30), fill=COLOR_GRAY)

    # ---------- DASHED DIVIDER ----------
    div_y = photo_y + photo_size + 60
    dx = 90
    while dx < CARD_W - 90:
        draw.line([(dx, div_y), (dx + 24, div_y)], fill=COLOR_DIVIDER, width=3)
        dx += 40

    # ---------- FOOTER ----------
    footer_y = div_y + 40

    # Barcode
    bc = barcode.get("code128", guest["id"], writer=ImageWriter())
    bc_buf = io.BytesIO()
    bc.write(bc_buf, options={
        "write_text": False,
        "module_height": 16,
        "module_width": 0.35,
        "quiet_zone": 2,
    })
    bc_buf.seek(0)
    bc_img = Image.open(bc_buf).convert("RGB")
    target_w = 820
    target_h = int(bc_img.height * (target_w / bc_img.width))
    bc_img = bc_img.resize((target_w, target_h), Image.LANCZOS)
    card.paste(bc_img, (110, footer_y))

    code_font = font(42, bold=True)
    code_w = draw.textlength(guest["id"], font=code_font)
    draw.text((110 + (target_w - code_w) // 2, footer_y + target_h + 18),
              guest["id"], font=code_font, fill=COLOR_TEXT)

    # Door verification (right)
    dv_x = CARD_W - 760
    draw_lock(draw, dv_x, footer_y + 6, 48, COLOR_DARK)
    draw.text((dv_x + 66, footer_y), "DOOR VERIFICATION",
              font=font(42, bold=True), fill=COLOR_DARK)
    draw.text((dv_x, footer_y + 78),
              "Security scans this barcode at entry.",
              font=font(32), fill=COLOR_TEXT)
    draw.text((dv_x, footer_y + 124),
              "Valid for one entry only.",
              font=font(32), fill=COLOR_TEXT)

    return finalize_card_for_format(card, card_format)

# ----------------- Print sheet PDF (multiple cards per page, cut apart) -----------------

PRINT_DPI = 300
PRINT_MARGIN = 48
PRINT_GAP = 24
PRINT_MIN_SCALE = 0.40
PRINT_MAX_GRID = 6


def mm_to_print_px(mm):
    return int(round(mm * PRINT_DPI / 25.4))


def paper_dimensions(paper):
    """Portrait (width, height) in pixels at PRINT_DPI."""
    p = (paper or "a4").strip().lower()
    if p == "letter":
        return int(round(8.5 * PRINT_DPI)), int(round(11.0 * PRINT_DPI))
    return mm_to_print_px(210), mm_to_print_px(297)


def best_print_layout(page_w, page_h, cw, ch):
    """Maximize cards per page; each card scaled uniformly with gaps for cutting."""
    uw = page_w - 2 * PRINT_MARGIN
    uh = page_h - 2 * PRINT_MARGIN
    if uw <= 10 or uh <= 10:
        return None
    gap = PRINT_GAP
    best = None
    best_key = None
    for cols in range(1, PRINT_MAX_GRID + 1):
        for rows in range(1, PRINT_MAX_GRID + 1):
            slot_w = (uw - (cols - 1) * gap) / cols
            slot_h = (uh - (rows - 1) * gap) / rows
            if slot_w <= 1 or slot_h <= 1:
                continue
            scale = min(slot_w / cw, slot_h / ch)
            if scale < PRINT_MIN_SCALE:
                continue
            per = cols * rows
            key = (per, scale)
            if best_key is None or key > best_key:
                best_key = key
                best = {"cols": cols, "rows": rows, "scale": scale, "per_page": per}
    if best is None:
        scale = min(uw / cw, uh / ch)
        best = {"cols": 1, "rows": 1, "scale": scale, "per_page": 1}
    return best


def pick_global_print_layout(paper, cw, ch):
    """Best grid across portrait and landscape for the paper size."""
    pw, ph = paper_dimensions(paper)
    chosen = None
    chosen_key = None
    for w, h in ((pw, ph), (ph, pw)):
        lay = best_print_layout(w, h, cw, ch)
        if lay is None:
            continue
        key = (lay["per_page"], lay["scale"])
        if chosen_key is None or key > chosen_key:
            chosen_key = key
            chosen = {**lay, "page_w": w, "page_h": h, "card_w": cw, "card_h": ch}
    return chosen


def dashed_rectangle(draw, bbox, dash=14, gap=8, fill=(145, 150, 155), width=2):
    x0, y0, x1, y1 = bbox

    def edge_h(y, xa, xb):
        if xa > xb:
            xa, xb = xb, xa
        x = xa
        while x < xb:
            x2 = min(x + dash, xb)
            draw.line([(x, y), (x2, y)], fill=fill, width=width)
            x = x2 + gap

    def edge_v(x, ya, yb):
        if ya > yb:
            ya, yb = yb, ya
        y = ya
        while y < yb:
            y2 = min(y + dash, yb)
            draw.line([(x, y), (x, y2)], fill=fill, width=width)
            y = y2 + gap

    edge_h(y0, x0, x1)
    edge_h(y1, x0, x1)
    edge_v(x0, y0, y1)
    edge_v(x1, y0, y1)


def compose_print_sheet_page(card_images, layout):
    """Paste up to cols*rows cards; dashed box around each for scissors."""
    page_w, page_h = layout["page_w"], layout["page_h"]
    cols, rows = layout["cols"], layout["rows"]
    scale = layout["scale"]
    cw = layout["card_w"]
    ch = layout["card_h"]
    sheet = Image.new("RGB", (page_w, page_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    uw = page_w - 2 * PRINT_MARGIN
    uh = page_h - 2 * PRINT_MARGIN
    gap = PRINT_GAP
    slot_w = (uw - (cols - 1) * gap) / cols
    slot_h = (uh - (rows - 1) * gap) / rows
    dw = max(1, int(round(cw * scale)))
    dh = max(1, int(round(ch * scale)))
    pad = 4

    for idx, card in enumerate(card_images):
        if idx >= cols * rows:
            break
        ci = idx % cols
        ri = idx // cols
        x = PRINT_MARGIN + ci * (slot_w + gap) + (slot_w - dw) / 2
        y = PRINT_MARGIN + ri * (slot_h + gap) + (slot_h - dh) / 2
        xi, yi = int(round(x)), int(round(y))
        resized = card.resize((dw, dh), Image.LANCZOS)
        sheet.paste(resized, (xi, yi))
        dashed_rectangle(draw, (xi - pad, yi - pad, xi + dw + pad, yi + dh + pad))

    return sheet


def build_print_sheets_pdf(guests, paper="a4", card_format="event"):
    cf = normalize_card_format(card_format)
    cw, ch = card_layout_pixels(cf)
    layout = pick_global_print_layout(paper, cw, ch)
    if layout is None:
        pw, ph = paper_dimensions(paper)
        bl = best_print_layout(pw, ph, cw, ch)
        layout = {**bl, "page_w": pw, "page_h": ph, "card_w": cw, "card_h": ch}
    per = layout["per_page"]
    card_images = [render_card(g, cf).convert("RGB") for g in guests]
    pages = []
    for start in range(0, len(card_images), per):
        chunk = card_images[start : start + per]
        pages.append(compose_print_sheet_page(chunk, layout))
    buf = io.BytesIO()
    if len(pages) == 1:
        pages[0].save(buf, format="PDF", resolution=PRINT_DPI)
    else:
        pages[0].save(
            buf,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=PRINT_DPI,
        )
    buf.seek(0)
    return buf

# ----------------- HTML templates -----------------

INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0F4C5C">
  <title>Guest Cards — {{ event.title_en_l1 }} {{ event.title_en_l2 }}</title>
  <style>
    :root {
      --primary: #0F4C5C;
      --primary-hover: #155F73;
      --accent: #C9A14A;
      --accent-hover: #B68E3E;
      --bg: #F7F8FA;
      --surface: #FFFFFF;
      --text: #1F2937;
      --muted: #6B7280;
      --border: #E5E7EB;
      --success: #047857;
      --success-bg: rgba(16,185,129,0.12);
      --danger: #DC2626;
      --danger-bg: rgba(220,38,38,0.08);
      --radius: 12px;
      --radius-sm: 8px;
      --tap: 44px;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", system-ui, sans-serif;
      font-size: 15px; line-height: 1.5; color: var(--text);
      background: var(--bg); -webkit-font-smoothing: antialiased;
    }
    h1, h2 { margin: 0; }

    .hdr {
      background: var(--surface); border-bottom: 1px solid var(--border);
      position: sticky; top: 0; z-index: 10;
    }
    .hdr__inner {
      max-width: 1100px; margin: 0 auto; padding: 14px 20px;
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
    }
    .hdr__brand h1 { font-size: 17px; font-weight: 600; color: var(--primary); }
    .hdr__brand p { margin: 2px 0 0; font-size: 12px; color: var(--muted); }
    @media (max-width: 480px) {
      .hdr__inner { padding: 12px 14px; }
      .hdr__brand h1 { font-size: 15px; }
      .hdr__brand p { display: none; }
    }

    .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
    @media (max-width: 480px) { .container { padding: 14px; } }

    .grid {
      display: grid; gap: 16px;
      grid-template-columns: minmax(0, 380px) minmax(0, 1fr);
      align-items: start;
    }
    @media (max-width: 820px) { .grid { grid-template-columns: 1fr; } }

    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 20px;
    }
    .card__hdr {
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px; margin-bottom: 16px;
    }
    .card__hdr h2 { font-size: 16px; font-weight: 600; color: var(--text); }

    .field { margin-top: 14px; }
    .field:first-child { margin-top: 0; }
    label {
      display: block; font-size: 11px; font-weight: 700; color: var(--muted);
      margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;
    }
    .input, .select, .file {
      width: 100%; padding: 11px 12px; font: inherit; color: inherit;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    .input:focus, .select:focus {
      outline: none; border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(15,76,92,0.12);
    }
    .input, .select { unicode-bidi: plaintext; }
    .hint { font-size: 12px; color: var(--muted); margin-top: 6px; }

    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      padding: 0 16px; min-height: var(--tap); font: inherit;
      font-weight: 600; font-size: 14px; border: 1px solid transparent;
      border-radius: var(--radius-sm); cursor: pointer; text-decoration: none;
      transition: background-color 0.15s, border-color 0.15s, color 0.15s;
      user-select: none;
    }
    .btn--primary { background: var(--primary); color: white; }
    .btn--primary:hover { background: var(--primary-hover); }
    .btn--accent { background: var(--accent); color: white; }
    .btn--accent:hover { background: var(--accent-hover); }
    .btn--ghost {
      background: var(--surface); color: var(--primary); border-color: var(--border);
    }
    .btn--ghost:hover { background: var(--bg); border-color: var(--primary); }
    .btn--block { width: 100%; }
    .btn--sm { min-height: 34px; padding: 0 12px; font-size: 13px; }
    .btn--danger {
      background: transparent; color: var(--danger); border-color: var(--border);
    }
    .btn--danger:hover { background: var(--danger-bg); border-color: var(--danger); }

    .hero-cta__sub {
      font-size: 12px; color: var(--muted); text-align: center; margin: 8px 0 0;
    }

    .more {
      margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px;
    }
    .more summary {
      cursor: pointer; font-size: 13px; font-weight: 600; color: var(--primary);
      list-style: none; padding: 6px 0; user-select: none;
    }
    .more summary::-webkit-details-marker { display: none; }
    .more summary::before {
      content: "›"; display: inline-block; margin-right: 6px;
      transition: transform 0.15s; font-size: 16px;
    }
    .more[open] summary::before { transform: rotate(90deg); }
    .export-grid {
      display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;
    }
    @media (max-width: 480px) { .export-grid { grid-template-columns: 1fr; } }
    .export-group {
      background: var(--bg); border-radius: var(--radius-sm); padding: 10px 12px;
    }
    .export-group__label {
      font-size: 10px; font-weight: 700; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px;
    }
    .export-group__row { display: flex; gap: 6px; }
    .export-group__row .btn { flex: 1; }

    .glist { margin: 16px 0 0; padding: 0; list-style: none; }
    .glist__empty {
      text-align: center; padding: 48px 16px; color: var(--muted); font-size: 14px;
    }
    .grow {
      display: flex; align-items: center; gap: 12px;
      padding: 14px 0; border-bottom: 1px solid var(--border);
    }
    .grow:last-child { border-bottom: 0; padding-bottom: 0; }
    .grow__photo {
      width: 48px; height: 48px; border-radius: 50%; object-fit: cover;
      background: var(--bg); flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      color: var(--muted); font-weight: 600; font-size: 16px;
    }
    .grow__info { flex: 1; min-width: 0; }
    .grow__name {
      font-weight: 600; font-size: 15px; color: var(--text);
      unicode-bidi: plaintext; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap;
    }
    .grow__meta {
      font-size: 12px; color: var(--muted); margin-top: 2px;
      unicode-bidi: plaintext; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap;
    }
    .grow__code {
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 11px; padding: 1px 6px;
      background: var(--bg); border-radius: 4px;
    }
    .grow__actions { display: flex; gap: 6px; flex-shrink: 0; }
    .grow__actions form { display: inline; margin: 0; }
    .badge {
      display: inline-block; padding: 2px 8px;
      font-size: 10px; font-weight: 700; border-radius: 12px;
      letter-spacing: 0.04em; vertical-align: middle; margin-left: 6px;
    }
    .badge--ok { background: var(--success-bg); color: var(--success); }
    @media (max-width: 540px) {
      .grow { flex-wrap: wrap; }
      .grow__actions { width: 100%; justify-content: flex-end; padding-left: 60px; }
    }
  </style>
</head>
<body>
  <header class="hdr">
    <div class="hdr__inner">
      <div class="hdr__brand">
        <h1>Guest Cards</h1>
        <p>{{ event.title_en_l1 }} {{ event.title_en_l2 }} · {{ event.date }} · {{ event.location }}</p>
      </div>
      <a href="{{ url_for('verify') }}" class="btn btn--ghost btn--sm">Door verification →</a>
    </div>
  </header>

  <main class="container">
    <div class="grid">

      <section class="card">
        <div class="card__hdr"><h2>Add guest</h2></div>
        <form action="{{ url_for('add') }}" method="post" enctype="multipart/form-data">
          <div class="field">
            <label for="f-name">Full name</label>
            <input id="f-name" type="text" name="name" class="input" required dir="auto"
                   autocomplete="name" placeholder="Ahmed Al-Rashid / أحمد الرشيد">
          </div>
          <div class="field">
            <label for="f-role">Role</label>
            <input id="f-role" type="text" name="role" class="input" dir="auto"
                   autocomplete="organization-title" placeholder="Speaker / متحدث">
          </div>
          <div class="field">
            <label for="f-ticket">Ticket type</label>
            <select id="f-ticket" name="ticket_type" class="select" dir="auto">
              <option value="VIP Access">VIP Access</option>
              <option value="Standard">Standard</option>
              <option value="Press">Press</option>
              <option value="Staff">Staff</option>
              <option value="Sponsor">Sponsor</option>
            </select>
          </div>
          <div class="field">
            <label for="f-comp">Companions</label>
            <input id="f-comp" type="number" name="companions" value="0" min="0" max="10" class="input">
            <div class="hint">Additional people allowed in with this guest.</div>
          </div>
          <div class="field">
            <label for="f-photo">Photo</label>
            <input id="f-photo" type="file" name="photo" accept="image/*" class="file">
            <div class="hint">JPG, PNG or HEIC. Initials are shown if blank.</div>
          </div>
          <div class="field">
            <button type="submit" class="btn btn--primary btn--block">Add guest</button>
          </div>
        </form>
      </section>

      <section class="card">
        <div class="card__hdr"><h2>Guests ({{ guests|length }})</h2></div>

        {% if guests %}
          <a href="{{ url_for('generate_print_sheets', paper='a4', format='event') }}"
             class="btn btn--accent btn--block"
             title="A4 PDF: multiple cards per page with dashed cut lines">
            Generate cards for printing (A4)
          </a>
          <p class="hero-cta__sub">Multiple cards per page · cut along dashed lines · print at 100% scale</p>

          <details class="more">
            <summary>More export options</summary>
            <div class="export-grid">
              <div class="export-group">
                <div class="export-group__label">Sheets — A4</div>
                <div class="export-group__row">
                  <a href="{{ url_for('generate_print_sheets', paper='a4', format='event') }}" class="btn btn--ghost btn--sm">Event</a>
                  <a href="{{ url_for('generate_print_sheets', paper='a4', format='conference') }}" class="btn btn--ghost btn--sm">CR80</a>
                </div>
              </div>
              <div class="export-group">
                <div class="export-group__label">Sheets — Letter</div>
                <div class="export-group__row">
                  <a href="{{ url_for('generate_print_sheets', paper='letter', format='event') }}" class="btn btn--ghost btn--sm">Event</a>
                  <a href="{{ url_for('generate_print_sheets', paper='letter', format='conference') }}" class="btn btn--ghost btn--sm">CR80</a>
                </div>
              </div>
              <div class="export-group">
                <div class="export-group__label">One card per page</div>
                <div class="export-group__row">
                  <a href="{{ url_for('generate', format='event') }}" class="btn btn--ghost btn--sm">Event</a>
                  <a href="{{ url_for('generate', format='conference') }}" class="btn btn--ghost btn--sm">CR80</a>
                </div>
              </div>
            </div>
          </details>
        {% endif %}

        <ul class="glist">
          {% if not guests %}
            <li class="glist__empty">No guests yet — add your first one to get started.</li>
          {% else %}
            {% for g in guests|reverse %}
              <li class="grow">
                {% if g.photo %}
                  <img src="{{ url_for('photo', filename=g.photo) }}" class="grow__photo" alt="">
                {% else %}
                  {% set parts = g.name.strip().split() %}
                  <div class="grow__photo" dir="auto">{% if parts|length >= 2 %}{{ parts[0][:1] }}{{ parts[1][:1] }}{% elif g.name.strip()|length >= 2 %}{{ g.name.strip()[:2] }}{% else %}{{ g.name.strip()[:1] if g.name.strip() else '?' }}{% endif %}</div>
                {% endif %}
                <div class="grow__info">
                  <div class="grow__name" dir="auto">{{ g.name }}{% if g.checked_in %}<span class="badge badge--ok">CHECKED IN</span>{% endif %}</div>
                  <div class="grow__meta" dir="auto">{{ g.ticket_type }} · {{ g.role }} · +{{ g.companions }} · <span class="grow__code" dir="ltr">{{ g.id }}</span></div>
                </div>
                <div class="grow__actions">
                  <a href="{{ url_for('preview', code=g.id) }}" target="_blank" class="btn btn--ghost btn--sm">Preview</a>
                  <a href="{{ url_for('preview', code=g.id, format='conference') }}" target="_blank" class="btn btn--ghost btn--sm" title="CR80 conference size">CR80</a>
                  <form action="{{ url_for('delete', code=g.id) }}" method="post">
                    <button type="submit" class="btn btn--danger btn--sm" onclick='return confirm({{ ("Delete " ~ g.name ~ "?")|tojson }})'>Delete</button>
                  </form>
                </div>
              </li>
            {% endfor %}
          {% endif %}
        </ul>
      </section>

    </div>
  </main>
</body>
</html>
"""

VERIFY_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0F4C5C">
  <title>Door Verification</title>
  <style>
    :root {
      --primary: #0F4C5C;
      --primary-hover: #155F73;
      --accent: #C9A14A;
      --bg: #F7F8FA;
      --surface: #FFFFFF;
      --text: #1F2937;
      --muted: #6B7280;
      --border: #E5E7EB;
      --radius: 12px;
      --radius-sm: 8px;
      --tap: 48px;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", system-ui, sans-serif;
      font-size: 15px; line-height: 1.5; color: var(--text);
      background: var(--primary);
      min-height: 100vh; min-height: 100dvh;
      -webkit-font-smoothing: antialiased;
    }
    .wrap {
      max-width: 480px; margin: 0 auto;
      padding: 24px 16px calc(24px + env(safe-area-inset-bottom));
    }
    h1 {
      color: white; text-align: center; font-size: 22px;
      font-weight: 600; margin: 0 0 20px;
    }
    .card {
      background: var(--surface); border-radius: var(--radius); padding: 22px;
    }
    label {
      display: block; font-size: 11px; font-weight: 700; color: var(--muted);
      margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em;
    }
    .code-input {
      width: 100%; padding: 14px 14px; font-size: 18px;
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      letter-spacing: 0.04em; border: 1px solid var(--border);
      border-radius: var(--radius-sm); background: var(--surface); color: var(--text);
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    .code-input:focus {
      outline: none; border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(15,76,92,0.12);
    }
    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      padding: 0 18px; min-height: var(--tap); font: inherit;
      font-weight: 600; font-size: 15px; border: 1px solid transparent;
      border-radius: var(--radius-sm); cursor: pointer; text-decoration: none;
      transition: background-color 0.15s, border-color 0.15s;
    }
    .btn--block { width: 100%; }
    .btn--primary { background: var(--primary); color: white; }
    .btn--primary:hover { background: var(--primary-hover); }
    .btn--ghost {
      background: var(--surface); color: var(--primary); border-color: var(--border);
    }
    .btn--ghost:hover { background: var(--bg); }
    .gap { margin-top: 10px; }
    .result {
      margin-top: 18px; padding: 22px 18px; border-radius: var(--radius);
      text-align: center; border: 2px solid transparent;
    }
    .result--ok { background: #ECFDF5; border-color: #10B981; }
    .result--warn { background: #FFFBEB; border-color: #F59E0B; }
    .result--fail { background: #FEF2F2; border-color: #EF4444; }
    .result__badge {
      display: inline-block; padding: 7px 16px; border-radius: 100px;
      font-weight: 700; font-size: 13px; letter-spacing: 0.04em; color: white;
    }
    .result--ok .result__badge { background: #047857; }
    .result--warn .result__badge { background: #B45309; }
    .result--fail .result__badge { background: #B91C1C; }
    .result__photo {
      width: 120px; height: 120px; border-radius: 50%; object-fit: cover;
      margin: 16px auto 0; display: block; border: 4px solid white;
      box-shadow: 0 2px 8px rgba(0,0,0,0.12);
    }
    .result__name {
      font-size: 22px; font-weight: 700; color: var(--primary);
      margin-top: 12px; unicode-bidi: plaintext;
    }
    .result__role {
      font-size: 14px; color: var(--muted); margin-top: 4px; unicode-bidi: plaintext;
    }
    .result__ts {
      font-size: 12px; color: var(--muted); margin-top: 10px;
      font-family: ui-monospace, monospace;
    }
    .back-link {
      display: block; text-align: center; margin-top: 18px;
      color: rgba(255,255,255,0.85); text-decoration: none; font-size: 14px;
    }
    .back-link:hover { color: white; }
    #reader-wrap { margin-top: 14px; }
    #reader { width: 100%; border-radius: var(--radius-sm); overflow: hidden; }
    code {
      font-family: ui-monospace, monospace; background: rgba(0,0,0,0.04);
      padding: 1px 5px; border-radius: 3px; font-size: 13px;
    }
  </style>
  <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
</head>
<body>
  <div class="wrap">
    <h1>Door Verification</h1>
    <div class="card">
      <form method="post" autocomplete="off" id="verify-form">
        <label for="code-input">Guest code</label>
        <input type="text" name="code" id="code-input" class="code-input"
               placeholder="Scan or type code…" dir="ltr" autocomplete="off" autofocus>
        <button type="submit" class="btn btn--primary btn--block gap">Verify</button>
      </form>
      <button type="button" id="scan-btn" class="btn btn--ghost btn--block gap">Scan with camera</button>
      <div id="reader-wrap" style="display:none;">
        <div id="reader"></div>
        <button type="button" id="stop-btn" class="btn btn--ghost btn--block gap">Cancel</button>
      </div>
      {% if result %}
        {% if result.ok and result.already_checked_in %}
          <div class="result result--warn">
            <div class="result__badge">⚠ ALREADY CHECKED IN</div>
            {% if result.guest.photo %}<img class="result__photo" src="{{ url_for('photo', filename=result.guest.photo) }}">{% endif %}
            <div class="result__name" dir="auto">{{ result.guest.name }}</div>
            <div class="result__role" dir="auto">{{ result.guest.ticket_type }} · {{ result.guest.role }}</div>
            <div class="result__ts">Entered at {{ result.guest.checked_in_at }}</div>
          </div>
        {% elif result.ok %}
          <div class="result result--ok">
            <div class="result__badge">✓ VERIFIED · WELCOME</div>
            {% if result.guest.photo %}<img class="result__photo" src="{{ url_for('photo', filename=result.guest.photo) }}">{% endif %}
            <div class="result__name" dir="auto">{{ result.guest.name }}</div>
            <div class="result__role" dir="auto">{{ result.guest.ticket_type }} · {{ result.guest.role }}</div>
            <div class="result__role" dir="ltr">+{{ result.guest.companions }} {% if result.guest.companions == 1 %}Companion{% else %}Companions{% endif %}</div>
          </div>
        {% else %}
          <div class="result result--fail">
            <div class="result__badge">✗ INVALID CODE</div>
            <p>No guest found for <code dir="ltr">{{ result.code }}</code></p>
          </div>
        {% endif %}
      {% endif %}
    </div>
    <a href="{{ url_for('index') }}" class="back-link">← Manage guests</a>
  </div>
  <script>
    (function () {
      const scanBtn = document.getElementById('scan-btn');
      const stopBtn = document.getElementById('stop-btn');
      const wrap = document.getElementById('reader-wrap');
      const input = document.getElementById('code-input');
      const form = document.getElementById('verify-form');
      let scanner = null;

      function stopScanner() {
        if (scanner) {
          scanner.stop().then(() => scanner.clear()).catch(() => {});
          scanner = null;
        }
        wrap.style.display = 'none';
        scanBtn.style.display = '';
      }

      scanBtn.addEventListener('click', async () => {
        if (!window.Html5Qrcode) {
          alert('Scanner library failed to load. Check internet.');
          return;
        }
        if (!window.isSecureContext) {
          alert('Camera blocked: this page must be served over HTTPS (or via localhost) for the browser to grant camera access.');
          return;
        }
        scanBtn.style.display = 'none';
        wrap.style.display = 'block';
        scanner = new Html5Qrcode('reader');
        const config = {
          fps: 10,
          qrbox: { width: 280, height: 140 },
          formatsToSupport: [
            Html5QrcodeSupportedFormats.CODE_128,
            Html5QrcodeSupportedFormats.QR_CODE
          ]
        };
        try {
          await scanner.start({ facingMode: 'environment' }, config, (text) => {
            input.value = text.trim().toUpperCase();
            stopScanner();
            form.submit();
          }, () => { /* per-frame failures: ignore */ });
        } catch (err) {
          alert('Could not start camera: ' + err);
          stopScanner();
        }
      });

      stopBtn.addEventListener('click', stopScanner);
    })();
  </script>
</body>
</html>
"""

# ----------------- Flask routes -----------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB photo upload cap

@app.route("/")
def index():
    return render_template_string(INDEX_HTML, guests=load_guests(), event=EVENT)

@app.route("/add", methods=["POST"])
def add():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("index"))

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
    return redirect(url_for("index"))

@app.route("/delete/<code>", methods=["POST"])
def delete(code):
    guests = [g for g in load_guests() if g["id"] != code]
    save_guests(guests)
    return redirect(url_for("index"))

@app.route("/photo/<filename>")
def photo(filename):
    return send_from_directory(PHOTOS_DIR, filename)

@app.route("/preview/<code>")
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

@app.route("/generate")
def generate():
    guests = load_guests()
    if not guests:
        return redirect(url_for("index"))
    fmt = normalize_card_format(request.args.get("format"))
    cards = [render_card(g, fmt).convert("RGB") for g in guests]
    buf = io.BytesIO()
    if len(cards) == 1:
        cards[0].save(buf, format="PDF", resolution=300)
    else:
        cards[0].save(buf, format="PDF", save_all=True,
                      append_images=cards[1:], resolution=300)
    buf.seek(0)
    suffix = "-cr80" if fmt == "conference" else ""
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"guest-cards-{EVENT['date_code']}{suffix}.pdf")


@app.route("/generate/print-sheets")
def generate_print_sheets():
    guests = load_guests()
    if not guests:
        return redirect(url_for("index"))
    paper = request.args.get("paper", "a4").strip().lower()
    if paper not in ("a4", "letter"):
        paper = "a4"
    fmt = normalize_card_format(request.args.get("format"))
    buf = build_print_sheets_pdf(guests, paper=paper, card_format=fmt)
    suffix = "a4" if paper == "a4" else "letter"
    cr = "-cr80" if fmt == "conference" else ""
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"guest-cards-print-sheets-{EVENT['date_code']}-{suffix}{cr}.pdf",
    )

@app.route("/verify", methods=["GET", "POST"])
def verify():
    result = None
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        guest = get_guest(code)
        if not guest:
            result = {"ok": False, "code": code}
        else:
            already = bool(guest.get("checked_in"))
            if not already:
                guests = load_guests()
                for g in guests:
                    if g["id"] == code:
                        g["checked_in"] = True
                        g["checked_in_at"] = datetime.now().isoformat(timespec="seconds")
                        guest = g
                        break
                save_guests(guests)
            result = {"ok": True, "guest": guest, "already_checked_in": already}
    return render_template_string(VERIFY_HTML, result=result, event=EVENT)

# ----------------- Main -----------------

if __name__ == "__main__":
    port = 5151
    print("\n✨ Sudanese Forum — Guest Card Generator")
    print(f"   Open: http://127.0.0.1:{port}")
    print("   (localhost-only; not reachable from other devices on your network)\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
