from flask import Blueprint, flash, redirect, render_template, request, url_for

from .auth import add_user
from .core import check, db, field, get, integer, now, one, require, rows, timestamp

bp = Blueprint("admin", __name__, url_prefix="/admin")
KINDS = ("Viva", "Practical", "Project Demo", "Assessment")


def saved(endpoint, **kwargs):
    flash("Changes saved.")
    return redirect(url_for(endpoint, **kwargs))


def manage(eid):
    return saved("portal.exam", eid=eid)


@bp.get("/courses")
@require("admin")
def courses():
    return render_template("courses.html", courses=rows("SELECT * FROM courses ORDER BY archived,code"))


@bp.route("/courses/new", defaults={"cid": None}, methods=["GET", "POST"])
@bp.route("/courses/<int:cid>/edit", methods=["GET", "POST"])
@require("admin")
def course_form(cid):
    c = get("courses", cid) if cid else {}
    if request.method == "POST":
        check(not cid or not c["archived"], "This course is archived.")
        status = field("status")
        check(status in ("Active", "Inactive"), "Choose a course status.")
        data = (
            field("code").upper(),
            field("name"),
            field("description", required=False, limit=3000),
            status,
        )
        if cid:
            db().execute(
                "UPDATE courses SET code=?,name=?,description=?,status=? WHERE id=?", (*data, cid)
            )
        else:
            db().execute("INSERT INTO courses(code,name,description,status) VALUES(?,?,?,?)", data)
        return saved("admin.courses")
    return render_template("edit.html", kind="course", item=c)


@bp.post("/courses/<int:cid>/remove")
@require("admin")
def remove_course(cid):
    get("courses", cid)
    check(
        not one("SELECT id FROM exams WHERE course_id=? AND archived=0", (cid,)),
        "Archive this course's examinations first.",
    )
    db().execute("UPDATE courses SET archived=1,status='Inactive' WHERE id=?", (cid,))
    return saved("admin.courses")


@bp.route("/exams/new", defaults={"eid": None}, methods=["GET", "POST"])
@bp.route("/exams/<int:eid>/edit", methods=["GET", "POST"])
@require("admin")
def exam_form(eid):
    e = get("exams", eid) if eid else {}
    if request.method == "POST":
        check(not eid or not (e["archived"] or e["completed"]), "This exam is read-only.")
        cid, kind = integer("course_id"), field("kind")
        course = get("courses", cid)
        check(not course["archived"] and kind in KINDS, "Choose a current course and a valid exam type.")
        times = [
            timestamp(k) for k in ("creation_start", "creation_end", "booking_start", "booking_end")
        ]
        check(
            times[0] < times[1] <= times[2] < times[3],
            "Slot creation must finish before booking, and each window needs a positive duration.",
        )
        duration, maximum = integer("duration", 1440), integer("maximum")
        if eid and one("SELECT id FROM slots WHERE exam_id=? AND cancelled=0", (eid,)):
            check(duration == e["duration"], "The duration is fixed once slots exist.")
            check(
                not one(
                    "SELECT id FROM slots WHERE exam_id=? AND cancelled=0 AND start<?", (eid, times[3])
                ),
                "Booking must finish before the first slot.",
            )
        if eid and one("SELECT id FROM bookings WHERE exam_id=?", (eid,)):
            check(
                times[2] == e["booking_start"] and cid == e["course_id"],
                "The course and booking start are fixed once bookings exist.",
            )
        if eid and one(
            "SELECT b.id FROM bookings b JOIN evaluations v ON b.id=v.booking_id WHERE b.exam_id=?",
            (eid,),
        ):
            check(maximum == e["maximum"], "Maximum marks are fixed after evaluation.")
        data = (cid, field("name"), kind, duration, maximum, *times)
        if eid:
            db().execute(
                "UPDATE exams SET course_id=?,name=?,kind=?,duration=?,maximum=?,creation_start=?,creation_end=?,booking_start=?,booking_end=? WHERE id=?",
                (*data, eid),
            )
        else:
            eid = (
                db()
                .execute(
                    "INSERT INTO exams(course_id,name,kind,duration,maximum,creation_start,creation_end,booking_start,booking_end) VALUES(?,?,?,?,?,?,?,?,?)",
                    data,
                )
                .lastrowid
            )
        return manage(eid)
    return render_template(
        "edit.html",
        kind="exam",
        item=e,
        courses=rows("SELECT * FROM courses WHERE archived=0 ORDER BY code"),
        kinds=KINDS,
    )


