"""Door verification: scan/enter code, mark check-in."""

from datetime import datetime

from flask import Blueprint, render_template, request

from ..config import EVENT
from ..models import get_guest, load_guests, save_guests

verify_bp = Blueprint("verify", __name__)


@verify_bp.route("/verify", methods=["GET", "POST"])
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
                        g["checked_in_at"] = datetime.now().isoformat(
                            timespec="seconds"
                        )
                        guest = g
                        break
                save_guests(guests)
            result = {"ok": True, "guest": guest, "already_checked_in": already}
    return render_template("verify.html", result=result, event=EVENT)
