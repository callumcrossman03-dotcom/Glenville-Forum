from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=True)
    bio = db.Column(db.String(280), nullable=True)
    avatar_color = db.Column(db.String(20), default="#005bab", nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    posts = db.relationship("Post", back_populates="author", cascade="all, delete-orphan")
    comments = db.relationship("Comment", back_populates="author", cascade="all, delete-orphan")
    votes = db.relationship("Vote", back_populates="user", cascade="all, delete-orphan")
    saved_posts = db.relationship("SavedPost", back_populates="user", cascade="all, delete-orphan")
    memberships = db.relationship("CommunityMembership", back_populates="user", cascade="all, delete-orphan")
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Notification.user_id",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def initials(self):
        name = self.display_name or self.username
        return name[:2].upper()

    @property
    def public_name(self):
        return self.display_name or self.username


class Community(db.Model):
    __tablename__ = "communities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(40), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=False)
    icon = db.Column(db.String(8), nullable=False, default="GS")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    posts = db.relationship("Post", back_populates="community", cascade="all, delete-orphan")
    memberships = db.relationship("CommunityMembership", back_populates="community", cascade="all, delete-orphan")
    creator = db.relationship("User")


class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=False)
    post_type = db.Column(db.String(20), default="discussion", nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    is_pinned = db.Column(db.Boolean, default=False, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    community_id = db.Column(db.Integer, db.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True)

    author = db.relationship("User", back_populates="posts")
    community = db.relationship("Community", back_populates="posts")
    comments = db.relationship("Comment", back_populates="post", cascade="all, delete-orphan", order_by="Comment.created_at")
    votes = db.relationship("Vote", back_populates="post", cascade="all, delete-orphan")
    saves = db.relationship("SavedPost", back_populates="post", cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="post", cascade="all, delete-orphan")

    @property
    def score(self):
        return sum(vote.value for vote in self.votes)


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True)

    author = db.relationship("User", back_populates="comments")
    post = db.relationship("Post", back_populates="comments")
    votes = db.relationship("Vote", back_populates="comment", cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="comment", cascade="all, delete-orphan")
    replies = db.relationship(
        "Comment",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
        order_by="Comment.created_at",
        single_parent=True,
    )

    @property
    def score(self):
        return sum(vote.value for vote in self.votes)


class Vote(db.Model):
    __tablename__ = "votes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True)
    value = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", back_populates="votes")
    post = db.relationship("Post", back_populates="votes")
    comment = db.relationship("Comment", back_populates="votes")

    __table_args__ = (
        db.UniqueConstraint("user_id", "post_id", name="uq_user_post_vote"),
        db.UniqueConstraint("user_id", "comment_id", name="uq_user_comment_vote"),
        db.CheckConstraint(
            "(post_id IS NOT NULL AND comment_id IS NULL) OR (post_id IS NULL AND comment_id IS NOT NULL)",
            name="ck_vote_targets_one_item",
        ),
        db.CheckConstraint("value IN (-1, 1)", name="ck_vote_value"),
    )


class SavedPost(db.Model):
    __tablename__ = "saved_posts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", back_populates="saved_posts")
    post = db.relationship("Post", back_populates="saves")

    __table_args__ = (db.UniqueConstraint("user_id", "post_id", name="uq_user_saved_post"),)


class CommunityMembership(db.Model):
    __tablename__ = "community_memberships"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    community_id = db.Column(db.Integer, db.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", back_populates="memberships")
    community = db.relationship("Community", back_populates="memberships")

    __table_args__ = (db.UniqueConstraint("user_id", "community_id", name="uq_user_community_membership"),)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True)
    message = db.Column(db.String(255), nullable=False)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], back_populates="notifications")
    actor = db.relationship("User", foreign_keys=[actor_id])
    post = db.relationship("Post")
    comment = db.relationship("Comment")


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(120), nullable=False)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    community_id = db.Column(db.Integer, db.ForeignKey("communities.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    author = db.relationship("User")
    community = db.relationship("Community")


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    sender = db.relationship("User", foreign_keys=[sender_id])
    recipient = db.relationship("User", foreign_keys=[recipient_id])


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True)
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="open", nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)

    reporter = db.relationship("User")
    post = db.relationship("Post", back_populates="reports")
    comment = db.relationship("Comment", back_populates="reports")

    __table_args__ = (
        db.CheckConstraint(
            "(post_id IS NOT NULL AND comment_id IS NULL) OR (post_id IS NULL AND comment_id IS NOT NULL)",
            name="ck_report_targets_one_item",
        ),
    )
