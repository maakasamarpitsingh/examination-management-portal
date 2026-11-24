from datetime import datetime, timedelta
from flask import Blueprint, abort, g, render_template, request

from .admin import KINDS, saved
from .core import check, db, field, get, integer, mark, now, one, phase, record, require, rows, timestamp

bp = Blueprint("portal", __name__)
ALL = ("admin", "examiner", "student")


def identity():
    return g.user["role"], g.user["id"]


def exam_scope():
    role, uid = identity()
    if role == "examiner":
        return (
            "(id IN (SELECT exam_id FROM assignments WHERE examiner_id=?) OR id IN (SELECT exam_id FROM slots WHERE examiner_id=?) OR id IN (SELECT exam_id FROM booking_info WHERE examiner_id=?))",
            [uid, uid, uid],
        )
    if role == "student":
        return (
            "((released=1 AND archived=0 AND course_archived=0 AND course_status='Active') OR id IN (SELECT exam_id FROM bookings WHERE student_id=?))",
            [uid],
        )
    return "1=1", []


def exam_access(eid):
    clause, args = exam_scope()
    return one(f"SELECT * FROM exam_info WHERE id=? AND {clause}", (eid, *args)) or abort(404)


def booking_scope():
    role, uid = identity()
    if role == "examiner":
        return "examiner_id=?", [uid]
    if role == "student":
        return "student_id=?", [uid]
    return "1=1", []


def booking_access(bid):
    clause, args = booking_scope()
    return one(f"SELECT * FROM booking_info WHERE id=? AND {clause}", (bid, *args)) or abort(404)


@bp.get("/")
@require(*ALL)
def home():
    role, uid = identity()
    clause, args = exam_scope()
    exams = rows(f"SELECT * FROM exam_info WHERE {clause} ORDER BY booking_end DESC", args)
    clause, args = booking_scope()
    bookings = rows(f"SELECT * FROM booking_info WHERE {clause} ORDER BY start,id", args)
    upcoming = [b for b in bookings if b["status"] == "Booked" and b["end"] > now()]
    pending = [b for b in bookings if b["status"] == "Booked" and b["end"] <= now()]
    results = [b for b in bookings if b["published_at"]]
    schedule = []
    approval_count = 0
    if role == "admin":
        schedule = rows(
            """SELECT s.* FROM slot_info s JOIN exam_info e ON e.id=s.exam_id
               WHERE s.cancelled=0 AND s.end>? AND e.archived=0 AND e.completed=0
                 AND e.course_archived=0 AND e.course_status='Active'
               ORDER BY s.start,s.id LIMIT 6""",
            (now(),),
        )
        counts = [
            (label, one("SELECT count(*) n FROM " + table)["n"])
            for label, table in (
                ("Courses", "courses"),
                ("Examinations", "exams"),
                ("Examiners", "users WHERE role='examiner'"),
                ("Students", "users WHERE role='student'"),
                ("Slots", "slots"),
                ("Bookings", "bookings"),
            )
        ]
        approval_count = one("SELECT count(*) n FROM users WHERE role='examiner' AND status='Pending'")["n"]
        focus = rows("SELECT id,name,department FROM users WHERE role='examiner' AND status='Pending' ORDER BY id LIMIT 5")
    elif role == "examiner":
        focus = rows("SELECT * FROM slot_info WHERE examiner_id=? ORDER BY start DESC", (uid,))
        counts = [
            (
                "Assigned examinations",
                one("SELECT count(*) n FROM assignments WHERE examiner_id=?", (uid,))["n"],
            ),
            ("Created / assigned slots", len(focus)),
            ("Booked students", len({b["student_id"] for b in bookings if b["status"] != "Cancelled"})),
            ("Pending evaluations", len(pending)),
        ]
    else:
        available = {
            e["id"]
            for e in exams
            if phase(e) == "Booking Open"
            and not any(b["exam_id"] == e["id"] and b["status"] != "Cancelled" for b in bookings)
        }
        focus = [
            s
            for s in rows(
                "SELECT * FROM slot_info WHERE seats>0 AND cancelled=0 AND examiner_status='Active' AND start>? ORDER BY start",
                (now(),),
            )
            if s["exam_id"] in available
        ]
        counts = [
            ("Open examinations", len(available)),
            ("Available slots", len(focus)),
            ("Upcoming bookings", len(upcoming)),
            ("Published results", len(results)),
        ]
    return render_template(
        "home.html",
        counts=counts,
        schedule=schedule,
        approval_count=approval_count,
        exams=exams[:5],
        upcoming=upcoming[:6],
        pending=pending[:6],
        results=results[-5:][::-1],
        focus=focus[:5],
    )


