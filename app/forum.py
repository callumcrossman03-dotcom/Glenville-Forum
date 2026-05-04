import os
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4

try:
    from PIL import Image
except ImportError:  # Pillow is optional locally, but recommended for production uploads.
    Image = None

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.utils import secure_filename

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .models import Comment, Community, CommunityMembership, CommunityModerator, Event, Message, Notification, PollOption, PollVote, Post, Report, SavedPost, User, Vote, db


forum_bp = Blueprint("forum", __name__)
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
IMAGE_SIGNATURES = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
}
POSTS_PER_PAGE = 8


def get_or_404(model, item_id):
    item = db.session.get(model, item_id)
    if item is None:
        abort(404)
    return item


def can_moderate_community(community):
    if not current_user.is_authenticated:
        return False
    if current_user.is_admin:
        return True
    community_id = community.id if hasattr(community, "id") else community
    return CommunityModerator.query.filter_by(user_id=current_user.id, community_id=community_id).first() is not None


def can_moderate_post(post):
    return can_moderate_community(post.community_id)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(**kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(**kwargs)

    return wrapped_view


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def image_extension(filename):
    if not allowed_image(filename):
        return None
    extension = filename.rsplit(".", 1)[1].lower()
    return "jpg" if extension == "jpeg" else extension


def image_signature_matches(file, extension):
    file.stream.seek(0)
    header = file.stream.read(16)
    file.stream.seek(0)
    if extension == "webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    return any(header.startswith(signature) for signature in IMAGE_SIGNATURES.get(extension, ()))


def save_post_image(file):
    if file is None or not file.filename:
        return None
    original = secure_filename(file.filename)
    extension = image_extension(original)
    if not extension or not image_signature_matches(file, extension):
        raise ValueError("Images must be real PNG, JPG, GIF, or WEBP files.")

    filename = f"{uuid4().hex}.{extension}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    destination = Path(upload_folder) / filename

    if Image is None or extension == "gif":
        file.save(destination)
        return filename

    try:
        with Image.open(file.stream) as image:
            image.verify()
        file.stream.seek(0)
        with Image.open(file.stream) as image:
            image = image.convert("RGB") if extension in {"jpg", "webp"} else image.convert("RGBA")
            image.thumbnail((1600, 1600))
            save_format = "JPEG" if extension == "jpg" else extension.upper()
            save_kwargs = {"optimize": True}
            if save_format in {"JPEG", "WEBP"}:
                save_kwargs["quality"] = 82
            image.save(destination, save_format, **save_kwargs)
    except Exception as exc:
        raise ValueError("That image could not be processed. Try a PNG, JPG, GIF, or WEBP file.") from exc
    finally:
        file.stream.seek(0)

    return filename


def delete_post_image(filename):
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(path):
        os.remove(path)


def poll_options_from_form():
    raw_options = request.form.get("poll_options", "")
    options = []
    seen = set()
    for line in raw_options.splitlines():
        option = line.strip()
        key = option.lower()
        if option and key not in seen:
            options.append(option[:160])
            seen.add(key)
    return options[:8]


def poll_state(post):
    if post.post_type != "poll":
        return {"total": 0, "user_option_id": None}
    total = sum(option.vote_count for option in post.poll_options)
    user_option_id = None
    if current_user.is_authenticated:
        vote = PollVote.query.filter_by(user_id=current_user.id, post_id=post.id).first()
        user_option_id = vote.option_id if vote else None
    return {"total": total, "user_option_id": user_option_id}


def paginate_query(query, page, per_page=POSTS_PER_PAGE):
    total = query.count()
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(max(page, 1), total_pages)
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return items, page, total_pages, total


def slugify(value):
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    return "-".join(part for part in slug.split("-") if part)[:40]


def post_listing_query(sort, community=None, search=None, joined_only=False, author=None, has_image=False, post_type=None):
    vote_totals = (
        db.session.query(Vote.post_id.label("post_id"), func.coalesce(func.sum(Vote.value), 0).label("score"))
        .filter(Vote.post_id.isnot(None))
        .group_by(Vote.post_id)
        .subquery()
    )
    comment_totals = (
        db.session.query(Comment.post_id.label("post_id"), func.count(Comment.id).label("comment_count"))
        .group_by(Comment.post_id)
        .subquery()
    )
    score = func.coalesce(vote_totals.c.score, 0).label("score")
    comment_count = func.coalesce(comment_totals.c.comment_count, 0).label("comment_count")
    query = (
        db.session.query(Post, score, comment_count)
        .options(
            joinedload(Post.author),
            joinedload(Post.community),
            selectinload(Post.comments),
            selectinload(Post.votes),
            selectinload(Post.saves),
            selectinload(Post.poll_options).selectinload(PollOption.votes),
        )
        .outerjoin(vote_totals, vote_totals.c.post_id == Post.id)
        .outerjoin(comment_totals, comment_totals.c.post_id == Post.id)
    )
    if community is not None:
        query = query.filter(Post.community_id == community.id)
    if joined_only and current_user.is_authenticated:
        joined_ids = db.session.query(CommunityMembership.community_id).filter_by(user_id=current_user.id)
        query = query.filter(Post.community_id.in_(joined_ids))
    if search or author:
        query = query.join(User, Post.user_id == User.id)
    if search:
        pattern = f"%{search}%"
        query = query.join(Community, Post.community_id == Community.id).filter(
            or_(Post.title.ilike(pattern), Post.body.ilike(pattern), Community.name.ilike(pattern), User.username.ilike(pattern))
        )
    if author:
        query = query.filter(User.username.ilike(f"%{author}%"))
    if has_image:
        query = query.filter(Post.image_filename.isnot(None))
    if post_type:
        query = query.filter(Post.post_type == post_type)

    if sort == "new":
        return query.order_by(Post.is_pinned.desc(), Post.created_at.desc())
    if sort == "top":
        return query.order_by(Post.is_pinned.desc(), score.desc(), Post.created_at.desc())
    if sort == "comments":
        return query.order_by(Post.is_pinned.desc(), comment_count.desc(), Post.created_at.desc())
    return query.order_by(Post.is_pinned.desc(), score.desc(), comment_count.desc(), Post.created_at.desc())


def trending_posts(limit=5):
    return post_listing_query("hot").limit(limit).all()


def wants_json_response():
    return request.headers.get("X-Requested-With") == "fetch"


def suggested_communities(limit=5):
    post_count = func.count(Post.id).label("post_count")
    return (
        db.session.query(Community, post_count)
        .outerjoin(Post, Post.community_id == Community.id)
        .group_by(Community.id)
        .order_by(post_count.desc(), Community.name.asc())
        .limit(limit)
        .all()
    )


def upcoming_events(limit=4):
    return Event.query.order_by(Event.starts_at.asc()).limit(limit).all()


def notify_user(user, actor, message, post=None, comment=None):
    if user is None or actor is None or user.id == actor.id:
        return
    db.session.add(Notification(user=user, actor=actor, message=message, post=post, comment=comment))


def user_state(post_ids=None, comment_ids=None):
    post_votes = {}
    comment_votes = {}
    saved_posts = set()
    if not current_user.is_authenticated:
        return post_votes, comment_votes, saved_posts
    if post_ids:
        post_votes = {
            vote.post_id: vote.value
            for vote in Vote.query.filter(Vote.user_id == current_user.id, Vote.post_id.in_(post_ids)).all()
        }
        saved_posts = {
            saved.post_id
            for saved in SavedPost.query.filter(SavedPost.user_id == current_user.id, SavedPost.post_id.in_(post_ids)).all()
        }
    if comment_ids:
        comment_votes = {
            vote.comment_id: vote.value
            for vote in Vote.query.filter(Vote.user_id == current_user.id, Vote.comment_id.in_(comment_ids)).all()
        }
    return post_votes, comment_votes, saved_posts


@forum_bp.route("/about-project")
def about_project():
    stats = {
        "users": User.query.count(),
        "posts": Post.query.count(),
        "comments": Comment.query.count(),
        "communities": Community.query.count(),
        "polls": Post.query.filter_by(post_type="poll").count(),
        "events": Event.query.count(),
    }
    return render_template("forum/about_project.html", stats=stats)


@forum_bp.route("/")
def index():
    sort = request.args.get("sort", "hot")
    search = request.args.get("q", "").strip()
    author = request.args.get("author", "").strip()
    post_type = request.args.get("type", "").strip()
    has_image = request.args.get("has_image") == "yes"
    feed = request.args.get("feed", "all")
    page = request.args.get("page", 1, type=int)
    if feed == "joined" and not current_user.is_authenticated:
        flash("Sign in to see your joined communities feed.", "warning")
        return redirect(url_for("auth.login", next=request.full_path))
    communities = Community.query.order_by(Community.name.asc()).all()
    posts_query = post_listing_query(sort, search=search, joined_only=feed == "joined", author=author, has_image=has_image, post_type=post_type or None)
    posts, page, total_pages, total_posts = paginate_query(posts_query, page)
    post_votes, _, saved_posts = user_state(post_ids=[post.id for post, _, _ in posts])
    return render_template(
        "forum/index.html",
        posts=posts,
        sort=sort,
        search=search,
        author=author,
        post_type=post_type,
        has_image=has_image,
        feed=feed,
        page=page,
        total_pages=total_pages,
        total_posts=total_posts,
        communities=communities,
        trending_posts=trending_posts(),
        suggested_communities=suggested_communities(),
        upcoming_events=upcoming_events(),
        post_votes=post_votes,
        saved_posts=saved_posts,
    )


@forum_bp.route("/communities")
def communities():
    communities = Community.query.order_by(Community.name.asc()).all()
    return render_template("forum/communities.html", communities=communities)


@forum_bp.route("/communities/new", methods=("GET", "POST"))
@login_required
def create_community():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        icon = request.form.get("icon", "GS").strip()[:8] or "GS"
        slug = slugify(request.form.get("slug", "") or name)
        if not name or not description or not slug:
            flash("Community name, slug, and description are required.", "error")
        elif Community.query.filter((Community.slug == slug) | (Community.name == name)).first():
            flash("That community name or slug already exists.", "error")
        else:
            community = Community(name=name, slug=slug, description=description, icon=icon, creator=current_user)
            db.session.add(community)
            db.session.flush()
            db.session.add(CommunityMembership(user=current_user, community=community))
            db.session.commit()
            flash("Community created.", "success")
            return redirect(url_for("forum.community_detail", slug=community.slug))
    return render_template("forum/create_community.html")


@forum_bp.route("/c/<slug>")
def community_detail(slug):
    community = Community.query.filter_by(slug=slug).first_or_404()
    sort = request.args.get("sort", "hot")
    search = request.args.get("q", "").strip()
    post_type = request.args.get("type", "").strip()
    has_image = request.args.get("has_image") == "yes"
    page = request.args.get("page", 1, type=int)
    posts, page, total_pages, total_posts = paginate_query(post_listing_query(sort, community, search, has_image=has_image, post_type=post_type or None), page)
    post_votes, _, saved_posts = user_state(post_ids=[post.id for post, _, _ in posts])
    is_joined = False
    if current_user.is_authenticated:
        is_joined = CommunityMembership.query.filter_by(user_id=current_user.id, community_id=community.id).first() is not None
    member_count = CommunityMembership.query.filter_by(community_id=community.id).count()
    pinned_intro = Post.query.filter_by(community_id=community.id, is_pinned=True).order_by(Post.created_at.desc()).first()
    moderator_rows = CommunityModerator.query.filter_by(community_id=community.id).options(joinedload(CommunityModerator.user)).all()
    moderators = [row.user for row in moderator_rows]
    if not moderators:
        moderators = User.query.filter_by(is_admin=True).order_by(User.username.asc()).limit(5).all()
    return render_template(
        "forum/community_detail.html",
        community=community,
        posts=posts,
        sort=sort,
        search=search,
        post_type=post_type,
        has_image=has_image,
        page=page,
        total_pages=total_pages,
        total_posts=total_posts,
        member_count=member_count,
        pinned_intro=pinned_intro,
        moderators=moderators,
        is_joined=is_joined,
        trending_posts=trending_posts(),
        suggested_communities=suggested_communities(),
        upcoming_events=upcoming_events(),
        post_votes=post_votes,
        saved_posts=saved_posts,
    )


@forum_bp.route("/c/<slug>/join", methods=("POST",))
@login_required
def toggle_membership(slug):
    community = Community.query.filter_by(slug=slug).first_or_404()
    existing = CommunityMembership.query.filter_by(user_id=current_user.id, community_id=community.id).first()
    if existing:
        db.session.delete(existing)
        flash(f"You left c/{community.slug}.", "success")
    else:
        db.session.add(CommunityMembership(user=current_user, community=community))
        flash(f"You joined c/{community.slug}.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("forum.community_detail", slug=community.slug))


@forum_bp.route("/onboarding", methods=("GET", "POST"))
@login_required
def onboarding():
    communities = Community.query.order_by(Community.name.asc()).all()
    if request.method == "POST":
        selected_ids = {int(value) for value in request.form.getlist("community_ids") if value.isdigit()}
        for community in communities:
            existing = CommunityMembership.query.filter_by(user_id=current_user.id, community_id=community.id).first()
            if community.id in selected_ids and existing is None:
                db.session.add(CommunityMembership(user=current_user, community=community))
            elif community.id not in selected_ids and existing is not None:
                db.session.delete(existing)
        db.session.commit()
        flash("Your campus feed is personalized.", "success")
        return redirect(url_for("forum.index", feed="joined" if selected_ids else "all"))
    joined_ids = {row.community_id for row in CommunityMembership.query.filter_by(user_id=current_user.id).all()}
    return render_template("forum/onboarding.html", communities=communities, joined_ids=joined_ids)


@forum_bp.route("/users/<username>")
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    post_karma = (
        db.session.query(func.coalesce(func.sum(Vote.value), 0))
        .join(Post, Vote.post_id == Post.id)
        .filter(Post.user_id == user.id)
        .scalar()
    )
    comment_karma = (
        db.session.query(func.coalesce(func.sum(Vote.value), 0))
        .join(Comment, Vote.comment_id == Comment.id)
        .filter(Comment.user_id == user.id)
        .scalar()
    )
    recent_posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).limit(8).all()
    recent_comments = Comment.query.filter_by(user_id=user.id).order_by(Comment.created_at.desc()).limit(8).all()
    joined_communities = (
        Community.query.join(CommunityMembership)
        .filter(CommunityMembership.user_id == user.id)
        .order_by(Community.name.asc())
        .limit(8)
        .all()
    )
    total_karma = (post_karma or 0) + (comment_karma or 0)
    event_count = Event.query.filter_by(user_id=user.id).count()
    badges = []
    if user.is_admin:
        badges.append("Moderator")
    if total_karma >= 10:
        badges.append("Campus Voice")
    if comment_karma and comment_karma >= 5:
        badges.append("Helpful Student")
    if event_count:
        badges.append("Event Organizer")
    if len(recent_posts) >= 5:
        badges.append("Top Contributor")
    if len(joined_communities) >= 3:
        badges.append("Community Member")
    if not badges:
        badges.append("New Member")
    return render_template(
        "forum/profile.html",
        user=user,
        post_karma=post_karma or 0,
        comment_karma=comment_karma or 0,
        total_karma=total_karma,
        badges=badges,
        joined_communities=joined_communities,
        recent_posts=recent_posts,
        recent_comments=recent_comments,
        event_count=event_count,
    )


@forum_bp.route("/settings", methods=("GET", "POST"))
@login_required
def settings():
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        bio = request.form.get("bio", "").strip()
        email = request.form.get("email", "").strip().lower()
        avatar_color = request.form.get("avatar_color", "#005bab").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")

        if not email:
            flash("Email is required.", "error")
        elif User.query.filter(User.email == email, User.id != current_user.id).first():
            flash("That email is already in use.", "error")
        elif new_password and (not current_user.check_password(current_password) or len(new_password) < 8):
            flash("To change password, enter your current password and a new password with at least 8 characters.", "error")
        else:
            current_user.display_name = display_name or None
            current_user.bio = bio or None
            current_user.email = email
            current_user.avatar_color = avatar_color if avatar_color.startswith("#") else "#005bab"
            if new_password:
                current_user.set_password(new_password)
            db.session.commit()
            flash("Settings updated.", "success")
            return redirect(url_for("forum.profile", username=current_user.username))
    return render_template("forum/settings.html")


@forum_bp.route("/saved")
@login_required
def saved_posts():
    saved_rows = (
        SavedPost.query.filter_by(user_id=current_user.id)
        .join(Post)
        .order_by(SavedPost.created_at.desc())
        .all()
    )
    posts = [(saved.post, saved.post.score, len(saved.post.comments)) for saved in saved_rows]
    post_votes, _, saved_ids = user_state(post_ids=[post.id for post, _, _ in posts])
    return render_template(
        "forum/saved.html",
        posts=posts,
        trending_posts=trending_posts(),
        suggested_communities=suggested_communities(),
        upcoming_events=upcoming_events(),
        post_votes=post_votes,
        saved_posts=saved_ids,
    )


@forum_bp.route("/notifications")
@login_required
def notifications():
    category = request.args.get("category", "all")
    query = Notification.query.filter_by(user_id=current_user.id)
    if category == "unread":
        query = query.filter(Notification.read_at.is_(None))
    elif category == "comments":
        query = query.filter(Notification.comment_id.isnot(None))
    elif category == "posts":
        query = query.filter(Notification.post_id.isnot(None), Notification.comment_id.is_(None))
    elif category == "messages":
        query = query.filter(Notification.message.ilike("%message%"))
    items = query.order_by(Notification.created_at.desc()).limit(50).all()
    unread = [item for item in items if item.read_at is None]
    return render_template("forum/notifications.html", notifications=items, unread=unread, category=category)


@forum_bp.route("/notifications/read", methods=("POST",))
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, read_at=None).update({"read_at": datetime.now(timezone.utc)})
    db.session.commit()
    flash("Notifications marked as read.", "success")
    return redirect(url_for("forum.notifications"))


