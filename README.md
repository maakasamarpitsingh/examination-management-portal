# Examination Management Portal

A local Flask application for planning examinations, allocating seats, recording rubric-based evaluations and publishing results. The interface uses Jinja2, HTML, Bootstrap 5.3.5 and custom CSS. Every action uses a server-rendered page and a standard HTML form. SQLite is the only database. Bootstrap is bundled for offline classroom demos.

## Run on macOS or Linux

Install Python 3.9 or later. Extract the ZIP, open a terminal in the folder containing `app.py`, and run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m flask --app app seed-demo
python app.py
```

Open **http://127.0.0.1:5000**. On subsequent runs, activate the environment and run `python app.py`. If port 5000 is occupied, use `python -m flask --app app run --port 5050` and open http://127.0.0.1:5050.

## Run on Windows

In Command Prompt, change to the extracted folder containing `app.py` and run:

```bat
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m flask --app app seed-demo
python app.py
```

The first installation requires access to the Python package index. After that, the demo runs locally. Omit `seed-demo` for a fresh portal with only its administrator. The demo command populates an otherwise empty portal and keeps existing records intact on repeat runs. It computes exam windows relative to the day you seed the database. For another fresh demo later, extract a new copy of the ZIP into another folder.

## Accounts

| Role | Email | Password | Starting point |
|---|---|---|---|
| Administrator | admin@emp.local | CampusAdmin123! | Pre-created on first launch |
| Examiner | examiner@emp.local | CampusDemo123! | Meera Rao, approved |
| Examiner | faculty@emp.local | CampusDemo123! | Arun Das, approved |
| Examiner | pending@emp.local | CampusDemo123! | Nisha Shah, waiting for approval |
| Student | student@emp.local | CampusDemo123! | Aarav Singh, a past sitting and a published result |
| Student | student2@emp.local | CampusDemo123! | Isha Sen, booked for the SQL practical |

Only the admin account exists without demo seeding. For your own installation, set `EMP_ADMIN_EMAIL` and `EMP_ADMIN_PASSWORD` in the environment **before the first launch or Flask command**. Passwords are stored as hashes. These default credentials are for a local demonstration.

## A five-minute walkthrough

1. **Examiner approval.** Sign in as admin. Open **Examiners**, find Nisha Shah, and approve her. She can now sign in. Use separate browser profiles for simultaneous roles, or sign out between steps.
2. **Create a slot.** As Meera, open **Examinations → Capstone project demo → Create slot**. Set a start after the booking deadline shown on the form and choose a room and capacity. Reopen the examination to edit or remove the slot before booking starts.
3. **Book the last seat.** As Aarav, open **Examinations → SQL practical** and book the 10:00 slot. Isha already occupies one of its two seats. The slot becomes full. Open the booking to cancel before the deadline, then book again to see both records in **Bookings**.
4. **Handle a schedule change.** As admin, open Aarav’s live SQL booking and reschedule it into the other SQL practical slot. Use **Slots → Reassign** to change the receiving slot from Arun to Meera. Supply a reason for each change. Open the booking history and slot roster to see the updates.
5. **Mark and publish.** As Meera, open **Overview → Pending evaluations → Database design viva → Details → Evaluate student**. Give 8/10 for technical accuracy and 5/10 for explanation, and submit a remark. The weights are 60% and 40%, giving **68/100**. As admin, open that booking and select **Publish result**. As Aarav, open **Overview → Published results** to see the score breakdown and feedback.

The demo uses four examinations at different stages so you can demonstrate all roles immediately.

## Running a new examination

- Create the course and examination under the admin account. Set the type, duration, total marks and both date ranges.
- On its detail page, assign an approved examiner. Add rubric criteria and allocate a total of 100% before evaluation.
- Enable slot creation and student booking separately. You can enable a window in advance. Flask checks the server's local clock on every submission. Windows include the start and exclude the end. The booking window must follow slot creation. Every sitting starts at or after the booking deadline.
- An assigned examiner can create slots inside the enabled creation window and edit or remove an unused slot before the booking start. End times follow the exam duration. The app rejects overlapping examiner slots.
- Students can search the register by name, ID or course, filter by phase or type, book, cancel before the deadline, and edit their profile. Duplicate live bookings and overlapping student schedules are rejected. A full slot becomes available again when a seat is released.
- Admins may move an outstanding booking to a future slot of the same exam, even outside the student booking window. Capacity and scheduling checks still apply. Reassignment selects an approved examiner and adds that examiner to the exam's assignments. A deactivated examiner loses access immediately. Their remaining slots can be reassigned.
- Only the responsible examiner can evaluate a student after the sitting ends. Submitted marks are final. A submitted evaluation fixes the exam's rubric and maximum marks, and preserves the evaluator's name on that student's result. A substitute can take over the other outstanding bookings. Admin publishes each result separately. Students can view their own published marks and feedback.
- Archiving removes a finished or unused exam from the active student catalogue. Linked booking histories stay available. A course can be archived after its exams have been archived. Admins can filter the register to **Archived**.

The weighted total is the sum of each raw score divided by its criterion maximum, multiplied by the criterion weight and the examination maximum divided by 100. Final totals are rounded to two decimal places.

## Inside the project

| Path | Purpose |
|---|---|
| app.py | Local entry point |
| emp/__init__.py | Application factory, automatic schema creation, initial admin, session and transaction management |
| emp/schema.sql | Tables, foreign keys, views and the unique active-booking index |
| emp/core.py | Shared validation, role checks, time rules and database functions |
| emp/auth.py | Login, registration and profile editing |
| emp/admin.py | Courses, examinations, rubrics, timelines and people |
| emp/portal.py | Dashboards, registers, slot rosters, booking, marking and publication |
| emp/demo.py | Optional relative-date demo dataset |
| emp/templates, emp/static | Jinja templates, Bootstrap, styles and license |
| tests/test_portal.py | HTTP workflow and concurrent booking tests |

On startup the app creates `instance/emp.sqlite3` and a local session key. There is no manual database setup. Back up the instance directory to retain the installation. The ZIP excludes private state.

## Run the tests

With the virtual environment active, from the project root:

```sh
python -m unittest discover -s tests -v
```

Tests use temporary databases and a controlled clock. They cover access and approval, course/exam management, slot timing, duplicate booking, concurrent last-seat booking, cancellation deadlines, exceptional changes, evaluation and result visibility.