@bp.get("/exams")
@require(*ALL)
def exams():
    clause, args = exam_scope()
    q = request.args.get("q", "").strip()
    kind = request.args.get("kind", "")
    items = rows(
        f"""SELECT * FROM exam_info WHERE {clause} AND
                (name LIKE ? OR code LIKE ? OR course_name LIKE ? OR CAST(id AS TEXT)=?)
                AND (?='' OR kind=?) ORDER BY archived,name""",
        (*args, f"%{q}%", f"%{q}%", f"%{q}%", q, kind, kind),
    )
    state = request.args.get("phase", "")
    return render_template(
        "exams.html", exams=[e for e in items if not state or phase(e) == state], kinds=KINDS
    )


@bp.get("/exams/<int:eid>")
@require(*ALL)
def exam(eid):
    e = exam_access(eid)
    role, uid = identity()
    slots = rows(
        "SELECT * FROM slot_info WHERE exam_id=? AND (?!='examiner' OR examiner_id=?) ORDER BY start",
        (eid, role, uid),
    )
    assigned = rows(
        "SELECT u.* FROM assignments a JOIN users u ON u.id=a.examiner_id WHERE exam_id=? ORDER BY name",
        (eid,),
    )
    return render_template(
        "exam.html",
        e=e,
        slots=slots,
        rubrics=rows("SELECT * FROM rubrics WHERE exam_id=? ORDER BY id", (eid,)),
        assigned=assigned,
        faculty=(
            rows("SELECT id,name FROM users WHERE role='examiner' AND status='Active' ORDER BY name")
            if role == "admin"
            else []
        ),
        my_assignment=any(u["id"] == uid for u in assigned),
        existing=one(
            "SELECT id FROM bookings WHERE student_id=? AND exam_id=? AND status!='Cancelled'",
            (uid, eid),
        ),
        rubric_locked=one("SELECT id FROM booking_info WHERE exam_id=? AND total IS NOT NULL", (eid,)),
    )


@bp.get("/slots")
@require("admin", "examiner")
def slots():
    role, uid = identity()
    return render_template(
        "slots.html",
        slots=rows(
            "SELECT * FROM slot_info WHERE (?='admin' OR examiner_id=?) ORDER BY start DESC", (role, uid)
        ),
    )


@bp.get("/slots/<int:sid>/roster")
@require("admin", "examiner")
def roster(sid):
    s = get("slot_info", sid)
    if g.user["role"] == "examiner" and s["examiner_id"] != g.user["id"]:
        abort(404)
    records = rows(
        "SELECT * FROM booking_info WHERE slot_id=? AND (?='admin' OR examiner_id=?) ORDER BY status='Cancelled',student",
        (sid, g.user["role"], g.user["id"]),
    )
    transfers = rows(
        """SELECT t.*,p.name previous,r.name replacement,a.name actor FROM slot_transfers t
                   JOIN users p ON p.id=t.previous_id JOIN users r ON r.id=t.replacement_id JOIN users a ON a.id=t.actor_id
                   WHERE slot_id=? ORDER BY t.id""",
        (sid,),
    )
    return render_template("roster.html", s=s, bookings=records, transfers=transfers)


def clash(examiner, start, end, ignored=0):
    return one(
        "SELECT id FROM slots WHERE examiner_id=? AND cancelled=0 AND id!=? AND start<? AND end>?",
        (examiner, ignored, end, start),
    )


@bp.route("/exams/<int:eid>/slots/new", defaults={"sid": None}, methods=["GET", "POST"])
@bp.route("/exams/<int:eid>/slots/<int:sid>/edit", methods=["GET", "POST"])
@require("examiner")
def slot_form(eid, sid):
    uid = g.user["id"]
    e = exam_access(eid)
    s = get("slots", sid) if sid else {}
    if sid and (s["exam_id"] != eid or s["examiner_id"] != uid):
        abort(403)
    check(
        one("SELECT * FROM assignments WHERE exam_id=? AND examiner_id=?", (eid, uid)),
        "An active examination assignment is required.",
    )
    if not sid:
        check(phase(e) == "Slot Creation", "The examiner slot creation period is closed.")
    if sid:
        check(
            now() < e["booking_start"]
            and not (e["archived"] or e["completed"])
            and e["course_status"] == "Active",
            "Slot editing closes when booking starts.",
        )
        check(
            not s["cancelled"] and not one("SELECT id FROM bookings WHERE slot_id=?", (sid,)),
            "This slot is locked.",
        )
    if request.method == "POST":
        if sid and request.form.get("action") == "remove":
            db().execute("UPDATE slots SET cancelled=1 WHERE id=?", (sid,))
        else:
            start = timestamp("start")
            check(start >= e["booking_end"] and start > now(), "Schedule the slot after booking closes.")
            end = (datetime.fromisoformat(start) + timedelta(minutes=e["duration"])).isoformat(
                timespec="minutes"
            )
            check(not clash(uid, start, end, sid or 0), "You already have a slot during this time.")
            values = (start, end, integer("capacity", 10000), field("room"))
            if sid:
                db().execute(
                    "UPDATE slots SET start=?,end=?,capacity=?,room=? WHERE id=?", (*values, sid)
                )
            else:
                db().execute(
                    "INSERT INTO slots(start,end,capacity,room,exam_id,examiner_id) VALUES(?,?,?,?,?,?)",
                    (*values, eid, uid),
                )
        return saved("portal.exam", eid=eid)
    return render_template("edit.html", kind="slot", item=s, e=e)