@forum_bp.route("/notifications/<int:notification_id>/read", methods=("POST",))
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    notification.read_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("Notification marked as read.", "success")
    return redirect(request.referrer or url_for("forum.notifications"))


@forum_bp.route("/posts/new", methods=("GET", "POST"))
@login_required
def create_post():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        post_type = request.form.get("post_type", "discussion")
        community_id = request.form.get("community_id", type=int)
        community = db.session.get(Community, community_id) if community_id else None
        image = request.files.get("image")
        poll_options = poll_options_from_form() if post_type == "poll" else []

        if not title or not body:
            flash("A title and post body are required.", "error")
        elif community is None:
            flash("Please choose a community.", "error")
        elif post_type == "poll" and len(poll_options) < 2:
            flash("Polls need at least two different answer choices.", "error")
        elif image and image.filename and not allowed_image(image.filename):
            flash("Images must be PNG, JPG, GIF, or WEBP files.", "error")
        else:
            try:
                image_filename = save_post_image(image)
            except ValueError as error:
                flash(str(error), "error")
                communities = Community.query.order_by(Community.name.asc()).all()
                return render_template("forum/create_post.html", communities=communities, form_data=request.form)
            post = Post(title=title, body=body, post_type=post_type, image_filename=image_filename, author=current_user, community=community)
            db.session.add(post)
            db.session.flush()
            for index, option in enumerate(poll_options):
                db.session.add(PollOption(post=post, text=option, position=index))
            db.session.commit()
            flash("Your post is live.", "success")
            return redirect(url_for("forum.post_detail", post_id=post.id))

    communities = Community.query.order_by(Community.name.asc()).all()
    return render_template("forum/create_post.html", communities=communities, form_data=request.form)


