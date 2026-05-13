"""Print-sheet PDF: multiple cards per page, dashed cut guides."""

import io

from PIL import Image, ImageDraw

from ..config import card_layout_pixels, normalize_card_format
from .card import render_card

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