@bp.route("/slots/<int:sid>/reassign", methods=["GET", "POST"])
@require("admin")
def reassign(sid):
    s = get("slot_info", sid)
    e = get("exam_info", s["exam_id"])
    check(not (s["cancelled"] or e["archived"] or e["completed"]), "This slot is read-only.")
    check(
        s["end"] > now() or one("SELECT id FROM bookings WHERE slot_id=? AND status='Booked'", (sid,)),
        "Finished slots without outstanding bookings are read-only.",
    )
    if request.method == "POST":
        uid = integer("examiner_id")
        u = get("users", uid)
        check(
            u["role"] == "examiner" and u["status"] == "Active" and uid != s["examiner_id"],
            "Select a different approved examiner.",
        )
        check(not clash(uid, s["start"], s["end"], sid), "This examiner has an overlapping slot.")
        reason = field("reason")
        db().execute("INSERT OR IGNORE INTO assignments VALUES(?,?)", (s["exam_id"], uid))
        db().execute("UPDATE slots SET examiner_id=? WHERE id=?", (uid, sid))
        db().execute(
            "INSERT INTO slot_transfers(slot_id,at,previous_id,replacement_id,actor_id,reason) VALUES(?,?,?,?,?,?)",
            (sid, now(), s["examiner_id"], uid, g.user["id"], reason),
        )
        for b in rows("SELECT id FROM bookings WHERE slot_id=? AND status='Booked'", (sid,)):
            record(b["id"], f"Examiner changed from {s['examiner']} to {u['name']}. {reason}")
        return saved("portal.exam", eid=s["exam_id"])
    return render_template(
        "edit.html",
        kind="reassign",
        item=s,
        faculty=rows(
            "SELECT * FROM users WHERE role='examiner' AND status='Active' AND id!=? ORDER BY name",
            (s["examiner_id"],),
        ),
    )


def seat_check(s, student, ignored=0):
    check(
        not s["cancelled"]
        and s["seats"] > 0
        and s["start"] > now()
        and s["examiner_status"] == "Active",
        "This slot is no longer available.",
    )
    check(
        not one(
            "SELECT id FROM booking_info WHERE student_id=? AND status='Booked' AND id!=? AND start<? AND end>?",
            (student, ignored, s["end"], s["start"]),
        ),
        "The student has an overlapping examination.",
    )


@bp.post("/slots/<int:sid>/book")
@require("student")
def book(sid):
    s = get("slot_info", sid)
    e = exam_access(s["exam_id"])
    uid = g.user["id"]
    check(phase(e) == "Booking Open", "The student booking period is closed.")
    check(
        not one(
            "SELECT id FROM bookings WHERE student_id=? AND exam_id=? AND status!='Cancelled'",
            (uid, e["id"]),
        ),
        "You already have a booking for this examination.",
    )
    seat_check(s, uid)
    bid = (
        db()
        .execute(
            "INSERT INTO bookings(student_id,exam_id,slot_id,booked_at,status) VALUES(?,?,?,?,'Booked')",
            (uid, e["id"], sid, now()),
        )
        .lastrowid
    )
    record(bid, f"Booked slot #{sid} with {s['examiner']}.")
    return saved("portal.booking", bid=bid)


@bp.get("/bookings")
@require(*ALL)
def bookings():
    clause, args = booking_scope()
    q = request.args.get("q", "").strip()
    data = rows(
        f"""SELECT * FROM booking_info WHERE {clause} AND
        (CAST(id AS TEXT)=? OR student LIKE ? OR exam LIKE ? OR examiner LIKE ?) ORDER BY booked_at DESC,id DESC""",
        (*args, q, *([f"%{q}%"] * 3)),
    )
    return render_template("bookings.html", bookings=data)


