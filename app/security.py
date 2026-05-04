import secrets
import time
from urllib.parse import urlparse

from flask import abort, current_app, request, session


def is_safe_redirect_url(target):
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.scheme == "" and parsed.netloc == "" and target.startswith("/")


def csrf_token():
    token = session.get("_csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def protect_from_csrf():
    if current_app.config.get("TESTING"):
        return
    if request.method != "POST":
        return
    sent_token = request.form.get("_csrf_token")
    if not sent_token or sent_token != session.get("_csrf_token"):
        abort(400, description="Invalid CSRF token.")


def too_many_attempts(key, limit=5, window_seconds=60):
    now = time.time()
    attempts = [stamp for stamp in session.get(key, []) if now - stamp < window_seconds]
    if len(attempts) >= limit:
        session[key] = attempts
        return True
    attempts.append(now)
    session[key] = attempts
    return False


def clear_attempts(key):
    session.pop(key, None)