@forum_bp.route("/posts/<int:post_id>/edit", methods=("GET", "POST"))
@login_required
def edit_post(post_id):
    post = get_or_404(Post, post_id)
    if post.author != current_user and not can_moderate_post(post):
        abort(403)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        post_type = request.form.get("post_type", "discussion")
        community_id = request.form.get("community_id", type=int)
        community = db.session.get(Community, community_id) if community_id else None

        if not title or not body:
            flash("A title and post body are required.", "error")
        elif community is None:
            flash("Please choose a community.", "error")
        elif request.files.get("image") and request.files["image"].filename and not allowed_image(request.files["image"].filename):
            flash("Images must be PNG, JPG, GIF, or WEBP files.", "error")
        else:
            post.title = title
            post.body = body
            post.post_type = post_type
            post.community = community
            if request.form.get("remove_image") == "yes":
                delete_post_image(post.image_filename)
                post.image_filename = None
            try:
                image_filename = save_post_image(request.files.get("image"))
            except ValueError as error:
                flash(str(error), "error")
                communities = Community.query.order_by(Community.name.asc()).all()
                return render_template("forum/edit_post.html", post=post, communities=communities)
            if image_filename:
                delete_post_image(post.image_filename)
                post.image_filename = image_filename
            db.session.commit()
            flash("Post updated.", "success")
            return redirect(url_for("forum.post_detail", post_id=post.id))

    communities = Community.query.order_by(Community.name.asc()).all()
    return render_template("forum/edit_post.html", post=post, communities=communities)


