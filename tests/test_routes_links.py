import re
from html.parser import HTMLParser

from app.models import Comment, Community, Event, Message, Notification, Post, Report, User, db
from tests.conftest import login


class InternalLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ("href", "data-href"):
            value = attrs.get(name)
            if value and value.startswith("/") and not value.startswith("/static/"):
                self.links.add(value.split("#", 1)[0] or "/")


def create_smoke_content():
    admin = User.query.filter_by(username="admin").first()
    student = User.query.filter_by(username="student").first()
    campus = Community.query.filter_by(slug="campus-life").first()
    events = Community.query.filter_by(slug="events").first()
    post = Post(title="Smoke test post", body="Useful campus update", post_type="announcement", is_pinned=True, author=admin, community=campus)
    event_post = Post(title="Smoke event post", body="Event body", post_type="discussion", author=student, community=events)
    db.session.add_all([post, event_post])
    db.session.flush()
    comment = Comment(body="Thanks for sharing", author=student, post=post)
    db.session.add(comment)
    db.session.flush()
    db.session.add_all([
        Notification(user=admin, actor=student, message="student commented on your post.", post=post, comment=comment),
        Message(sender=student, recipient=admin, body="Hi admin"),
        Event(title="Smoke event", description="A campus event", location="Library", starts_at=post.created_at, author=admin, community=events),
        Report(reporter=student, post=event_post, reason="Smoke report"),
    ])
    db.session.commit()
    return post.id, comment.id


def test_health_check(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_core_pages_and_internal_links_render(client, app):
    with app.app_context():
        post_id, comment_id = create_smoke_content()

    public_pages = ["/", "/communities", "/c/campus-life", "/about-project", "/auth/login", "/auth/register", f"/posts/{post_id}"]
    for path in public_pages:
        response = client.get(path)
        assert response.status_code == 200, path

    login(client, "admin")
    protected_pages = [
        "/",
        "/communities",
        "/communities/new",
        "/c/campus-life",
        "/onboarding",
        "/users/admin",
        "/settings",
        "/saved",
        "/notifications",
        "/posts/new",
        f"/posts/{post_id}",
        f"/posts/{post_id}/edit",
        f"/comments/{comment_id}/edit",
        "/events",
        "/messages",
        "/admin",
        "/about-project",
    ]
    seen_links = set()
    for path in protected_pages:
        response = client.get(path)
        assert response.status_code == 200, path
        parser = InternalLinkParser()
        parser.feed(response.get_data(as_text=True))
        seen_links.update(parser.links)

    skip_prefixes = ("/posts/new?",)
    for link in sorted(seen_links):
        if any(link.startswith(prefix) for prefix in skip_prefixes):
            continue
        response = client.get(link)
        assert response.status_code in {200, 302}, link


def test_no_obvious_copy_typos_in_rendered_homepage(client):
    response = client.get("/")
    text = re.sub(r"\s+", " ", response.get_data(as_text=True)).lower()
    forbidden = ["glenvillle", "camups", "comun", "ypu", "semel", "collage"]
    assert not any(word in text for word in forbidden)
