import math
import sqlite3
from datetime import datetime
from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for


class Invalid(ValueError):
    pass


def db():
    if "connection" not in g:
        con = sqlite3.connect(current_app.config["DATABASE"], isolation_level=None, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        g.connection = con
    return g.connection


def rows(sql, args=()):
    return db().execute(sql, args).fetchall()


def one(sql, args=()):
    return db().execute(sql, args).fetchone()


def get(table, key):
    # Table names are constants supplied by the controllers.
    return one(f"SELECT * FROM {table} WHERE id=?", (key,)) or abort(404)


def now():
    return current_app.config.get("CLOCK", datetime.now)().strftime("%Y-%m-%dT%H:%M")


def schedule_date(value):
    return datetime.fromisoformat(value).strftime("%a, %d %b %Y")


def when(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M").strftime("%d %b %Y · %H:%M")


def phase(e):
    t = now()
    if e["archived"] or e["course_archived"]:
        return "Archived"
    if e["completed"]:
        return "Completed"
    if e["course_status"] != "Active":
        return "Closed"
    if e["creation_enabled"] and e["creation_start"] <= t < e["creation_end"]:
        return "Slot Creation"
    if e["booking_enabled"] and e["booking_start"] <= t < e["booking_end"]:
        return "Booking Open"
    if not e["released"] and t < e["booking_end"]:
        return "Draft"
    return "Closed"


def slot_status(s):
    if s["cancelled"]:
        return "Cancelled"
    if s["end"] <= now():
        return "Completed"
    return "Full" if s["seats"] == 0 else "Available"


def require(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for("auth.login"))
            if g.user["role"] not in roles or g.user["status"] != "Active":
                abort(403)
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def check(condition, message):
    if not condition:
        raise Invalid(message)


def field(name, label=None, required=True, limit=250):
    value = request.form.get(name, "").strip()
    check(
        (value or not required) and len(value) <= limit,
        f"Please check {label or name.replace('_', ' ')}.",
    )
    return value


def integer(name, maximum=1000000):
    value = field(name)
    check(
        value.isascii() and value.isdigit() and len(value) <= 9 and 1 <= int(value) <= maximum,
        f"Enter a positive whole number for {name.replace('_', ' ')} (up to {maximum}).",
    )
    return int(value)


def timestamp(name):
    try:
        return datetime.strptime(field(name), "%Y-%m-%dT%H:%M").isoformat(timespec="minutes")
    except ValueError:
        raise Invalid("Enter a valid local date and time.") from None


def mark(name, maximum):
    try:
        value = float(field(name))
    except ValueError:
        raise Invalid("Enter a numeric score for each criterion.") from None
    check(math.isfinite(value) and 0 <= value <= maximum, "A score is outside its criterion's range.")
    return value


def record(booking, message):
    db().execute(
        "INSERT INTO events(booking_id,at,actor_id,detail) VALUES(?,?,?,?)",
        (booking, now(), g.user["id"], message),
    )