@forum_bp.route("/posts/<int:post_id>/delete", methods=("POST",))
@login_required
def delete_post(post_id):
    post = get_or_404(Post, post_id)
    if post.author != current_user and not can_moderate_post(post):
        abort(403)
    delete_post_image(post.image_filename)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "success")
    return redirect(url_for("forum.index"))


@forum_bp.route("/posts/<int:post_id>", methods=("GET", "POST"))
def post_detail(post_id):
    post = get_or_404(Post, post_id)

    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Please sign in before commenting.", "warning")
            return redirect(url_for("auth.login", next=request.path))

        if post.is_locked and not can_moderate_post(post):
            abort(403)

        body = request.form.get("body", "").strip()
        parent_id = request.form.get("parent_id", type=int)
        parent = None
        if parent_id:
            parent = Comment.query.filter_by(id=parent_id, post_id=post.id).first_or_404()
        if not body:
            flash("Comment text is required.", "error")
        else:
            comment = Comment(body=body, author=current_user, post=post, parent=parent)
            db.session.add(comment)
            if parent is not None:
                notify_user(parent.author, current_user, f"{current_user.username} replied to your comment.", post=post, comment=comment)
            else:
                notify_user(post.author, current_user, f"{current_user.username} commented on your post.", post=post, comment=comment)
            db.session.commit()
            flash("Reply added." if parent else "Comment added.", "success")
            return redirect(url_for("forum.post_detail", post_id=post.id))

    comment_sort = request.args.get("comments", "top")
    comment_score = func.coalesce(func.sum(Vote.value), 0)
    comments_query = Comment.query.filter_by(post_id=post.id).outerjoin(Vote, Vote.comment_id == Comment.id).group_by(Comment.id)
    if comment_sort == "new":
        comments_query = comments_query.order_by(Comment.created_at.desc())
    elif comment_sort == "old":
        comments_query = comments_query.order_by(Comment.created_at.asc())
    else:
        comments_query = comments_query.order_by(comment_score.desc(), Comment.created_at.asc())
        comment_sort = "top"
    comments = comments_query.all()
    top_comments = [comment for comment in comments if comment.parent_id is None]
    related_posts = (
        Post.query.filter(Post.id != post.id, Post.community_id == post.community_id)
        .order_by(Post.created_at.desc())
        .limit(4)
        .all()
    )
    post_votes, comment_votes, saved_posts = user_state(post_ids=[post.id], comment_ids=[comment.id for comment in comments])
    return render_template(
        "forum/post_detail.html",
        post=post,
        comments=comments,
        top_comments=top_comments,
        comment_sort=comment_sort,
        related_posts=related_posts,
        trending_posts=trending_posts(),
        suggested_communities=suggested_communities(),
        upcoming_events=upcoming_events(),
        post_votes=post_votes,
        comment_votes=comment_votes,
        saved_posts=saved_posts,
    )


