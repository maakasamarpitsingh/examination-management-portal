import re
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .core import check, db, field, one, require

bp = Blueprint("auth", __name__)


def email():
    address = field("email", limit=254).lower()
    check(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address), "Enter a valid email address.")
    return address


def add_user(role, status):
    check(role in ("examiner", "student"), "Choose a student or examiner account.")
    password = request.form.get("password", "")
    check(8 <= len(password) <= 256, "Use a password between 8 and 256 characters.")
    return (
        db()
        .execute(
            "INSERT INTO users(name,email,password,department,contact,role,status) VALUES(?,?,?,?,?,?,?)",
            (
                field("name"),
                email(),
                generate_password_hash(password),
                field("department"),
                field("contact", required=False),
                role,
                status,
            ),
        )
        .lastrowid
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = one("SELECT * FROM users WHERE email=?", (email(),))
        password = request.form.get("password", "")
        if not user or len(password) > 256 or not check_password_hash(user["password"], password):
            return (
                render_template("auth.html", mode="login", error="Email or password is incorrect."),
                401,
            )
        if user["status"] != "Active":
            return (
                render_template(
                    "auth.html",
                    mode="login",
                    error=(
                        "Your registration is awaiting approval."
                        if user["status"] == "Pending"
                        else "Your account is inactive. Contact the administrator."
                    ),
                ),
                403,
            )
        session.clear()
        session["uid"] = user["id"]
        return redirect(url_for("portal.home"))
    return render_template("auth.html", mode="login")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        role = field("role")
        add_user(role, "Pending" if role == "examiner" else "Active")
        flash(
            "Registration received. An administrator must approve your examiner account."
            if role == "examiner"
            else "Account created. You can now sign in."
        )
        return redirect(url_for("auth.login"))
    return render_template("auth.html", mode="register")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@require("student", "examiner", "admin")
def profile():
    if request.method == "POST":
        db().execute(
            "UPDATE users SET name=?,email=?,department=?,contact=? WHERE id=?",
            (
                field("name"),
                email(),
                field("department", required=False),
                field("contact", required=False),
                g.user["id"],
            ),
        )
        flash("Profile updated.")
        return redirect(url_for("auth.profile"))
    return render_template("auth.html", mode="profile")