@bp.get("/bookings/<int:bid>")
@require(*ALL)
def booking(bid):
    b = booking_access(bid)
    visible = b["total"] is not None and (g.user["role"] != "student" or b["published_at"])
    history = rows(
        "SELECT e.*,u.name actor FROM events e JOIN users u ON u.id=e.actor_id WHERE booking_id=? ORDER BY e.id",
        (bid,),
    )
    return render_template(
        "booking.html",
        b=b,
        visible=visible,
        history=history,
        scores=(
            rows(
                "SELECT s.mark,r.* FROM scores s JOIN rubrics r ON r.id=s.rubric_id WHERE booking_id=? ORDER BY r.id",
                (bid,),
            )
            if visible
            else []
        ),
    )


@bp.post("/bookings/<int:bid>/cancel")
@require("student")
def cancel(bid):
    b = booking_access(bid)
    check(
        b["status"] == "Booked" and now() < b["booking_end"],
        "Cancellation is available only before the booking deadline.",
    )
    db().execute("UPDATE bookings SET status='Cancelled' WHERE id=?", (bid,))
    record(bid, "Booking cancelled by student.")
    return saved("portal.booking", bid=bid)


@bp.route("/bookings/<int:bid>/reschedule", methods=["GET", "POST"])
@require("admin")
def reschedule(bid):
    b = booking_access(bid)
    check(b["status"] == "Booked", "Only outstanding bookings can be rescheduled.")
    if request.method == "POST":
        s = get("slot_info", integer("slot_id"))
        check(
            s["exam_id"] == b["exam_id"] and s["id"] != b["slot_id"],
            "Choose a different slot for the same examination.",
        )
        seat_check(s, b["student_id"], bid)
        reason = field("reason")
        db().execute("UPDATE bookings SET slot_id=? WHERE id=?", (s["id"], bid))
        record(
            bid,
            f"Rescheduled from slot #{b['slot_id']} ({b['start']}, {b['examiner']}) to #{s['id']} ({s['start']}, {s['examiner']}). {reason}",
        )
        return saved("portal.booking", bid=bid)
    choices = rows(
        "SELECT * FROM slot_info WHERE exam_id=? AND id!=? AND cancelled=0 AND seats>0 AND start>? AND examiner_status='Active' ORDER BY start",
        (b["exam_id"], b["slot_id"], now()),
    )
    return render_template("edit.html", kind="reschedule", item=b, choices=choices)


@bp.route("/bookings/<int:bid>/evaluate", methods=["GET", "POST"])
@require("examiner")
def evaluate(bid):
    b = booking_access(bid)
    check(
        b["status"] == "Booked" and b["end"] <= now(),
        "Only completed sittings with an outstanding evaluation can be marked.",
    )
    rubric = rows("SELECT * FROM rubrics WHERE exam_id=? ORDER BY id", (b["exam_id"],))
    check(
        sum(r["weight"] for r in rubric) == 100,
        "Ask the administrator to set criterion weights totalling 100%.",
    )
    if request.method == "POST":
        marks = [mark(f"mark_{r['id']}", r["maximum"]) for r in rubric]
        total = round(
            sum(m / r["maximum"] * r["weight"] for m, r in zip(marks, rubric)) * b["maximum"] / 100, 2
        )
        remarks = field("remarks", limit=3000)
        db().execute(
            "INSERT INTO evaluations(booking_id,examiner_id,total,remarks,submitted_at) VALUES(?,?,?,?,?)",
            (bid, g.user["id"], total, remarks, now()),
        )
        db().executemany(
            "INSERT INTO scores VALUES(?,?,?)", [(bid, r["id"], m) for r, m in zip(rubric, marks)]
        )
        db().execute("UPDATE bookings SET status='Completed' WHERE id=?", (bid,))
        record(bid, "Evaluation submitted.")
        return saved("portal.booking", bid=bid)
    return render_template("evaluate.html", b=b, rubric=rubric)


@bp.post("/bookings/<int:bid>/publish")
@require("admin")
def publish(bid):
    b = booking_access(bid)
    check(
        b["total"] is not None and not b["published_at"], "Select a submitted, unpublished evaluation."
    )
    db().execute("UPDATE evaluations SET published_at=? WHERE booking_id=?", (now(), bid))
    record(bid, "Result published.")
    return saved("portal.booking", bid=bid)
