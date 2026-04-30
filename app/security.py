import secrets
from urllib.parse import urlparse

from flask import abort, request, session


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
    if request.method != "POST":
        return
    sent_token = request.form.get("_csrf_token")
    if not sent_token or sent_token != session.get("_csrf_token"):
        abort(400, description="Invalid CSRF token.")