@forum_bp.route("/posts/<int:post_id>/poll", methods=("POST",))
@login_required
def vote_poll(post_id):
    post = get_or_404(Post, post_id)
    if post.post_type != "poll":
        abort(404)
    option_id = request.form.get("option_id", type=int)
    option = PollOption.query.filter_by(id=option_id, post_id=post.id).first()
    if option is None:
        flash("Choose a poll option first.", "error")
        return redirect(url_for("forum.post_detail", post_id=post.id))

    existing = PollVote.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if existing:
        existing.option = option
        message = "Anonymous poll response updated."
    else:
        db.session.add(PollVote(user=current_user, post=post, option=option))
        message = "Anonymous poll response saved."
    db.session.commit()

    if wants_json_response():
        options = []
        total = sum(item.vote_count for item in post.poll_options)
        for item in post.poll_options:
            options.append({"id": item.id, "votes": item.vote_count, "percent": round((item.vote_count / total) * 100) if total else 0})
        return jsonify({"message": message, "total": total, "user_option_id": option.id, "options": options})

    flash(message, "success")
    return redirect(request.referrer or url_for("forum.post_detail", post_id=post.id))


@forum_bp.route("/posts/<int:post_id>/save", methods=("POST",))
@login_required
def save_post(post_id):
    post = get_or_404(Post, post_id)
    existing = SavedPost.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if existing:
        db.session.delete(existing)
        saved = False
        message = "Post removed from saved."
    else:
        db.session.add(SavedPost(user=current_user, post=post))
        saved = True
        message = "Post saved."
    db.session.commit()
    if wants_json_response():
        return jsonify({"saved": saved, "message": message})
    flash(message, "success")
    return redirect(request.referrer or url_for("forum.index"))


