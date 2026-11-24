"""Integration tests through normal HTTP forms, using a fresh SQLite database per test."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from emp import create_app
from emp.core import one, rows


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.time = datetime(2026, 4, 10, 12)
        self.app = create_app(
            dict(
                TESTING=True,
                SECRET_KEY="test",
                DATABASE=str(Path(self.scratch.name) / "test.db"),
                CLOCK=lambda: self.time,
            )
        )
        runner = self.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=["seed-demo"]).exit_code, 0)
        self.admin = self.login("admin")
        self.student = self.login("student")
        self.examiner = self.login("examiner")

    def post(self, client, url, **data):
        client.get("/")
        with client.session_transaction() as session:
            token = session["csrf"]
        return client.post(url, data=dict(csrf=token, **data), follow_redirects=True)

    def login(self, name):
        c = self.app.test_client()
        c.get("/login")
        with c.session_transaction() as session:
            token = session["csrf"]
        r = c.post(
            "/login",
            data=dict(
                email=f"{name}@emp.local",
                password="CampusAdmin123!" if name == "admin" else "CampusDemo123!",
                csrf=token,
            ),
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        return c

    def val(self, sql, args=()):
        with self.app.app_context():
            return one(sql, args)[0]

    def test_registration_approval_deactivation_and_access(self):
        guest = self.app.test_client()
        data = dict(
            name="New faculty",
            email="new@emp.local",
            password="CampusDemo123!",
            department="Physics",
            role="examiner",
        )
        self.assertEqual(self.post(guest, "/register", **data).status_code, 200)
        self.assertEqual(
            self.post(guest, "/login", email=data["email"], password=data["password"]).status_code, 403
        )
        uid = self.val("SELECT id FROM users WHERE email='new@emp.local'")
        self.post(self.admin, f"/admin/people/{uid}/status", status="Active")
        new = self.login("new")
        self.assertEqual(new.get("/admin/people").status_code, 403)
        self.post(self.admin, f"/admin/people/{uid}/status", status="Inactive")
        self.assertTrue(new.get("/", follow_redirects=True).request.path == "/login")
        self.assertEqual(self.post(guest, "/register", **dict(data, role="admin")).status_code, 422)
        self.assertEqual(self.student.post("/slots/1/book").status_code, 400)
        self.assertEqual(
            self.post(
                self.student,
                "/profile",
                name="New name",
                email="student@emp.local",
                department="Physics",
                contact="123",
            ).status_code,
            200,
        )
        self.assertIn(b"New name", self.student.get("/profile").data)
        self.assertEqual(self.admin.get("/admin/people?q=New+faculty").status_code, 200)

    def test_course_exam_rubrics_and_archival(self):
        self.assertEqual(
            self.post(
                self.admin,
                "/admin/courses/new",
                code="MA200",
                name="Calculus",
                description="Analysis",
                status="Active",
            ).status_code,
            200,
        )
        cid = self.val("SELECT id FROM courses WHERE code='MA200'")
        self.post(
            self.admin,
            f"/admin/courses/{cid}/edit",
            code="MA201",
            name="Analysis",
            description="",
            status="Active",
        )
        data = dict(
            course_id=cid,
            name="Oral exam",
            kind="Viva",
            duration=20,
            maximum=50,
            creation_start="2026-04-10T08:00",
            creation_end="2026-04-11T08:00",
            booking_start="2026-04-12T08:00",
            booking_end="2026-04-13T08:00",
        )
        self.assertEqual(self.post(self.admin, "/admin/exams/new", **data).status_code, 200)
        eid = self.val("SELECT id FROM exams WHERE name='Oral exam'")
        self.assertEqual(
            self.post(self.admin, f"/admin/exams/{eid}/edit", **dict(data, duration=25)).status_code, 200
        )
        self.assertEqual(
            self.post(
                self.admin,
                f"/admin/exams/{eid}/rubric",
                name="Proof",
                maximum=10,
                weight=100,
                description="",
            ).status_code,
            200,
        )
        rid = self.val("SELECT id FROM rubrics WHERE exam_id=?", (eid,))
        self.post(
            self.admin,
            f"/admin/exams/{eid}/rubric",
            rubric_id=rid,
            name="Proofs",
            maximum=20,
            weight=100,
            description="",
        )
        self.assertEqual(self.val("SELECT maximum FROM rubrics WHERE id=?", (rid,)), 20)
        self.post(self.admin, f"/admin/exams/{eid}/rubric", rubric_id=rid, action="remove")
        self.assertEqual(self.post(self.admin, f"/admin/courses/{cid}/remove").status_code, 422)
        self.post(self.admin, f"/admin/exams/{eid}/phase", action="archive")
        self.post(self.admin, f"/admin/courses/{cid}/remove")
        self.assertEqual(self.val("SELECT archived FROM courses WHERE id=?", (cid,)), 1)

    def test_windows_slot_edit_and_conflicts(self):
        e = 2
        url = f"/exams/{e}/slots/new"
        data = dict(start="2026-04-17T13:00", capacity=2, room="Lab 2")
        self.assertEqual(self.post(self.examiner, url, **data).status_code, 200)
        sid = self.val("SELECT id FROM slots WHERE room='Lab 2'")
        self.assertEqual(self.post(self.examiner, url, **data).status_code, 422)
        self.assertEqual(
            self.post(
                self.examiner, f"/exams/{e}/slots/{sid}/edit", **dict(data, capacity=3)
            ).status_code,
            200,
        )
        self.assertEqual(self.post(self.student, f"/slots/{sid}/book").status_code, 422)
        self.post(self.admin, f"/admin/exams/{e}/phase", action="creation_off")
        self.assertEqual(self.post(self.examiner, url, **data).status_code, 422)
        self.assertEqual(
            self.post(self.examiner, f"/exams/{e}/slots/{sid}/edit", action="remove").status_code, 200
        )
        self.time = datetime(2026, 4, 13, 9)
        self.assertEqual(self.post(self.examiner, "/exams/2/slots/3/edit", **data).status_code, 422)
        self.assertEqual(self.post(self.student, "/slots/1/book").status_code, 422)

    def test_book_cancel_reschedule_and_reassign(self):
        self.post(self.admin, "/admin/exams/1/phase", action="booking_off")
        self.assertEqual(self.post(self.student, "/slots/1/book").status_code, 422)
        self.post(self.admin, "/admin/exams/1/phase", action="booking_on")
        self.assertEqual(self.post(self.student, "/slots/1/book").status_code, 200)
        self.assertEqual(self.val("SELECT seats FROM slot_info WHERE id=1"), 0)
        self.assertEqual(self.post(self.student, "/slots/2/book").status_code, 422)
        bid = self.val("SELECT MAX(id) FROM bookings")
        self.assertEqual(self.post(self.student, f"/bookings/{bid}/cancel").status_code, 200)
        self.assertEqual(self.val("SELECT seats FROM slot_info WHERE id=1"), 1)
        self.post(self.student, "/slots/1/book")
        bid = self.val("SELECT MAX(id) FROM bookings")
        self.assertEqual(
            self.post(
                self.admin, f"/bookings/{bid}/reschedule", slot_id=2, reason="Room change"
            ).status_code,
            200,
        )
        uid = self.val("SELECT id FROM users WHERE email='examiner@emp.local'")
        self.assertEqual(
            self.post(
                self.admin, "/slots/2/reassign", examiner_id=uid, reason="Faculty cover"
            ).status_code,
            200,
        )
        self.assertIn(b"Faculty cover", self.student.get(f"/bookings/{bid}").data)
        self.assertEqual(self.val("SELECT count(*) FROM bookings WHERE status='Cancelled'"), 1)
        self.time = datetime(2026, 4, 12, 9)
        self.assertEqual(self.post(self.student, f"/bookings/{bid}/cancel").status_code, 422)

    def test_evaluation_publication_and_privacy(self):
        b = self.val("SELECT id FROM bookings WHERE exam_id=3")
        url = f"/bookings/{b}/evaluate"
        self.assertEqual(self.login("faculty").get(url).status_code, 404)
        self.assertEqual(self.login("student2").get(f"/bookings/{b}").status_code, 404)
        self.assertEqual(self.examiner.get(url).status_code, 200)
        with self.app.app_context():
            ids = [r[0] for r in rows("SELECT id FROM rubrics WHERE exam_id=3 ORDER BY id")]
        marks = {f"mark_{ids[0]}": 8, f"mark_{ids[1]}": 5, "remarks": "Strong normalization."}
        self.assertEqual(
            self.post(self.examiner, url, **dict(marks, **{f"mark_{ids[0]}": 11})).status_code, 422
        )
        self.assertEqual(self.post(self.examiner, url, **marks).status_code, 200)
        self.assertEqual(self.val("SELECT total FROM evaluations WHERE booking_id=?", (b,)), 68)
        self.assertNotIn(b"Strong normalization.", self.student.get(f"/bookings/{b}").data)
        self.assertEqual(self.post(self.admin, f"/bookings/{b}/publish").status_code, 200)
        self.assertIn(b"Strong normalization.", self.student.get(f"/bookings/{b}").data)
        self.assertEqual(
            self.post(
                self.admin, "/admin/exams/3/rubric", name="Test", maximum=10, weight=10
            ).status_code,
            422,
        )
        self.assertEqual(self.post(self.examiner, url, **marks).status_code, 422)

    def test_handover_preserves_submitted_evaluator(self):
        self.post(self.student, "/slots/1/book")
        self.time = datetime(2026, 4, 13, 11)
        first = self.val("SELECT MIN(id) FROM bookings WHERE slot_id=1")
        second = self.val("SELECT MAX(id) FROM bookings WHERE slot_id=1")
        self.post(
            self.examiner,
            f"/bookings/{first}/evaluate",
            mark_1=9,
            mark_2=7,
            remarks="Original evaluator",
        )
        uid = self.val("SELECT id FROM users WHERE email='faculty@emp.local'")
        self.assertEqual(
            self.post(self.admin, "/slots/1/reassign", examiner_id=uid, reason="Substitute").status_code,
            200,
        )
        substitute = self.login("faculty")
        self.assertEqual(self.examiner.get(f"/bookings/{second}/evaluate").status_code, 404)
        self.assertEqual(substitute.get(f"/bookings/{second}/evaluate").status_code, 200)
        self.assertIn(b"Original evaluator", self.examiner.get(f"/bookings/{first}").data)
        self.assertEqual(substitute.get(f"/bookings/{first}").status_code, 404)
        self.assertEqual(self.val("SELECT examiner FROM booking_info WHERE id=?", (first,)), "Meera Rao")

    def test_last_seat_concurrently(self):
        guest = self.app.test_client()
        self.post(
            guest,
            "/register",
            role="student",
            name="Second candidate",
            department="CS",
            email="race@emp.local",
            password="CampusDemo123!",
        )
        barrier = Barrier(2)

        def contender(name):
            c = self.login(name)
            with c.session_transaction() as session:
                token = session["csrf"]
            barrier.wait(timeout=15)
            return c.post("/slots/1/book", data={"csrf": token}).status_code

        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(contender, ("race", "student")))
        self.assertEqual(sorted(codes), [302, 422])
        self.assertEqual(self.val("SELECT seats FROM slot_info WHERE id=1"), 0)

    def test_registers_and_forms_render(self):
        for path in [
            "/",
            "/admin/courses",
            "/admin/courses/new",
            "/admin/courses/1/edit",
            "/admin/exams/new",
            "/admin/exams/1/edit",
            "/admin/people",
            "/exams",
            "/exams/1",
            "/slots",
            "/bookings",
            "/bookings/1/reschedule",
            "/slots/1/reassign",
            "/slots/1/roster",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.admin.get(path).status_code, 200)
        for path in ["/", "/exams", "/exams/1", "/bookings", "/bookings/3", "/profile"]:
            self.assertEqual(self.student.get(path).status_code, 200)
        self.assertIn(b"SQL practical", self.student.get("/exams?kind=Practical&q=SQL").data)
        self.assertNotIn(b"Capstone project demo", self.student.get("/exams?kind=Practical&q=SQL").data)
        self.assertIn(b"Clear requirements analysis", self.student.get("/bookings/3").data)


if __name__ == "__main__":
    unittest.main()
