"""Card image composition driven by the live event.json config.

Header, info columns and issuer line all read from ``config.CONFIG`` so
that retitling the event or reordering fields in event.json immediately
shows up on the next render (the wizard mutates CONFIG in place).
"""

import qrcode
from PIL import Image, ImageDraw, ImageOps

from .. import config
from ..config import (
    CARD_H,
    CARD_W,
    CONFERENCE_CARD_H,
    CONFERENCE_CARD_W,
    PHOTOS_DIR,
    normalize_card_format,
)
from ..models import companions_label
from .fonts import (
    ar_shape,
    display_bidi,
    fit_text_for_width,
    font,
    has_arabic,
    mono_font,
    text_font,
)
from .themes import color

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


# ----------------- Icons -----------------


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
    d.ellipse([x + s * 0.36, y + s * 0.22, x + s * 0.64, y + s * 0.50], fill=color)


def draw_lock(d, x, y, s, color):
    d.arc([x + s * 0.20, y, x + s * 0.80, y + s * 0.55], 180, 360, fill=color, width=3)
    d.rounded_rectangle(
        [x + s * 0.10, y + s * 0.40, x + s * 0.90, y + s * 0.95],
        radius=int(s * 0.08),
        fill=color,
    )


# ----------------- Logo caching -----------------

_logo_cache_mtime = None
_logo_cache_image = None
_logo2_cache_mtime = None
_logo2_cache_image = None
_avatar_cache_key = None
_avatar_cache_image = None


def _resolve_logo_path(base="logo"):
    from ..config import STATIC_DIR

    for ext in (".png", ".jpg", ".webp"):
        p = STATIC_DIR / f"{base}{ext}"
        if p.is_file():
            return p
    return None


def _header_logo_image():
    global _logo_cache_mtime, _logo_cache_image
    path = _resolve_logo_path("logo")
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


def _footer_logo_image():
    """Optional secondary logo, sized for the bottom-right footer area."""
    global _logo2_cache_mtime, _logo2_cache_image
    path = _resolve_logo_path("logo2")
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _logo2_cache_image is not None and _logo2_cache_mtime == mtime:
        return _logo2_cache_image
    try:
        im = Image.open(path).convert("RGBA")
        max_w, max_h = 280, 220
        sc = min(1.0, max_w / max(im.width, 1), max_h / max(im.height, 1))
        nw = max(1, int(im.width * sc))
        nh = max(1, int(im.height * sc))
        resized = im.resize((nw, nh), Image.LANCZOS)
        _logo2_cache_image = resized
        _logo2_cache_mtime = mtime
        return resized
    except (OSError, ValueError):
        return None


def _default_avatar_image(size):
    """Uploaded default-guest photo, cropped square to the photo box. None if absent."""
    global _avatar_cache_key, _avatar_cache_image
    path = _resolve_logo_path("default_avatar")
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (mtime, size)
    if _avatar_cache_image is not None and _avatar_cache_key == key:
        return _avatar_cache_image
    try:
        im = Image.open(path).convert("RGB")
        im = ImageOps.exif_transpose(im)
        im = ImageOps.fit(im, (size, size), Image.LANCZOS)
        _avatar_cache_image = im
        _avatar_cache_key = key
        return im
    except (OSError, ValueError):
        return None


def _draw_silhouette(draw, x, y, size, fill):
    """Gender-neutral guest silhouette (head + shoulders) inscribed in a size×size box."""
    cx = x + size // 2
    head_r = int(size * 0.18)
    head_cy = y + int(size * 0.30)
    draw.ellipse(
        [cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r],
        fill=fill,
    )
    body_w = int(size * 0.62)
    body_h = int(size * 0.55)
    body_top = head_cy + int(head_r * 0.85)
    body_left = cx - body_w // 2
    body_right = cx + body_w // 2
    body_bottom = body_top + body_h
    draw.rounded_rectangle(
        [body_left, body_top, body_right, body_bottom],
        radius=int(size * 0.22),
        fill=fill,
    )