@forum_bp.route("/posts/<int:post_id>/report", methods=("POST",))
@login_required
def report_post(post_id):
    post = get_or_404(Post, post_id)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Please include a reason for the report.", "error")
    else:
        db.session.add(Report(reporter=current_user, post=post, reason=reason))
        db.session.commit()
        flash("Report sent to moderators.", "success")
    return redirect(request.referrer or url_for("forum.post_detail", post_id=post.id))


@forum_bp.route("/events", methods=("GET", "POST"))
@login_required
def events():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        starts_at_raw = request.form.get("starts_at", "")
        community_id = request.form.get("community_id", type=int)
        community = db.session.get(Community, community_id) if community_id else None
        try:
            starts_at = datetime.fromisoformat(starts_at_raw)
        except ValueError:
            starts_at = None
        if not title or not description or not location or starts_at is None:
            flash("Event title, description, location, and date/time are required.", "error")
        else:
            db.session.add(Event(title=title, description=description, location=location, starts_at=starts_at, author=current_user, community=community))
            db.session.commit()
            flash("Event added.", "success")
            return redirect(url_for("forum.events"))
    events = Event.query.order_by(Event.starts_at.asc()).all()
    communities = Community.query.order_by(Community.name.asc()).all()
    return render_template("forum/events.html", events=events, communities=communities)


