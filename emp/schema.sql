PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('admin','examiner','student')),
 name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password TEXT NOT NULL,
 department TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('Active','Pending','Inactive'))
);
CREATE TABLE IF NOT EXISTS courses (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL COLLATE NOCASE UNIQUE, name TEXT NOT NULL,
 description TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('Active','Inactive')), archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS exams (
 id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses, name TEXT NOT NULL,
 kind TEXT NOT NULL, duration INTEGER NOT NULL CHECK(duration > 0), maximum INTEGER NOT NULL CHECK(maximum > 0),
 creation_start TEXT NOT NULL, creation_end TEXT NOT NULL, booking_start TEXT NOT NULL, booking_end TEXT NOT NULL,
 creation_enabled INTEGER NOT NULL DEFAULT 0, booking_enabled INTEGER NOT NULL DEFAULT 0,
 released INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
 CHECK(creation_start < creation_end AND creation_end <= booking_start AND booking_start < booking_end)
);
CREATE TABLE IF NOT EXISTS assignments (
 exam_id INTEGER NOT NULL REFERENCES exams, examiner_id INTEGER NOT NULL REFERENCES users, PRIMARY KEY(exam_id, examiner_id)
);
CREATE TABLE IF NOT EXISTS rubrics (
 id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams, name TEXT NOT NULL,
 maximum INTEGER NOT NULL CHECK(maximum > 0), weight INTEGER NOT NULL CHECK(weight BETWEEN 1 AND 100),
 description TEXT NOT NULL, UNIQUE(exam_id, name)
);
CREATE TABLE IF NOT EXISTS slots (
 id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams, examiner_id INTEGER NOT NULL REFERENCES users,
 start TEXT NOT NULL, end TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity > 0), room TEXT NOT NULL,
 cancelled INTEGER NOT NULL DEFAULT 0, CHECK(start < end)
);
CREATE TABLE IF NOT EXISTS bookings (
 id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users, exam_id INTEGER NOT NULL REFERENCES exams,
 slot_id INTEGER NOT NULL REFERENCES slots, booked_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('Booked','Cancelled','Completed'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_booking ON bookings(student_id,exam_id) WHERE status != 'Cancelled';
CREATE INDEX IF NOT EXISTS slot_bookings ON bookings(slot_id,status);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL REFERENCES bookings, at TEXT NOT NULL, actor_id INTEGER NOT NULL REFERENCES users,
 detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
 booking_id INTEGER PRIMARY KEY REFERENCES bookings, examiner_id INTEGER NOT NULL REFERENCES users,
 total REAL NOT NULL, remarks TEXT NOT NULL, submitted_at TEXT NOT NULL, published_at TEXT
);
CREATE TABLE IF NOT EXISTS scores (
 booking_id INTEGER NOT NULL REFERENCES evaluations, rubric_id INTEGER NOT NULL REFERENCES rubrics, mark REAL NOT NULL,
 PRIMARY KEY(booking_id, rubric_id)
);
CREATE VIEW IF NOT EXISTS exam_info AS SELECT e.*,c.code,c.name course_name,c.status course_status,c.archived course_archived
 FROM exams e JOIN courses c ON c.id=e.course_id;
CREATE VIEW IF NOT EXISTS slot_info AS SELECT s.*,e.name exam,e.code,u.name examiner,u.status examiner_status,
 (SELECT count(*) FROM bookings pending WHERE pending.slot_id=s.id AND pending.status='Booked') pending_count,
 s.capacity-(SELECT count(*) FROM bookings b WHERE b.slot_id=s.id AND b.status!='Cancelled') seats
 FROM slots s JOIN exam_info e ON e.id=s.exam_id JOIN users u ON u.id=s.examiner_id;
CREATE VIEW IF NOT EXISTS booking_info AS SELECT b.*,u.name student,s.exam,s.start,s.end,s.room,
 COALESCE(marker.name,s.examiner) examiner,COALESCE(v.examiner_id,s.examiner_id) examiner_id,
 v.total,v.remarks,v.published_at,e.maximum,e.booking_end FROM bookings b JOIN users u ON u.id=b.student_id
 JOIN slot_info s ON s.id=b.slot_id JOIN exams e ON e.id=b.exam_id LEFT JOIN evaluations v ON v.booking_id=b.id
 LEFT JOIN users marker ON marker.id=v.examiner_id;
CREATE TABLE IF NOT EXISTS slot_transfers (
 id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES slots, at TEXT NOT NULL,
 previous_id INTEGER NOT NULL REFERENCES users, replacement_id INTEGER NOT NULL REFERENCES users,
 actor_id INTEGER NOT NULL REFERENCES users, reason TEXT NOT NULL
);
