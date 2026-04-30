import os
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4

from sqlalchemy import and_, func, or_
from werkzeug.utils import secure_filename

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .models import Comment, Community, CommunityMembership, Event, Message, Notification, Post, Report, SavedPost, User, Vote, db


forum_bp = Blueprint("forum", __name__)
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
POSTS_PER_PAGE = 8


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


def save_post_image(file):
    if file is None or not file.filename:
        return None
    original = secure_filename(file.filename)
    extension = original.rsplit(".", 1)[1].lower()
    filename = f"{uuid4().hex}.{extension}"
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
    return filename


def delete_post_image(filename):
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(path):
        os.remove(path)


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
        is_joined=is_joined,
        trending_posts=trending_posts(),
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
    return render_template(
        "forum/profile.html",
        user=user,
        post_karma=post_karma or 0,
        comment_karma=comment_karma or 0,
        recent_posts=recent_posts,
        recent_comments=recent_comments,
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
        post_votes=post_votes,
        saved_posts=saved_ids,
    )


@forum_bp.route("/notifications")
@login_required
def notifications():
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    unread = [item for item in items if item.read_at is None]
    return render_template("forum/notifications.html", notifications=items, unread=unread)


@forum_bp.route("/notifications/read", methods=("POST",))
@login_required
def mark_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, read_at=None).update({"read_at": datetime.now(timezone.utc)})
    db.session.commit()
    flash("Notifications marked as read.", "success")
    return redirect(url_for("forum.notifications"))


@forum_bp.route("/posts/new", methods=("GET", "POST"))
@login_required
def create_post():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if post.is_locked and not current_user.is_admin:
            flash("This thread is locked, so new comments are closed.", "warning")
            return redirect(url_for("forum.post_detail", post_id=post.id))

        body = request.form.get("body", "").strip()
        post_type = request.form.get("post_type", "discussion")
        community_id = request.form.get("community_id", type=int)
        community = db.session.get(Community, community_id) if community_id else None
        image = request.files.get("image")

        if not title or not body:
            flash("A title and post body are required.", "error")
        elif community is None:
            flash("Please choose a community.", "error")
        elif image and image.filename and not allowed_image(image.filename):
            flash("Images must be PNG, JPG, GIF, or WEBP files.", "error")
        else:
            image_filename = save_post_image(image)
            post = Post(title=title, body=body, post_type=post_type, image_filename=image_filename, author=current_user, community=community)
            db.session.add(post)
            db.session.commit()
            flash("Your post is live.", "success")
            return redirect(url_for("forum.post_detail", post_id=post.id))

    communities = Community.query.order_by(Community.name.asc()).all()
    return render_template("forum/create_post.html", communities=communities)


@forum_bp.route("/posts/<int:post_id>/edit", methods=("GET", "POST"))
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user and not current_user.is_admin:
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
            image_filename = save_post_image(request.files.get("image"))
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
    post = Post.query.get_or_404(post_id)
    if post.author != current_user and not current_user.is_admin:
        abort(403)
    delete_post_image(post.image_filename)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "success")
    return redirect(url_for("forum.index"))


@forum_bp.route("/posts/<int:post_id>", methods=("GET", "POST"))
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Please sign in before commenting.", "warning")
            return redirect(url_for("auth.login", next=request.path))

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

    comments = (
        Comment.query.filter_by(post_id=post.id)
        .outerjoin(Vote, Vote.comment_id == Comment.id)
        .group_by(Comment.id)
        .order_by(func.coalesce(func.sum(Vote.value), 0).desc(), Comment.created_at.asc())
        .all()
    )
    top_comments = [comment for comment in comments if comment.parent_id is None]
    post_votes, comment_votes, saved_posts = user_state(post_ids=[post.id], comment_ids=[comment.id for comment in comments])
    return render_template(
        "forum/post_detail.html",
        post=post,
        comments=comments,
        top_comments=top_comments,
        trending_posts=trending_posts(),
        post_votes=post_votes,
        comment_votes=comment_votes,
        saved_posts=saved_posts,
    )


@forum_bp.route("/posts/<int:post_id>/save", methods=("POST",))
@login_required
def save_post(post_id):
    post = Post.query.get_or_404(post_id)
    existing = SavedPost.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if existing:
        db.session.delete(existing)
        flash("Post removed from saved.", "success")
    else:
        db.session.add(SavedPost(user=current_user, post=post))
        flash("Post saved.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("forum.index"))


@forum_bp.route("/posts/<int:post_id>/report", methods=("POST",))
@login_required
def report_post(post_id):
    post = Post.query.get_or_404(post_id)
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
    comment = Comment.query.get_or_404(comment_id)
    if comment.author != current_user and not current_user.is_admin:
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
    comment = Comment.query.get_or_404(comment_id)
    if comment.author != current_user and not current_user.is_admin:
        abort(403)
    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()
    flash("Comment deleted.", "success")
    return redirect(url_for("forum.post_detail", post_id=post_id))


@forum_bp.route("/comments/<int:comment_id>/report", methods=("POST",))
@login_required
def report_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
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
    return render_template("forum/admin.html", users=users, posts=posts, comments=comments, reports=reports)


@forum_bp.route("/admin/users/<int:user_id>/toggle-admin", methods=("POST",))
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot remove your own admin access.", "warning")
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash("User admin status updated.", "success")
    return redirect(url_for("forum.admin_dashboard"))


@forum_bp.route("/admin/posts/<int:post_id>/pin", methods=("POST",))
@admin_required
def toggle_pin_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_pinned = not post.is_pinned
    db.session.commit()
    flash("Post pin status updated.", "success")
    return redirect(request.referrer or url_for("forum.admin_dashboard"))


@forum_bp.route("/admin/posts/<int:post_id>/lock", methods=("POST",))
@admin_required
def toggle_lock_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_locked = not post.is_locked
    db.session.commit()
    flash("Post lock status updated.", "success")
    return redirect(request.referrer or url_for("forum.admin_dashboard"))


@forum_bp.route("/admin/reports/<int:report_id>/<action>", methods=("POST",))
@admin_required
def moderate_report(report_id, action):
    report = Report.query.get_or_404(report_id)
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
    post = Post.query.get_or_404(post_id)
    value = request.form.get("value", type=int)
    if value not in (-1, 1):
        abort(400)
    existing = Vote.query.filter_by(user_id=current_user.id, post_id=post.id).first()

    if existing and existing.value == value:
        db.session.delete(existing)
        flash("Post vote removed.", "success")
    elif existing:
        existing.value = value
        flash("Post vote changed.", "success")
    else:
        db.session.add(Vote(user=current_user, post=post, value=value))
        flash("Post voted.", "success")

    db.session.commit()
    return redirect(request.referrer or url_for("forum.index"))


@forum_bp.route("/comments/<int:comment_id>/vote", methods=("POST",))
@login_required
def vote_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    value = request.form.get("value", type=int)
    if value not in (-1, 1):
        abort(400)
    existing = Vote.query.filter_by(user_id=current_user.id, comment_id=comment.id).first()

    if existing and existing.value == value:
        db.session.delete(existing)
        flash("Comment vote removed.", "success")
    elif existing:
        existing.value = value
        flash("Comment vote changed.", "success")
    else:
        db.session.add(Vote(user=current_user, comment=comment, value=value))
        flash("Comment voted.", "success")

    db.session.commit()
    return redirect(url_for("forum.post_detail", post_id=comment.post_id))