@bp.post("/exams/<int:eid>/phase")
@require("admin")
def change_phase(eid):
    e = get("exams", eid)
    check(not e["archived"], "This exam is archived.")
    action = field("action")
    if action in ("creation_on", "creation_off", "booking_on", "booking_off"):
        check(not e["completed"], "This exam has been completed.")
        gate = "creation_enabled" if action.startswith("creation") else "booking_enabled"
        db().execute(
            f"UPDATE exams SET {gate}=?,released=1 WHERE id=?", (int(action.endswith("_on")), eid)
        )
    elif action in ("complete", "archive"):
        check(
            not one("SELECT id FROM bookings WHERE exam_id=? AND status='Booked'", (eid,)),
            "Finish all outstanding bookings before completing or archiving this exam.",
        )
        if action == "complete":
            check(
                not one("SELECT id FROM slots WHERE exam_id=? AND cancelled=0 AND end>?", (eid, now())),
                "Future slots remain on this exam.",
            )
            db().execute("UPDATE exams SET completed=1 WHERE id=?", (eid,))
        else:
            db().execute("UPDATE exams SET archived=1 WHERE id=?", (eid,))
    else:
        check(False, "Unknown phase action.")
    return manage(eid)


@bp.post("/exams/<int:eid>/assign")
@require("admin")
def assign(eid):
    e = get("exams", eid)
    check(not e["archived"] and not e["completed"], "This examination is read-only.")
    uid = integer("examiner_id")
    u = get("users", uid)
    if field("action") == "remove":
        check(
            not one(
                "SELECT id FROM slots WHERE exam_id=? AND examiner_id=? AND cancelled=0 AND (end>? OR EXISTS(SELECT 1 FROM bookings WHERE slot_id=slots.id AND status='Booked'))",
                (eid, uid, now()),
            ),
            "Reassign this examiner's remaining slots first.",
        )
        db().execute("DELETE FROM assignments WHERE exam_id=? AND examiner_id=?", (eid, uid))
    else:
        check(u["role"] == "examiner" and u["status"] == "Active", "Choose an approved examiner.")
        db().execute("INSERT OR IGNORE INTO assignments VALUES(?,?)", (eid, uid))
    return manage(eid)


@bp.post("/exams/<int:eid>/rubric")
@require("admin")
def rubric(eid):
    e = get("exams", eid)
    check(not (e["archived"] or e["completed"]), "This exam is read-only.")
    check(
        not one(
            "SELECT v.booking_id FROM evaluations v JOIN bookings b ON b.id=v.booking_id WHERE b.exam_id=?",
            (eid,),
        ),
        "The rubric is fixed after the first evaluation.",
    )
    rid = request.form.get("rubric_id")
    if rid:
        check(one("SELECT id FROM rubrics WHERE exam_id=? AND id=?", (eid, rid)), "Invalid criterion.")
    if request.form.get("action") == "remove" and rid:
        db().execute("DELETE FROM rubrics WHERE id=?", (rid,))
    else:
        data = (
            field("name"),
            integer("maximum"),
            integer("weight", 100),
            field("description", required=False, limit=2000),
        )
        if rid:
            db().execute(
                "UPDATE rubrics SET name=?,maximum=?,weight=?,description=? WHERE id=?", (*data, rid)
            )
        else:
            db().execute(
                "INSERT INTO rubrics(name,maximum,weight,description,exam_id) VALUES(?,?,?,?,?)",
                (*data, eid),
            )
    return manage(eid)


@bp.route("/people", methods=["GET", "POST"])
@require("admin")
def people():
    if request.method == "POST":
        add_user("examiner", "Active")
        return saved("admin.people")
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    data = rows(
        """SELECT * FROM users WHERE role IN ('student','examiner') AND (?='' OR role=?)
                AND (name LIKE ? OR CAST(id AS TEXT)=? OR email LIKE ?) ORDER BY status='Pending' DESC,name""",
        (role, role, f"%{q}%", q, f"%{q}%"),
    )
    return render_template("people.html", people=data)


@bp.post("/people/<int:uid>/status")
@require("admin")
def user_status(uid):
    u = get("users", uid)
    status = field("status")
    check(
        u["role"] == "examiner" and status in ("Active", "Inactive"),
        "Choose an examiner and a valid status.",
    )
    db().execute("UPDATE users SET status=? WHERE id=?", (status, uid))
    if request.form.get("return_to") == "overview":
        return saved("portal.home")
    return saved("admin.people")
