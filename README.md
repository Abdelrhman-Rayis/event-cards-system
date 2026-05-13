# Event Cards System (ECS)

Bilingual (Arabic / English) Flask app for generating event guest cards with scannable Code 128 barcodes and a door-verification flow. Built for the **Sudanese Forum for the Homeland** (Manchester, May 2026).

## Features

- **Bilingual UI and card output** — Arabic and English side by side, with proper shaping (`arabic-reshaper`) and bidirectional layout (`python-bidi`).
- **Guest management** — add guests with photo, role, ticket type, and companion count from a single-page form.
- **PDF exports**
  - A4 or Letter print sheets, multiple cards per page with dashed cut lines
  - CR80 conference-badge size (3.375" × 2.125") or full event-card size
  - One card per page, or several cards per sheet
- **Code 128 barcodes** — every guest gets a unique `EVT-YYYYMMDD-XXXXX` code.
- **Door verification** — security scans the barcode (camera or USB scanner), sees the guest's photo and details; each code is single-use to prevent reuse.
- **Modern flat, mobile-first UI** — sticky header, 44 px tap targets, responsive layout.
- **Localhost-only by default** — the dev server binds to `127.0.0.1`, not your LAN.

## Quick start

```bash
git clone https://github.com/Abdelrhman-Rayis/event-cards-system.git
cd event-cards-system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5151.

## Customizing for your event

Event details are in the `EVENT` dict near the top of `app.py`:

```python
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
```

Swap the strings, drop your logo at `static/logo.png`, restart the server.

## Routes

| Path | Purpose |
|---|---|
| `/` | Manage guests, export options |
| `/preview/<code>?format=event\|conference` | Render a single card as PNG |
| `/generate?format=event\|conference` | One-card-per-page PDF |
| `/generate/print-sheets?paper=a4\|letter&format=event\|conference` | Multi-card print sheet PDF |
| `/verify` | Door verification (camera or manual entry) |
| `/photo/<filename>` | Serve uploaded guest photos |
| `/add`, `/delete/<code>` | Form endpoints |

## Tech stack

- **Flask** — single-file server
- **Pillow** — card rendering
- **python-barcode** — Code 128 generation
- **arabic-reshaper** + **python-bidi** — Arabic script handling
- **html5-qrcode** (CDN) — in-browser camera scanning

## Privacy

Guest data is stored locally in `guests.json` and `photos/`. **Both paths are gitignored** — they are never committed. Guests are PII; treat the file like a contact list.

## Project layout

```
app.py              Flask routes, card rendering, HTML templates
requirements.txt    Python dependencies
static/logo.png     Event logo (header of every card)
guests.json         (gitignored) per-event guest list
photos/             (gitignored) uploaded guest photos
output/             (gitignored) generated PDFs scratch dir
```
