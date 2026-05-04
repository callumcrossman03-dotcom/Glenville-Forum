from io import BytesIO

from PIL import Image
from pathlib import Path

from app.models import Comment, Community, Notification, Post, Report, SavedPost, User, db
from tests.conftest import login


def make_post(title="Existing post", author="admin", community="campus-life", **kwargs):
    user = User.query.filter_by(username=author).first()
    group = Community.query.filter_by(slug=community).first()
    post = Post(title=title, body="Body text", post_type="discussion", author=user, community=group, **kwargs)
    db.session.add(post)
    db.session.commit()
    return post


def test_login_and_logout(client):
    response = login(client, "student")
    assert response.status_code == 200
    assert b"Signed in successfully" in response.data

    response = client.post("/auth/logout", follow_redirects=True)
    assert response.status_code == 200
    assert b"Signed out" in response.data


def test_comment_creates_notification_for_post_author(client, app):
    with app.app_context():
        post = make_post()
        post_id = post.id

    login(client, "student")
    response = client.post(f"/posts/{post_id}", data={"body": "This helped me."}, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        assert Comment.query.filter_by(post_id=post_id).count() == 1
        admin = User.query.filter_by(username="admin").first()
        assert Notification.query.filter_by(user_id=admin.id, post_id=post_id).count() == 1


def test_save_post_toggle(client, app):
    with app.app_context():
        post = make_post()
        post_id = post.id

    login(client, "student")
    first = client.post(f"/posts/{post_id}/save", headers={"X-Requested-With": "fetch"})
    second = client.post(f"/posts/{post_id}/save", headers={"X-Requested-With": "fetch"})

    assert first.status_code == 200
    assert first.get_json()["saved"] is True
    assert second.status_code == 200
    assert second.get_json()["saved"] is False
    with app.app_context():
        assert SavedPost.query.filter_by(post_id=post_id).count() == 0


def test_image_upload_accepts_real_png(client, app):
    image_bytes = BytesIO()
    Image.new("RGB", (16, 16), "#005bab").save(image_bytes, format="PNG")
    image_bytes.seek(0)
    with app.app_context():
        community_id = Community.query.filter_by(slug="campus-life").first().id
        upload_folder = Path(app.config["UPLOAD_FOLDER"])

    login(client, "student")
    response = client.post(
        "/posts/new",
        data={
            "title": "Photo post",
            "body": "Tiny real png",
            "post_type": "image",
            "community_id": community_id,
            "image": (image_bytes, "photo.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        post = Post.query.filter_by(title="Photo post").first()
        assert post.image_filename
        assert (upload_folder / post.image_filename).exists()


def test_locked_post_blocks_regular_comment(client, app):
    with app.app_context():
        post = make_post(is_locked=True)
        post_id = post.id

    login(client, "student")
    response = client.post(f"/posts/{post_id}", data={"body": "Should not land"})
    assert response.status_code == 403
    with app.app_context():
        assert Comment.query.filter_by(post_id=post_id).count() == 0


def test_admin_can_remove_reported_post(client, app):
    with app.app_context():
        post = make_post()
        reporter = User.query.filter_by(username="student").first()
        report = Report(reporter=reporter, post=post, reason="Spam")
        db.session.add(report)
        db.session.commit()
        post_id = post.id
        report_id = report.id

    login(client, "admin")
    response = client.post(f"/admin/reports/{report_id}/remove", follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Post, post_id) is None


def test_security_headers_are_present(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "Content-Security-Policy" in response.headers


def test_login_rate_limit(client):
    for _ in range(6):
        client.post("/auth/login", data={"username_or_email": "student", "password": "wrong"})
    response = client.post("/auth/login", data={"username_or_email": "student", "password": "wrong"})
    assert response.status_code == 429
