"""Optional fictional records for a local classroom demonstration."""

from datetime import datetime, timedelta
import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash
from .core import db, now, one


@click.command("seed-demo")
@with_appcontext
def seed_demo():
    con = db()
    con.execute("BEGIN IMMEDIATE")
    try:
        if one("SELECT id FROM courses LIMIT 1") or one(
            "SELECT id FROM users WHERE role!='admin' LIMIT 1"
        ):
            raise click.ClickException(
                "Demo seeding requires a fresh portal with only its administrator. Existing data was kept."
            )
        populate(con)
        con.commit()
    except Exception:
        con.rollback()
        raise
    click.echo("Demo ready. Student and examiner credentials are in README.md.")


def populate(con):
    today = datetime.fromisoformat(now()).replace(hour=0, minute=0)

    def at(day, hour=9):
        return (today + timedelta(days=day, hours=hour)).isoformat(timespec="minutes")

    password = generate_password_hash("CampusDemo123!")

    def person(role, name, email, status="Active"):
        return con.execute(
            "INSERT INTO users(role,name,email,password,status,department) VALUES(?,?,?,?,?,'Computer Science')",
            (role, name, email, password, status),
        ).lastrowid

    examiner = person("examiner", "Meera Rao", "examiner@emp.local")
    other = person("examiner", "Arun Das", "faculty@emp.local")
    person("examiner", "Nisha Shah", "pending@emp.local", "Pending")
    student = person("student", "Aarav Singh", "student@emp.local")
    peer = person("student", "Isha Sen", "student2@emp.local")
    c = con.execute(
        "INSERT INTO courses(code,name,description,status) VALUES('CS204','Database Systems','Relational models, queries, and database design.','Active')"
    ).lastrowid
    d = con.execute(
        "INSERT INTO courses(code,name,description,status) VALUES('CS310','Software Engineering','Project delivery and technical communication.','Active')"
    ).lastrowid

    def exam(course, name, kind, days, creation, booking):
        eid = con.execute(
            """INSERT INTO exams(course_id,name,kind,duration,maximum,creation_start,creation_end,booking_start,booking_end,
                        released,creation_enabled,booking_enabled) VALUES(?,?,?,30,100,?,?,?,?,1,?,?)""",
            (course, name, kind, *(at(i) for i in days), creation, booking),
        ).lastrowid
        con.executemany("INSERT INTO assignments VALUES(?,?)", [(eid, examiner), (eid, other)])
        con.executemany(
            "INSERT INTO rubrics(exam_id,name,maximum,weight,description) VALUES(?,?,?,?,?)",
            [
                (eid, "Technical accuracy", 10, 60, "Correctness of the solution and reasoning."),
                (eid, "Explanation", 10, 40, "Clarity of the demonstration and answers."),
            ],
        )
        return eid

    def slot(eid, person, day, hour, capacity):
        start = at(day, hour)
        end = (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat(timespec="minutes")
        return con.execute(
            "INSERT INTO slots(exam_id,examiner_id,start,end,capacity,room) VALUES(?,?,?,?,?,'Lab B-204')",
            (eid, person, start, end, capacity),
        ).lastrowid

    def book(eid, sid, uid, day):
        bid = con.execute(
            "INSERT INTO bookings(student_id,exam_id,slot_id,booked_at,status) VALUES(?,?,?,?,'Booked')",
            (uid, eid, sid, at(day)),
        ).lastrowid
        con.execute(
            "INSERT INTO events(booking_id,at,actor_id,detail) VALUES(?,?,?,?)",
            (bid, at(day), uid, f"Booked slot #{sid}."),
        )
        return bid

    open_exam = exam(c, "SQL practical", "Practical", [-7, -4, -3, 2], 0, 1)
    first = slot(open_exam, examiner, 3, 10, 2)
    slot(open_exam, other, 3, 11, 3)
    book(open_exam, first, peer, -1)
    creation = exam(d, "Capstone project demo", "Project Demo", [-1, 2, 3, 5], 1, 0)
    slot(creation, examiner, 6, 14, 4)
    recent = exam(c, "Database design viva", "Viva", [-10, -8, -7, -5], 0, 0)
    sitting = slot(recent, examiner, -2, 10, 3)
    book(recent, sitting, student, -6)
    older = exam(d, "Requirements assessment", "Assessment", [-20, -18, -17, -15], 0, 0)
    sitting = slot(older, other, -12, 10, 2)
    bid = book(older, sitting, student, -16)
    con.execute("UPDATE bookings SET status='Completed' WHERE id=?", (bid,))
    con.execute(
        "INSERT INTO evaluations VALUES(?,?,?,?,?,?)",
        (
            bid,
            other,
            86.0,
            "Clear requirements analysis. Include edge cases in the acceptance criteria.",
            at(-12, 12),
            at(-11),
        ),
    )
    for r, m in zip(con.execute("SELECT id FROM rubrics WHERE exam_id=? ORDER BY id", (older,)), (9, 8)):
        con.execute("INSERT INTO scores VALUES(?,?,?)", (bid, r[0], m))
    admin = one("SELECT id FROM users WHERE role='admin'")["id"]
    con.executemany(
        "INSERT INTO events(booking_id,at,actor_id,detail) VALUES(?,?,?,?)",
        [(bid, at(-12, 12), other, "Evaluation submitted."), (bid, at(-11), admin, "Result published.")],
    )
    con.execute("UPDATE exams SET completed=1 WHERE id=?", (older,))
