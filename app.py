"""Event Cards System — Flask entry point.

The application is now organized as a Python package under `event_cards/`.
This file is a thin shim so existing entry points (``python app.py`` for
local dev, ``gunicorn app:app`` for the systemd unit on the droplet) keep
working unchanged.
"""

from event_cards import create_app

app = create_app()


if __name__ == "__main__":
    port = 5151
    print("\n✨ Event Cards — Guest Card Generator")
    print(f"   Open: http://127.0.0.1:{port}")
    print("   (localhost-only; not reachable from other devices on your network)\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
