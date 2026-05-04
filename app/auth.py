from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from .models import User, db
from .security import clear_attempts, is_safe_redirect_url, too_many_attempts


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=("GET", "POST"))
def register():
    if current_user.is_authenticated:
        return redirect(url_for("forum.index"))

    if request.method == "POST":
        if too_many_attempts("register_attempts", limit=8, window_seconds=300):
            flash("Too many registration attempts. Please wait a few minutes and try again.", "error")
            return render_template("auth/register.html"), 429
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Username, email, and password are required.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif User.query.filter((User.username == username) | (User.email == email)).first():
            flash("That username or email is already in use.", "error")
        else:
            admin_emails = current_app.config.get("ADMIN_EMAILS", [])
            user = User(username=username, email=email, is_admin=User.query.count() == 0 or email in admin_emails)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            clear_attempts("register_attempts")
            login_user(user)
            flash("Welcome aboard. Pick a few communities to personalize your feed.", "success")
            return redirect(url_for("forum.onboarding"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=("GET", "POST"))
def login():
    if current_user.is_authenticated:
        return redirect(url_for("forum.index"))

    if request.method == "POST":
        if too_many_attempts("login_attempts", limit=6, window_seconds=300):
            flash("Too many sign-in attempts. Please wait a few minutes and try again.", "error")
            return render_template("auth/login.html"), 429
        username_or_email = request.form.get("username_or_email", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email.lower())
        ).first()

        if user is None or not user.check_password(password):
            flash("Invalid username, email, or password.", "error")
        else:
            clear_attempts("login_attempts")
            login_user(user)
            flash("Signed in successfully.", "success")
            next_url = request.args.get("next")
            return redirect(next_url if is_safe_redirect_url(next_url) else url_for("forum.index"))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=("POST",))
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("forum.index"))
