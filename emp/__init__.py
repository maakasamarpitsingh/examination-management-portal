import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, g, render_template, request, session
from werkzeug.security import generate_password_hash

from .core import Invalid, db, now, one, phase, schedule_date, slot_status, when


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    folder = Path(app.instance_path)
    folder.mkdir(exist_ok=True, parents=True)
    app.config.from_mapping(
        DATABASE=str(folder / "emp.sqlite3"),
        SECRET_KEY=os.getenv("EMP_SECRET"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    app.config.update(config or {})
    if not app.config["SECRET_KEY"]:
        keyfile = folder / "session.key"
        try:
            with keyfile.open("x") as stream:
                stream.write(secrets.token_hex(32))
            keyfile.chmod(0o600)
        except FileExistsError:
            pass
        app.config["SECRET_KEY"] = keyfile.read_text()

    @app.teardown_appcontext
    def disconnect(error):
        con = g.pop("connection", None)
        if con:
            con.close()

    with app.app_context():
        db().executescript(Path(__file__).with_name("schema.sql").read_text())
        if not one("SELECT id FROM users WHERE role='admin'"):
            db().execute(
                "INSERT OR IGNORE INTO users(role,name,email,password,status) VALUES('admin','Portal Administrator',?,?,'Active')",
                (
                    os.getenv("EMP_ADMIN_EMAIL", "admin@emp.local"),
                    generate_password_hash(os.getenv("EMP_ADMIN_PASSWORD", "CampusAdmin123!")),
                ),
            )

    @app.before_request
    def prepare():
        if request.endpoint == "static":
            return
        if request.method == "POST":
            expected = session.get("csrf", "")
            if not expected or not secrets.compare_digest(
                expected.encode(), request.form.get("csrf", "").encode()
            ):
                abort(400, "This form expired. Reload the page and try again.")
            # Serialize validation with its write, even when two users book the final seat.
            db().execute("BEGIN IMMEDIATE")
        g.user = one("SELECT * FROM users WHERE id=?", (session["uid"],)) if "uid" in session else None
        if g.user and g.user["status"] != "Active":
            session.clear()
            g.user = None
        session.setdefault("csrf", secrets.token_urlsafe(32))

    @app.after_request
    def finish(response):
        con = g.get("connection")
        if con and con.in_transaction:
            con.commit() if response.status_code < 400 else con.rollback()
        return response

    @app.errorhandler(Invalid)
    @app.errorhandler(sqlite3.IntegrityError)
    def invalid(error):
        db().rollback()
        message = (
            str(error)
            if isinstance(error, Invalid)
            else "This entry conflicts with an existing record. Check the details and try again."
        )
        return render_template("error.html", title="Please review this action", message=message), 422

    for code in (400, 403, 404):
        app.register_error_handler(
            code,
            lambda err: (
                render_template("error.html", title=err.name, message=err.description),
                err.code,
            ),
        )

    from . import auth, admin, portal, demo

    for module in (auth, admin, portal):
        app.register_blueprint(module.bp)
    app.cli.add_command(demo.seed_demo)
    app.jinja_env.filters["when"] = when
    app.jinja_env.filters["schedule_date"] = schedule_date
    app.jinja_env.globals.update(phase=phase, slot_status=slot_status, now=now)
    return app
