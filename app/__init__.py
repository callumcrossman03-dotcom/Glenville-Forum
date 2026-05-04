import os
from pathlib import Path
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

from flask import Flask, render_template
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from .models import Comment, Community, CommunityMembership, CommunityModerator, Event, Message, Notification, PollOption, PollVote, Post, User, Vote, db
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
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline'; "
            "font-src 'self' https://cdn.jsdelivr.net data:; "
            "connect-src 'self'; "
            "frame-ancestors 'self';"
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
            return {"unread_notification_count": 0, "recent_unread_notifications": []}
        unread_query = Notification.query.filter_by(user_id=current_user.id, read_at=None)
        count = unread_query.count()
        recent = unread_query.order_by(Notification.created_at.desc()).limit(5).all()
        return {"unread_notification_count": count, "recent_unread_notifications": recent}

    from .auth import auth_bp
    from .forum import forum_bp, can_moderate_post, poll_state
    app.jinja_env.globals["poll_state"] = poll_state
    app.jinja_env.globals["can_moderate_post"] = can_moderate_post

    app.register_blueprint(auth_bp)
    app.register_blueprint(forum_bp)

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, title="Bad request", message="Something about that request was not valid. Please go back and try again."), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("error.html", code=403, title="Access denied", message="You do not have permission to view or change that page."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, title="Page not found", message="That page does not exist or has moved."), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template("error.html", code=413, title="Upload too large", message="That upload is too large. Try a smaller image."), 413

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template("error.html", code=500, title="Server error", message="Something went wrong. Please try again in a moment."), 500

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



DEMO_IMAGES = {
    "demo-campus-sunrise.jpg": ("Campus Sunrise", "Morning walk before class", (0, 91, 171), (255, 214, 102)),
    "demo-club-fair.jpg": ("Club Fair", "Tables, signups, and student groups", (0, 91, 171), (34, 197, 94)),
    "demo-game-day.jpg": ("Game Day", "Pioneers student section", (0, 63, 125), (88, 166, 255)),
    "demo-study-night.jpg": ("Study Night", "Library lights and finals notes", (16, 35, 63), (219, 234, 254)),
    "demo-coffee-lunch.jpg": ("Campus Coffee", "Quick lunch between classes", (11, 116, 209), (245, 158, 11)),
    "demo-dorm-setup.jpg": ("Dorm Setup", "Storage hacks and desk ideas", (23, 54, 83), (20, 184, 166)),
    "demo-showcase.jpg": ("Student Showcase", "Projects, posters, and creative work", (88, 51, 168), (236, 72, 153)),
}


