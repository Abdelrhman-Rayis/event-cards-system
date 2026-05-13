"""Card image composition: header, body, QR footer."""

from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageOps

from ..config import (
    BG_CREAM,
    BG_HEADER_BORDER,
    CARD_H,
    CARD_W,
    COLOR_DARK,
    COLOR_DIVIDER,
    COLOR_GOLD,
    COLOR_GRAY,
    COLOR_TEXT,
    CONFERENCE_CARD_H,
    CONFERENCE_CARD_W,
    EVENT,
    PHOTOS_DIR,
    normalize_card_format,
)
from ..models import companions_label
from .fonts import (
    ar_font,
    ar_shape,
    display_bidi,
    fit_text_for_width,
    font,
    initials_from_name,
    mono_font,
    text_font,
)

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass


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


# ----------------- Icon drawing (no emoji-font dependency) -----------------


def draw_pin(d, x, y, s, color):
    d.ellipse([x + s * 0.10, y, x + s * 0.90, y + s * 0.78], outline=color, width=2)
    d.polygon(
        [
            (x + s * 0.30, y + s * 0.55),
            (x + s * 0.70, y + s * 0.55),
            (x + s * 0.50, y + s * 0.98),
        ],
        fill=color,
    )
    d.ellipse(
        [x + s * 0.36, y + s * 0.22, x + s * 0.64, y + s * 0.50], fill=color
    )


def draw_lock(d, x, y, s, color):
    d.arc([x + s * 0.20, y, x + s * 0.80, y + s * 0.55], 180, 360, fill=color, width=3)
    d.rounded_rectangle(
        [x + s * 0.10, y + s * 0.40, x + s * 0.90, y + s * 0.95],
        radius=int(s * 0.08),
        fill=color,
    )


# ----------------- Logo caching -----------------

# Only cache successful loads — never cache "missing file" or the logo never
# appears until process restart.
_logo_cache_mtime = None
_logo_cache_image = None


def _resolve_logo_path():
    """First existing logo file wins (absolute paths)."""
    from ..config import STATIC_DIR

    for name in ("logo.png", "logo.jpg", "logo.webp"):
        p = STATIC_DIR / name
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
    if lg.mode == "RGBA":
        rgb = Image.merge("RGB", lg.split()[:3])
        alpha = lg.split()[3]
        card.paste(rgb, (lx, ly), alpha)
    else:
        card.paste(lg, (lx, ly))
    return lx + lg.width + 28


# ----------------- Header -----------------


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
        draw.text(
            (CARD_W - 100 - w, 60 + i * 105), txt, font=ar_title_font, fill=COLOR_DARK
        )

    # Event info strip (location only for now)
    info_strip_h = 100
    draw.rectangle([0, top_h, CARD_W, top_h + info_strip_h], fill=BG_CREAM)
    draw.line(
        [(0, top_h + info_strip_h), (CARD_W, top_h + info_strip_h)],
        fill=BG_HEADER_BORDER,
        width=2,
    )

    info_y = top_h + (info_strip_h - 44) // 2
    info_font_obj = font(44)
    text = EVENT["location"]
    text_w = int(draw.textlength(text, font=info_font_obj))
    item_w = 44 + 14 + text_w
    x = (CARD_W - item_w) // 2
    draw_pin(draw, x, info_y, 44, COLOR_DARK)
    draw.text(
        (x + 44 + 14, info_y + 2), text, font=info_font_obj, fill=COLOR_TEXT
    )

    return top_h + info_strip_h


# ----------------- Full card -----------------


