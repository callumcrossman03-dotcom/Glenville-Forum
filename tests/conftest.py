import shutil
import tempfile

import pytest

from app import create_app
from app.models import Community, User, db
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app():
    upload_dir = tempfile.mkdtemp(prefix="glenville-test-uploads-")
    app = create_app(TestConfig)
    app.config["UPLOAD_FOLDER"] = upload_dir
    with app.app_context():
        db.create_all()
        seed = Community(name="Campus Life", slug="campus-life", description="Campus talk", icon="GS")
        other = Community(name="Events", slug="events", description="Events", icon="EV")
        admin = User(username="admin", email="admin@example.com", is_admin=True)
        admin.set_password("password123")
        user = User(username="student", email="student@example.com")
        user.set_password("password123")
        mod = User(username="mod", email="mod@example.com")
        mod.set_password("password123")
        db.session.add_all([seed, other, admin, user, mod])
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()
    shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username="student", password="password123"):
    return client.post("/auth/login", data={"username_or_email": username, "password": password}, follow_redirects=True)