def ensure_demo_images():
    uploads = Path(__file__).resolve().parent / "static" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 54)
        body_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
        small_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)
    except OSError:
        title_font = body_font = small_font = ImageFont.load_default()

    for filename, (title, subtitle, primary, accent) in DEMO_IMAGES.items():
        path = uploads / filename
        if path.exists():
            continue
        width, height = 1200, 720
        image = Image.new("RGB", (width, height), primary)
        draw = ImageDraw.Draw(image)
        for y in range(height):
            blend = y / height
            color = tuple(int(primary[i] * (1 - blend) + accent[i] * blend) for i in range(3))
            draw.line((0, y, width, y), fill=color)

        draw.rounded_rectangle((70, 70, width - 70, height - 70), radius=34, fill=(255, 255, 255), outline=(225, 236, 250), width=4)
        draw.rectangle((70, 70, width - 70, 190), fill=(0, 91, 171))
        draw.text((110, 105), "GLENVILLE STATE FORUMS", fill=(255, 255, 255), font=small_font)
        draw.text((110, 265), title, fill=(16, 35, 63), font=title_font)
        draw.text((112, 340), subtitle, fill=(82, 103, 128), font=body_font)

        for index in range(5):
            x = 110 + index * 190
            y = 465 + (index % 2) * 30
            draw.rounded_rectangle((x, y, x + 132, y + 86), radius=18, fill=(232, 242, 255), outline=(196, 216, 234), width=2)
            draw.ellipse((x + 18, y + 22, x + 48, y + 52), fill=accent)
            draw.line((x + 62, y + 30, x + 116, y + 30), fill=(96, 114, 138), width=5)
            draw.line((x + 62, y + 48, x + 104, y + 48), fill=(148, 163, 184), width=4)

        image.save(path, "JPEG", quality=88, optimize=True)

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
    taylor = get_or_create_user("taylor", "taylor@example.com", "password123", "Taylor", "Education major, resident assistant, and planner person.", "#0a6fb3")
    sam = get_or_create_user("sam", "sam@example.com", "password123", "Sam", "Computer science student who asks too many questions in a good way.", "#1f8a70")
    priya = get_or_create_user("priya", "priya@example.com", "password123", "Priya", "Nursing student, commuter, and coffee cart loyalist.", "#a23e72")
    eli = get_or_create_user("eli", "eli@example.com", "password123", "Eli", "Theatre club, intramurals, and whatever is happening this weekend.", "#6b5bd6")
    noah = get_or_create_user("noah", "noah@example.com", "password123", "Noah", "Accounting major selling textbooks and finding study groups.", "#2563eb")
    grace = get_or_create_user("grace", "grace@example.com", "password123", "Grace", "Student Government and campus event enthusiast.", "#d97706")
    db.session.flush()

    users = [admin, ross, maya, jordan, taylor, sam, priya, eli, noah, grace]
    communities = {community.slug: community for community in Community.query.all()}
    memberships = {
        admin: ["campus-life", "classes", "events", "questions", "clubs"],
        ross: ["campus-life", "classes", "events", "buy-sell-trade", "food"],
        maya: ["campus-life", "classes", "questions", "food", "showcase"],
        jordan: ["campus-life", "athletics", "events", "housing"],
        taylor: ["campus-life", "housing", "events", "questions"],
        sam: ["classes", "questions", "showcase", "clubs"],
        priya: ["classes", "food", "questions", "events"],
        eli: ["clubs", "events", "athletics", "campus-life"],
        noah: ["buy-sell-trade", "classes", "housing", "campus-life"],
        grace: ["events", "clubs", "campus-life", "questions"],
    }
    for user, slugs in memberships.items():
        for slug in slugs:
            if CommunityMembership.query.filter_by(user_id=user.id, community_id=communities[slug].id).first() is None:
                db.session.add(CommunityMembership(user=user, community=communities[slug]))

    demo_moderators = {
        grace: [("events", "owner"), ("clubs", "moderator")],
        jordan: [("athletics", "owner")],
        sam: [("classes", "moderator"), ("showcase", "moderator")],
        taylor: [("housing", "moderator")],
    }
    for user, assignments in demo_moderators.items():
        for slug, role in assignments:
            if CommunityModerator.query.filter_by(user_id=user.id, community_id=communities[slug].id).first() is None:
                db.session.add(CommunityModerator(user=user, community=communities[slug], role=role))

    demo_posts = [
        ("Welcome to Glenville State Forums", "Use this space for campus questions, events, classes, clubs, and student life. Keep it helpful and respectful.", "announcement", admin, "campus-life", True),
        ("Club fair next week", "If your organization is tabling, drop details here so new students can find you. We will pin updates as groups add times and table locations.", "announcement", admin, "events", True),
        ("Best quiet study spots?", "I am trying to find somewhere quieter than the usual library tables. Any favorite corners on campus? Bonus points for outlets and decent lighting.", "question", maya, "classes", False),
        ("Friday pickup basketball", "A few of us are meeting at the gym Friday at 6. Anyone can join. Bring a light and dark shirt if you can.", "discussion", jordan, "athletics", False),
        ("Selling intro psych textbook", "Used but clean. Happy to meet near the student center. Asking 25 or best offer.", "discussion", ross, "buy-sell-trade", False),
        ("Dining hall breakfast rankings", "Current top three: biscuits, potatoes, then the waffle station. I will accept arguments for cereal only if you bring evidence.", "discussion", priya, "food", False),
        ("Anyone need a roommate for fall?", "Looking for someone who keeps a regular schedule and is okay with quiet weeknights. Message me if you are also searching.", "question", taylor, "housing", False),
        ("Computer science study group", "A few of us are reviewing Python, Flask, and database basics on Tuesday evening. Beginners welcome.", "discussion", sam, "classes", False),
        ("Theatre club auditions", "Auditions are Thursday in the fine arts building. No prepared monologue required, just show up and read with us.", "announcement", eli, "clubs", False),
        ("Commuter parking tips?", "What time does the good parking disappear? I am trying to stop learning this lesson the hard way.", "question", priya, "questions", False),
        ("Intramural soccer signups", "Teams are forming this week. Drop your position or skill level if you want to get picked up by a group.", "announcement", jordan, "athletics", False),
        ("Free desk lamp", "Works fine, just switched setups. First person who can meet by the residence halls can have it.", "discussion", noah, "buy-sell-trade", False),
        ("Favorite local coffee order", "Trying to rotate away from my usual iced vanilla. What are people getting before morning classes?", "discussion", maya, "food", False),
        ("Student Government open forum", "Bring concerns, ideas, or questions about campus services. We are collecting notes for the next meeting.", "announcement", grace, "events", False),
        ("Showcase your final projects", "Drop screenshots, links, posters, videos, or anything you are proud of from this semester.", "discussion", sam, "showcase", False),
        ("Laundry room etiquette", "Can we agree on moving clothes only after giving people a reasonable window? Curious what everyone thinks is fair.", "discussion", taylor, "housing", False),
        ("BIO lab practical tips", "For anyone who already took the practical: what helped you study without just staring at slides for hours?", "question", maya, "classes", False),
        ("Weekend hiking group", "Weather looks good Saturday. Thinking of a short morning hike and lunch after. Anyone interested?", "discussion", eli, "campus-life", False),
        ("Lost blue water bottle", "Pretty sure I left it near the library computers. It has a Glenville sticker and a dent in the lid.", "question", ross, "questions", False),
        ("Pioneers game thread", "Use this for score updates, ride plans, and postgame thoughts. Go Pioneers.", "discussion", jordan, "athletics", False),
        ("Volunteer hours opportunity", "Local cleanup event needs student volunteers this month. Counts for several club service requirements.", "announcement", grace, "clubs", False),
        ("Accounting exam review", "Making a shared formula sheet and practice problem list. Reply if you want the study doc.", "discussion", noah, "classes", False),
        ("Best place for a quick lunch", "I have 25 minutes between classes on Wednesday. What is actually realistic?", "question", ross, "food", False),
        ("Dorm room setup ideas", "Post your storage hacks. I am trying to make my desk less chaotic before finals.", "discussion", taylor, "housing", False),
        ("Campus photography thread", "Share your favorite campus photos from this week. Sunrise, game day, study spots, all of it.", "image", eli, "showcase", False),
        ("Which dining hall theme night should come back?", "Vote for the one you would actually show up for next month.", "poll", priya, "food", False),
        ("Best time for a finals study meetup?", "Trying to pick a time that works for the most people before finals week.", "poll", sam, "classes", False),
        ("What should the next campus event be?", "Student Government is collecting ideas for a low-stress spring event.", "poll", grace, "events", False),
    ]

    ensure_demo_images()
    demo_images_by_title = {
        "Club fair next week": "demo-club-fair.jpg",
        "Friday pickup basketball": "demo-game-day.jpg",
        "Dining hall breakfast rankings": "demo-coffee-lunch.jpg",
        "Computer science study group": "demo-study-night.jpg",
        "Student Government open forum": "demo-campus-sunrise.jpg",
        "Dorm room setup ideas": "demo-dorm-setup.jpg",
        "Campus photography thread": "demo-showcase.jpg",
    }

    demo_poll_options = {
        "Which dining hall theme night should come back?": ["Breakfast for dinner", "Taco night", "Pasta bar", "Wing night"],
        "Best time for a finals study meetup?": ["Monday evening", "Tuesday afternoon", "Wednesday night", "Saturday morning"],
        "What should the next campus event be?": ["Outdoor movie", "Game night", "Food truck day", "Open mic"],
    }

    created_posts = []
    for title, body, post_type, author, slug, pinned in demo_posts:
        post = Post.query.filter_by(title=title).first()
        image_filename = demo_images_by_title.get(title)
        if post is None:
            post = Post(title=title, body=body, post_type=post_type, image_filename=image_filename, author=author, community=communities[slug], is_pinned=pinned)
            db.session.add(post)
            db.session.flush()
        elif image_filename and not post.image_filename:
            post.image_filename = image_filename
        if post_type == "poll" and not post.poll_options:
            for index, option in enumerate(demo_poll_options.get(title, [])):
                db.session.add(PollOption(post=post, text=option, position=index))
        created_posts.append(post)

    comments_by_title = {
        "Welcome to Glenville State Forums": [(ross, "This is exactly what campus needed."), (grace, "Pinned this in our group chat too."), (sam, "The community pages already make it easier to find stuff.")],
        "Best quiet study spots?": [(ross, "The third floor near the windows is usually calm."), (jordan, "Seconding this. Bring headphones though."), (priya, "The back corner by the reference shelves is underrated.")],
        "Club fair next week": [(eli, "Theatre club will be there with signup sheets."), (grace, "Student Government has a table near the entrance."), (maya, "Biology club is bringing candy, allegedly.")],
        "Dining hall breakfast rankings": [(ross, "Waffle station is number one and I will not be moved."), (taylor, "Potatoes depend entirely on the day."), (priya, "This is why we need weekly rankings.")],
        "Computer science study group": [(maya, "Can non-CS people come if we are just learning basics?"), (sam, "Absolutely. We are starting from routes/templates."), (admin, "Love seeing study groups here.")],
        "Intramural soccer signups": [(eli, "I can play midfield badly but enthusiastically."), (jordan, "That is the official intramural skill level."), (grace, "Please post the schedule when you have it.")],
        "Student Government open forum": [(taylor, "Can housing questions go here too?"), (grace, "Yes, bring them. We will route notes to the right office."), (noah, "Parking and dining are going to come up for sure.")],
        "Showcase your final projects": [(sam, "I want to see posters from the science classes."), (maya, "I can share our lab infographic after presentations."), (eli, "Theatre set photos count, right?")],
        "Lost blue water bottle": [(admin, "Check with the front desk too."), (ross, "Found it! Someone turned it in at the library." )],
        "Pioneers game thread": [(jordan, "Tipoff is 7, student section should show up early."), (eli, "Bringing face paint. This is not a joke."), (grace, "SGA has spirit towels while they last.")],
        "Accounting exam review": [(noah, "I uploaded the first practice set to the shared doc."), (ross, "Can you add depreciation examples?"), (noah, "Yes, adding those tonight.")],
    }
    existing_comment_count = Comment.query.count()
    if existing_comment_count < 20:
        for post in created_posts:
            for author, body in comments_by_title.get(post.title, []):
                if Comment.query.filter_by(post_id=post.id, user_id=author.id, body=body).first() is None:
                    db.session.add(Comment(body=body, author=author, post=post))
        db.session.flush()
        quiet_post = Post.query.filter_by(title="Best quiet study spots?").first()
        parent = Comment.query.filter_by(post=quiet_post, body="The third floor near the windows is usually calm.").first()
        if parent and Comment.query.filter_by(parent=parent, body="Seconding this. Bring headphones though.").first() is None:
            db.session.add(Comment(body="Seconding this. Bring headphones though.", author=jordan, post=quiet_post, parent=parent))

    if PollVote.query.count() < 10:
        for post in [item for item in created_posts if item.post_type == "poll"]:
            options = list(post.poll_options)
            if options:
                for index, user in enumerate(users):
                    if PollVote.query.filter_by(user_id=user.id, post_id=post.id).first() is None:
                        db.session.add(PollVote(user=user, post=post, option=options[index % len(options)]))

    if Vote.query.count() < 80:
        for index, post in enumerate(created_posts):
            for user in users:
                if user.id == post.author.id:
                    continue
                if Vote.query.filter_by(user_id=user.id, post_id=post.id).first() is None:
                    value = -1 if (index + user.id) % 11 == 0 else 1
                    db.session.add(Vote(user=user, post=post, value=value))
        for comment in Comment.query.limit(60).all():
            for user in users[:5]:
                if user.id != comment.author.id and Vote.query.filter_by(user_id=user.id, comment_id=comment.id).first() is None:
                    db.session.add(Vote(user=user, comment=comment, value=1))

    event_seed = [
        ("Student Organization Fair", "Meet clubs, teams, and campus groups.", "Student Center", datetime(2026, 5, 3, 15, 0, tzinfo=timezone.utc), admin, "events"),
        ("Finals Study Night", "Quiet rooms, snacks, peer tutors, and extended library hours.", "Library", datetime(2026, 5, 6, 18, 0, tzinfo=timezone.utc), grace, "classes"),
        ("Pioneers Home Game", "Student section meetup before tipoff.", "Waco Center", datetime(2026, 5, 8, 19, 0, tzinfo=timezone.utc), jordan, "athletics"),
        ("Open Mic Night", "Music, poetry, comedy, and quick performances welcome.", "Student Center", datetime(2026, 5, 10, 20, 0, tzinfo=timezone.utc), eli, "events"),
        ("Volunteer Cleanup", "Service hours available. Gloves and supplies provided.", "Downtown meetup point", datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc), grace, "clubs"),
        ("Resume Workshop", "Bring a draft resume or start from scratch with career services.", "Career Services", datetime(2026, 5, 14, 16, 0, tzinfo=timezone.utc), admin, "events"),
    ]
    for title, description, location, starts_at, author, slug in event_seed:
        if Event.query.filter_by(title=title).first() is None:
            db.session.add(Event(title=title, description=description, location=location, starts_at=starts_at, author=author, community=communities[slug]))

    message_seed = [
        (admin, ross, "Thanks for helping test the campus forum."),
        (grace, eli, "Can theatre club send details for the fair post?"),
        (eli, grace, "Yes, I will add audition info tonight."),
        (sam, maya, "Want to join the Flask study group Tuesday?"),
        (maya, sam, "Yes, I need the database part especially."),
        (taylor, noah, "Are you still looking for housing options?"),
    ]
    for sender, recipient, body in message_seed:
        if Message.query.filter_by(sender_id=sender.id, recipient_id=recipient.id, body=body).first() is None:
            db.session.add(Message(sender=sender, recipient=recipient, body=body))

    notification_seed = [
        (ross, grace, "Grace mentioned your event post.", Post.query.filter_by(title="Student Government open forum").first()),
        (maya, sam, "Sam replied to your study question.", Post.query.filter_by(title="Computer science study group").first()),
        (jordan, eli, "Eli replied to your athletics post.", Post.query.filter_by(title="Intramural soccer signups").first()),
    ]
    for user, actor, message, post in notification_seed:
        if post and Notification.query.filter_by(user_id=user.id, actor_id=actor.id, message=message, post_id=post.id).first() is None:
            db.session.add(Notification(user=user, actor=actor, message=message, post=post))

    db.session.commit()
