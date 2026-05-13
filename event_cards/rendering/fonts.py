"""Font loading, Arabic shaping, and text-fitting helpers."""

import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import ImageFont

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
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
                ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
            ]
        else:
            cands = [
                ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
                ("/System/Library/Fonts/Helvetica.ttc", 0),
                ("/Library/Fonts/Arial.ttf", 0),
                ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
                ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 0),
            ]
        _FONT_CACHE[key] = _font_try(cands, size)
    return _FONT_CACHE[key]


def mono_font(size, bold=False):
    key = ("mono", size, bold)
    if key not in _FONT_CACHE:
        if bold:
            cands = [
                ("/System/Library/Fonts/Menlo.ttc", 1),
                ("/System/Library/Fonts/Monaco.dfont", 0),
                ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 0),
            ]
        else:
            cands = [
                ("/System/Library/Fonts/Menlo.ttc", 0),
                ("/System/Library/Fonts/Monaco.dfont", 0),
                ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
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
            (
                "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
                0,
            ),
            (
                "/opt/homebrew/share/fonts/noto/NotoNaskhArabic-Bold.ttf"
                if bold
                else "/opt/homebrew/share/fonts/noto/NotoNaskhArabic-Regular.ttf",
                0,
            ),
            ("/System/Library/Fonts/Helvetica.ttc", 0),
        ]
        chosen = None
        for path, idx in cands:
            if not Path(path).exists():
                continue
            chosen = _ar_truetype(path, size, index=idx)
            if chosen is not None:
                break
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