def _paste_header_logo(card):
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
    """Cream strip with optional bilingual title, then a thin info row."""
    cfg = config.CONFIG
    title_primary = (cfg.get("title_primary") or "").strip()
    title_secondary = (cfg.get("title_secondary") or "").strip()
    title_primary_ar = (cfg.get("title_primary_ar") or "").strip()
    title_secondary_ar = (cfg.get("title_secondary_ar") or "").strip()

    top_h = 290
    header_bg = color("header_bg")
    primary = color("primary")
    text_color = color("text")
    draw = ImageDraw.Draw(card)
    draw.rectangle([0, 0, CARD_W, top_h], fill=header_bg)

    en_x = _paste_header_logo(card)
    draw = ImageDraw.Draw(card)

    if title_primary or title_secondary:
        f = text_font(86, True, title_primary or title_secondary)
        if title_primary:
            draw.text(
                (en_x, 60), display_bidi(title_primary), font=f, fill=primary
            )
        if title_secondary:
            draw.text(
                (en_x, 165), display_bidi(title_secondary), font=f, fill=primary
            )

    if title_primary_ar or title_secondary_ar:
        ar_f = text_font(88, True, title_primary_ar or title_secondary_ar)
        for i, line in enumerate([title_primary_ar, title_secondary_ar]):
            if not line:
                continue
            txt = ar_shape(line) if has_arabic(line) else line
            w = draw.textlength(txt, font=ar_f)
            draw.text(
                (CARD_W - 100 - w, 60 + i * 105), txt, font=ar_f, fill=primary
            )

    # Info strip
    info_strip_h = 100
    draw.rectangle([0, top_h, CARD_W, top_h + info_strip_h], fill=header_bg)
    draw.line(
        [(0, top_h + info_strip_h), (CARD_W, top_h + info_strip_h)],
        fill=color("header_border"),
        width=2,
    )

    info_y = top_h + (info_strip_h - 44) // 2
    info_font_obj = text_font(44, False, cfg.get("location", ""))
    location_text = display_bidi(cfg.get("location", ""))
    text_w = int(draw.textlength(location_text, font=info_font_obj))
    item_w = 44 + 14 + text_w
    x = (CARD_W - item_w) // 2
    draw_pin(draw, x, info_y, 44, primary)
    draw.text(
        (x + 44 + 14, info_y + 2), location_text, font=info_font_obj, fill=text_color
    )

    return top_h + info_strip_h


# ----------------- Field value formatting -----------------


def _card_columns(cfg):
    """Fields to render as info columns. Excludes implicit name/photo fields."""
    implicit = {"name", "photo"}
    cols = []
    for f in cfg.get("fields", []):
        if not f.get("show_on_card", False):
            continue
        if f.get("id") in implicit:
            continue
        cols.append(f)
    return cols[:3]


def _format_field_value(field, value):
    """Render a stored value into a string suitable for the card."""
    if value is None:
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


# ----------------- Full card -----------------