def render_card(guest, card_format="event"):
    card = Image.new("RGB", (CARD_W, CARD_H), "white")
    header_h = render_header(card)
    draw = ImageDraw.Draw(card)

    # ---------- BODY ----------
    body_top = header_h + 30
    photo_size = 440
    photo_x = 110
    photo_y = body_top + 20

    draw.rectangle(
        [photo_x, photo_y, photo_x + photo_size, photo_y + photo_size],
        fill=(235, 235, 235),
    )

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
        draw.text(
            (
                photo_x + (photo_size - tw) // 2 - bbox[0],
                photo_y + (photo_size - th) // 2 - bbox[1] - 10,
            ),
            initials,
            font=ifont,
            fill=(170, 170, 170),
        )

    # VERIFIED badge
    badge_w, badge_h = 200, 56
    bx = photo_x + (photo_size - badge_w) // 2
    by = photo_y + photo_size - badge_h - 16
    draw.rounded_rectangle(
        [bx, by, bx + badge_w, by + badge_h], radius=6, fill=COLOR_GOLD
    )
    bfont = font(30, bold=True)
    bw = draw.textlength("VERIFIED", font=bfont)
    draw.text(
        (bx + (badge_w - bw) // 2, by + 11), "VERIFIED", font=bfont, fill="white"
    )

    # Right-side info column
    info_x = photo_x + photo_size + 90

    draw.text((info_x, photo_y + 10), "GUEST NAME", font=font(36), fill=COLOR_GRAY)
    nm = guest.get("name", "") or ""
    name_max_w = float(CARD_W - info_x - 90)
    name_f, name_disp, _ = fit_text_for_width(
        draw, nm, name_max_w, 124, True, min_size=64
    )
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
        val_f, val_disp, _ = fit_text_for_width(
            draw, val, col_text_max_w, 60, True, min_size=32
        )
        draw.text((cx, col_value_y), val_disp, font=val_f, fill=COLOR_TEXT)

    # Secured line
    sec_y = col_value_y + 110
    draw.ellipse(
        [info_x, sec_y + 8, info_x + 16, sec_y + 24], fill=COLOR_DARK
    )
    draw.text(
        (info_x + 28, sec_y),
        "SECURED  ·  HOLOGRAPHIC SEAL  ·  TAMPER-PROOF",
        font=font(30),
        fill=COLOR_GRAY,
    )

    # ---------- DASHED DIVIDER ----------
    div_y = photo_y + photo_size + 60
    dx = 90
    while dx < CARD_W - 90:
        draw.line([(dx, div_y), (dx + 24, div_y)], fill=COLOR_DIVIDER, width=3)
        dx += 40

    # ---------- FOOTER ----------
    footer_y = div_y + 40

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(guest["id"])
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_size = 360
    qr_x = 110
    qr_y = footer_y
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    card.paste(qr_img, (qr_x, qr_y))
    draw.rectangle(
        [qr_x - 3, qr_y - 3, qr_x + qr_size + 2, qr_y + qr_size + 2],
        outline=COLOR_DIVIDER,
        width=2,
    )

    # Right-of-QR column
    dv_x = qr_x + qr_size + 70
    dv_top = qr_y + 6

    draw.text((dv_x, dv_top), "TICKET ID", font=font(28), fill=COLOR_GRAY)
    serial_font = mono_font(46, bold=True)
    draw.text((dv_x, dv_top + 40), guest["id"], font=serial_font, fill=COLOR_DARK)

    dv_header_y = dv_top + 140
    draw_lock(draw, dv_x, dv_header_y + 6, 52, COLOR_DARK)
    draw.text(
        (dv_x + 70, dv_header_y),
        "DOOR VERIFICATION",
        font=font(44, bold=True),
        fill=COLOR_DARK,
    )

    underline_y = dv_header_y + 72
    draw.rectangle(
        [dv_x, underline_y, dv_x + 80, underline_y + 4], fill=COLOR_GOLD
    )

    draw.text(
        (dv_x, dv_header_y + 96),
        "Scan this code at entry.",
        font=font(34),
        fill=COLOR_TEXT,
    )
    draw.text(
        (dv_x, dv_header_y + 146),
        "Valid for one entry only.",
        font=font(34),
        fill=COLOR_TEXT,
    )

    # Issuer line at the bottom-right
    issuer_text = "Sudanese Forum · 16 May 2026"
    issuer_font = font(24)
    iw = draw.textlength(issuer_text, font=issuer_font)
    draw.text(
        (CARD_W - iw - 90, qr_y + qr_size - 24),
        issuer_text,
        font=issuer_font,
        fill=COLOR_GRAY,
    )

    return finalize_card_for_format(card, card_format)