@forum_bp.route("/messages", methods=("GET", "POST"))
@login_required
def messages():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        body = request.form.get("body", "").strip()
        recipient = User.query.filter_by(username=username).first()
        if recipient is None or recipient.id == current_user.id:
            flash("Choose another valid username.", "error")
        elif not body:
            flash("Message text is required.", "error")
        else:
            db.session.add(Message(sender=current_user, recipient=recipient, body=body))
            notify_user(recipient, current_user, f"{current_user.username} sent you a message.")
            db.session.commit()
            flash("Message sent.", "success")
            return redirect(url_for("forum.messages", with_user=recipient.username))

    with_username = request.args.get("with_user", "").strip()
    selected_user = User.query.filter_by(username=with_username).first() if with_username else None
    conversations = (
        User.query.join(Message, or_(Message.sender_id == User.id, Message.recipient_id == User.id))
        .filter(or_(Message.sender_id == current_user.id, Message.recipient_id == current_user.id), User.id != current_user.id)
        .distinct()
        .order_by(User.username.asc())
        .all()
    )
    thread = []
    if selected_user:
        thread = (
            Message.query.filter(
                or_(
                    and_(Message.sender_id == current_user.id, Message.recipient_id == selected_user.id),
                    and_(Message.sender_id == selected_user.id, Message.recipient_id == current_user.id),
                )
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        Message.query.filter_by(sender_id=selected_user.id, recipient_id=current_user.id, read_at=None).update({"read_at": datetime.now(timezone.utc)})
        db.session.commit()
    return render_template("forum/messages.html", conversations=conversations, selected_user=selected_user, thread=thread)


@forum_bp.route("/comments/<int:comment_id>/edit", methods=("GET", "POST"))
@login_required
def edit_comment(comment_id):
    comment = get_or_404(Comment, comment_id)
    if comment.author != current_user and not can_moderate_post(comment.post):
        abort(403)

    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if not body:
            flash("Comment text is required.", "error")
        else:
            comment.body = body
            db.session.commit()
            flash("Comment updated.", "success")
            return redirect(url_for("forum.post_detail", post_id=comment.post_id))

    return render_template("forum/edit_comment.html", comment=comment)


@forum_bp.route("/comments/<int:comment_id>/delete", methods=("POST",))
@login_required
def delete_comment(comment_id):
    comment = get_or_404(Comment, comment_id)
    if comment.author != current_user and not can_moderate_post(comment.post):
        abort(403)
    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()
    flash("Comment deleted.", "success")
    return redirect(url_for("forum.post_detail", post_id=post_id))


@forum_bp.route("/comments/<int:comment_id>/report", methods=("POST",))
@login_required
def report_comment(comment_id):
    comment = get_or_404(Comment, comment_id)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Please include a reason for the report.", "error")
    else:
        db.session.add(Report(reporter=current_user, comment=comment, reason=reason))
        db.session.commit()
        flash("Report sent to moderators.", "success")
    return redirect(url_for("forum.post_detail", post_id=comment.post_id))


@forum_bp.route("/admin")
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).limit(20).all()
    posts = Post.query.order_by(Post.created_at.desc()).limit(20).all()
    comments = Comment.query.order_by(Comment.created_at.desc()).limit(20).all()
    reports = Report.query.filter_by(status="open").order_by(Report.created_at.desc()).all()
    top_communities = suggested_communities(limit=5)
    moderator_rows = CommunityModerator.query.options(joinedload(CommunityModerator.user), joinedload(CommunityModerator.community)).order_by(CommunityModerator.created_at.desc()).all()
    communities = Community.query.order_by(Community.name.asc()).all()
    stats = {
        "users": User.query.count(),
        "posts": Post.query.count(),
        "comments": Comment.query.count(),
        "votes": Vote.query.count(),
        "polls": Post.query.filter_by(post_type="poll").count(),
        "events": Event.query.count(),
        "reports": len(reports),
    }
    return render_template("forum/admin.html", users=users, posts=posts, comments=comments, reports=reports, stats=stats, top_communities=top_communities, moderator_rows=moderator_rows, communities=communities)


@forum_bp.route("/admin/community-moderators", methods=("POST",))
@admin_required
def manage_community_moderator():
    username = request.form.get("username", "").strip()
    community_id = request.form.get("community_id", type=int)
    role = request.form.get("role", "moderator")
    action = request.form.get("action", "add")
    user = User.query.filter_by(username=username).first()
    community = db.session.get(Community, community_id) if community_id else None
    if user is None or community is None:
        flash("Choose a valid user and community.", "error")
    elif role not in {"owner", "moderator"}:
        flash("Choose a valid moderator role.", "error")
    else:
        existing = CommunityModerator.query.filter_by(user_id=user.id, community_id=community.id).first()
        if action == "remove":
            if existing:
                db.session.delete(existing)
                db.session.commit()
                flash(f"Removed {user.username} from c/{community.slug} moderators.", "success")
            else:
                flash("That user is not a moderator for this community.", "warning")
        else:
            if existing:
                existing.role = role
            else:
                db.session.add(CommunityModerator(user=user, community=community, role=role))
            db.session.commit()
            flash(f"{user.username} can now moderate c/{community.slug}.", "success")
    return redirect(url_for("forum.admin_dashboard"))


@forum_bp.route("/admin/users/<int:user_id>/toggle-admin", methods=("POST",))
@admin_required
def toggle_admin(user_id):
    user = get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot remove your own admin access.", "warning")
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash("User admin status updated.", "success")
    return redirect(url_for("forum.admin_dashboard"))


@forum_bp.route("/admin/posts/<int:post_id>/pin", methods=("POST",))
@login_required
def toggle_pin_post(post_id):
    post = get_or_404(Post, post_id)
    if not can_moderate_post(post):
        abort(403)
    post.is_pinned = not post.is_pinned
    db.session.commit()
    flash("Post pinned." if post.is_pinned else "Post unpinned.", "success")
    return redirect(request.referrer or url_for("forum.admin_dashboard"))


@forum_bp.route("/admin/posts/<int:post_id>/lock", methods=("POST",))
@login_required
def toggle_lock_post(post_id):
    post = get_or_404(Post, post_id)
    if not can_moderate_post(post):
        abort(403)
    post.is_locked = not post.is_locked
    db.session.commit()
    flash("Post lock status updated.", "success")
    return redirect(request.referrer or url_for("forum.admin_dashboard"))


@forum_bp.route("/admin/reports/<int:report_id>/<action>", methods=("POST",))
@admin_required
def moderate_report(report_id, action):
    report = get_or_404(Report, report_id)
    if action == "dismiss":
        report.status = "dismissed"
        report.resolved_at = datetime.now(timezone.utc)
        flash("Report dismissed.", "success")
    elif action == "remove":
        if report.post:
            delete_post_image(report.post.image_filename)
            db.session.delete(report.post)
        elif report.comment:
            db.session.delete(report.comment)
        report.status = "removed"
        report.resolved_at = datetime.now(timezone.utc)
        flash("Reported content removed.", "success")
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("forum.admin_dashboard"))