def render_card(guest, card_format="event"):
    cfg = config.CONFIG
    primary = color("primary")
    text_color = color("text")
    muted = color("muted")
    accent = color("accent")
    divider = color("divider")

    card = Image.new("RGB", (CARD_W, CARD_H), color("card_bg"))
    header_h = render_header(card)
    draw = ImageDraw.Draw(card)

    # ---------- BODY ----------
    body_top = header_h + 30
    photo_size = 440
    photo_x = 110
    photo_y = body_top + 20

    draw.rectangle(
        [photo_x, photo_y, photo_x + photo_size, photo_y + photo_size],
        fill=color("photo_placeholder_bg"),
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
        avatar = _default_avatar_image(photo_size)
        if avatar is not None:
            card.paste(avatar, (photo_x, photo_y))
        else:
            _draw_silhouette(
                draw,
                photo_x,
                photo_y,
                photo_size,
                color("photo_placeholder_text"),
            )

    # VERIFIED badge
    badge_w, badge_h = 200, 56
    bx = photo_x + (photo_size - badge_w) // 2
    by = photo_y + photo_size - badge_h - 16
    draw.rounded_rectangle(
        [bx, by, bx + badge_w, by + badge_h], radius=6, fill=accent
    )
    bfont = font(30, bold=True)
    bw = draw.textlength("VERIFIED", font=bfont)
    draw.text(
        (bx + (badge_w - bw) // 2, by + 11), "VERIFIED", font=bfont, fill="white"
    )

    # Right-side info column
    info_x = photo_x + photo_size + 90

    draw.text((info_x, photo_y + 10), "GUEST NAME", font=font(36), fill=muted)
    nm = guest.get("name", "") or ""
    name_max_w = float(CARD_W - info_x - 90)
    name_f, name_disp, _ = fit_text_for_width(
        draw, nm, name_max_w, 124, True, min_size=64
    )
    draw.text((info_x, photo_y + 64), name_disp, font=name_f, fill=primary)

    # Info columns driven by event.json fields list
    columns = _card_columns(cfg)
    col_label_y = photo_y + 268
    col_value_y = photo_y + 318
    n_cols = max(1, len(columns) or 1)
    col_w = (CARD_W - info_x - 100) // 3  # keep 3-column grid for spacing parity
    col_text_max_w = float(col_w - 24)
    for i, field in enumerate(columns):
        cx = info_x + i * col_w
        draw.text(
            (cx, col_label_y),
            field.get("label", field.get("id", "")).upper(),
            font=font(36),
            fill=muted,
        )
        raw = guest.get(field["id"], field.get("default", ""))
        val_str = _format_field_value(field, raw)
        val_f, val_disp, _ = fit_text_for_width(
            draw, val_str, col_text_max_w, 60, True, min_size=32
        )
        draw.text((cx, col_value_y), val_disp, font=val_f, fill=text_color)

    # Secured line
    sec_y = col_value_y + 110
    draw.ellipse([info_x, sec_y + 8, info_x + 16, sec_y + 24], fill=primary)
    draw.text(
        (info_x + 28, sec_y),
        "SECURED  ·  HOLOGRAPHIC SEAL  ·  TAMPER-PROOF",
        font=font(30),
        fill=muted,
    )

    # ---------- DASHED DIVIDER ----------
    div_y = photo_y + photo_size + 60
    dx = 90
    while dx < CARD_W - 90:
        draw.line([(dx, div_y), (dx + 24, div_y)], fill=divider, width=3)
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
        outline=divider,
        width=2,
    )

    dv_x = qr_x + qr_size + 70
    dv_top = qr_y + 6

    draw.text((dv_x, dv_top), "TICKET ID", font=font(28), fill=muted)
    serial_font = mono_font(46, bold=True)
    draw.text((dv_x, dv_top + 40), guest["id"], font=serial_font, fill=primary)

    dv_header_y = dv_top + 140
    draw_lock(draw, dv_x, dv_header_y + 6, 52, primary)
    draw.text(
        (dv_x + 70, dv_header_y),
        "DOOR VERIFICATION",
        font=font(44, bold=True),
        fill=primary,
    )

    underline_y = dv_header_y + 72
    draw.rectangle([dv_x, underline_y, dv_x + 80, underline_y + 4], fill=accent)

    draw.text(
        (dv_x, dv_header_y + 96),
        "Scan this code at entry.",
        font=font(34),
        fill=text_color,
    )
    draw.text(
        (dv_x, dv_header_y + 146),
        "Valid for one entry only.",
        font=font(34),
        fill=text_color,
    )

    # Optional footer logo in the bottom-right
    fl = _footer_logo_image()
    if fl is not None:
        right_margin = 90
        bottom_margin = 60  # leave room for the issuer line below
        fx = CARD_W - right_margin - fl.width
        fy = qr_y + qr_size - bottom_margin - fl.height
        if fl.mode == "RGBA":
            rgb = Image.merge("RGB", fl.split()[:3])
            alpha = fl.split()[3]
            card.paste(rgb, (fx, fy), alpha)
        else:
            card.paste(fl, (fx, fy))

    # Issuer line from event config
    issuer_bits = [
        s for s in (cfg.get("title_primary", ""), cfg.get("date", "")) if s.strip()
    ]
    if issuer_bits:
        issuer_text = " · ".join(issuer_bits)
        issuer_font = text_font(24, False, issuer_text)
        iw = draw.textlength(display_bidi(issuer_text), font=issuer_font)
        draw.text(
            (CARD_W - iw - 90, qr_y + qr_size - 24),
            display_bidi(issuer_text),
            font=issuer_font,
            fill=muted,
        )

    return finalize_card_for_format(card, card_format)
