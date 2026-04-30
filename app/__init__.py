import os
from datetime import datetime, timezone

from flask import Flask
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from .models import Comment, Community, CommunityMembership, Event, Message, Notification, Post, User, Vote, db
from .security import csrf_token, protect_from_csrf


migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config.setdefault("UPLOAD_FOLDER", os.path.join(app.static_folder, "uploads"))
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    migrate.init_app(app, db)
    app.before_request(protect_from_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        return response

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "warning"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_notification_count():
        if not current_user.is_authenticated:
            return {"unread_notification_count": 0}
        count = Notification.query.filter_by(user_id=current_user.id, read_at=None).count()
        return {"unread_notification_count": count}

    from .auth import auth_bp
    from .forum import forum_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(forum_bp)

    @app.cli.command("init-db")
    def init_db_command():
        """Create database tables."""
        db.create_all()
        seed_default_communities()
        print("Database tables created.")

    @app.cli.command("reset-db")
    def reset_db_command():
        """Drop and recreate database tables."""
        db.drop_all()
        db.create_all()
        seed_default_communities()
        print("Database reset complete.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Create demo users, posts, comments, votes, events, and messages."""
        seed_demo_data()
        print("Demo data created.")

    return app


def seed_default_communities():
    defaults = [
        ("Campus Life", "campus-life", "Dorms, dining, events, and everyday life at Glenville State.", "GS"),
        ("Classes", "classes", "Talk about courses, professors, registration, and study tips.", "CL"),
        ("Questions", "questions", "Ask for help, advice, and second opinions.", "?"),
        ("Athletics", "athletics", "Pioneers sports, intramurals, training, and game day threads.", "AT"),
        ("Clubs", "clubs", "Student organizations, meetups, volunteer work, and club announcements.", "CB"),
        ("Buy Sell Trade", "buy-sell-trade", "Textbooks, furniture, rides, tickets, and student deals.", "$"),
        ("Housing", "housing", "Roommates, residence halls, apartments, and housing questions.", "HM"),
        ("Events", "events", "Campus events, local plans, deadlines, and things to do nearby.", "EV"),
        ("Food", "food", "Dining hall thoughts, local restaurants, coffee, and late-night food.", "FD"),
        ("Showcase", "showcase", "Share projects, wins, experiments, and discoveries.", "SH"),
    ]
    for name, slug, description, icon in defaults:
        community = Community.query.filter_by(slug=slug).first()
        if community is None:
            db.session.add(Community(name=name, slug=slug, description=description, icon=icon))
        else:
            community.icon = icon
    db.session.commit()


def get_or_create_user(username, email, password, display_name, bio, avatar_color, is_admin=False):
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(
            username=username,
            email=email,
            display_name=display_name,
            bio=bio,
            avatar_color=avatar_color,
            is_admin=is_admin,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
    return user


def seed_demo_data():
    seed_default_communities()
    admin = get_or_create_user(
        "admin",
        "admin@glenville.example",
        "password123",
        "Glenville Admin",
        "Campus forum moderator.",
        "#005bab",
        True,
    )
    ross = get_or_create_user("ross", "ross@example.com", "password123", "Ross", "Business major. Always looking for campus events.", "#1d75d8")
    maya = get_or_create_user("maya", "maya@example.com", "password123", "Maya", "Biology student and coffee enthusiast.", "#0f8b8d")
    jordan = get_or_create_user("jordan", "jordan@example.com", "password123", "Jordan", "Pioneers fan and intramural regular.", "#5833a8")
    db.session.flush()

    communities = {community.slug: community for community in Community.query.all()}
    for user in [admin, ross, maya, jordan]:
        for slug in ["campus-life", "classes", "events"]:
            if CommunityMembership.query.filter_by(user_id=user.id, community_id=communities[slug].id).first() is None:
                db.session.add(CommunityMembership(user=user, community=communities[slug]))

    demo_posts = [
        ("Welcome to Glenville State Forums", "Use this space for campus questions, events, classes, clubs, and student life. Keep it helpful and respectful.", "announcement", admin, "campus-life", True),
        ("Best quiet study spots?", "I am trying to find somewhere quieter than the usual library tables. Any favorite corners on campus?", "question", maya, "classes", False),
        ("Friday pickup basketball", "A few of us are meeting at the gym Friday at 6. Anyone can join.", "discussion", jordan, "athletics", False),
        ("Selling intro psych textbook", "Used but clean. Happy to meet near the student center.", "discussion", ross, "buy-sell-trade", False),
        ("Club fair next week", "If your organization is tabling, drop details here so new students can find you.", "announcement", admin, "events", True),
    ]
    created_posts = []
    for title, body, post_type, author, slug, pinned in demo_posts:
        post = Post.query.filter_by(title=title).first()
        if post is None:
            post = Post(title=title, body=body, post_type=post_type, author=author, community=communities[slug], is_pinned=pinned)
            db.session.add(post)
            db.session.flush()
        created_posts.append(post)

    if Comment.query.count() == 0:
        db.session.add(Comment(body="This is exactly what campus needed.", author=ross, post=created_posts[0]))
        parent = Comment(body="The third floor near the windows is usually calm.", author=ross, post=created_posts[1])
        db.session.add(parent)
        db.session.flush()
        db.session.add(Comment(body="Seconding this. Bring headphones though.", author=jordan, post=created_posts[1], parent=parent))

    if Vote.query.count() == 0:
        for post in created_posts:
            db.session.add(Vote(user=admin, post=post, value=1))
            if post.author != maya:
                db.session.add(Vote(user=maya, post=post, value=1))
            if post.author != jordan:
                db.session.add(Vote(user=jordan, post=post, value=1))

    if Event.query.count() == 0:
        db.session.add(
            Event(
                title="Student Organization Fair",
                description="Meet clubs, teams, and campus groups.",
                location="Student Center",
                starts_at=datetime(2026, 5, 3, 15, 0, tzinfo=timezone.utc),
                author=admin,
                community=communities["events"],
            )
        )

    if Message.query.count() == 0:
        db.session.add(Message(sender=admin, recipient=ross, body="Thanks for helping test the campus forum."))

    db.session.commit()