@forum_bp.route("/posts/<int:post_id>/vote", methods=("POST",))
@login_required
def vote_post(post_id):
    post = get_or_404(Post, post_id)
    value = request.form.get("value", type=int)
    if value not in (-1, 1):
        abort(400)
    existing = Vote.query.filter_by(user_id=current_user.id, post_id=post.id).first()

    if existing and existing.value == value:
        db.session.delete(existing)
        user_vote = 0
        message = "Post vote removed."
    elif existing:
        existing.value = value
        user_vote = value
        message = "Post vote changed."
    else:
        db.session.add(Vote(user=current_user, post=post, value=value))
        user_vote = value
        message = "Post voted."

    db.session.commit()
    if wants_json_response():
        return jsonify({"score": post.score, "user_vote": user_vote, "message": message})
    flash(message, "success")
    return redirect(request.referrer or url_for("forum.index"))


@forum_bp.route("/comments/<int:comment_id>/vote", methods=("POST",))
@login_required
def vote_comment(comment_id):
    comment = get_or_404(Comment, comment_id)
    value = request.form.get("value", type=int)
    if value not in (-1, 1):
        abort(400)
    existing = Vote.query.filter_by(user_id=current_user.id, comment_id=comment.id).first()

    if existing and existing.value == value:
        db.session.delete(existing)
        user_vote = 0
        message = "Comment vote removed."
    elif existing:
        existing.value = value
        user_vote = value
        message = "Comment vote changed."
    else:
        db.session.add(Vote(user=current_user, comment=comment, value=value))
        user_vote = value
        message = "Comment voted."

    db.session.commit()
    if wants_json_response():
        return jsonify({"score": comment.score, "user_vote": user_vote, "message": message})
    flash(message, "success")
    return redirect(url_for("forum.post_detail", post_id=comment.post_id))
