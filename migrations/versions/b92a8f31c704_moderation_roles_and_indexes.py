"""moderation_roles_and_indexes

Revision ID: b92a8f31c704
Revises: 7b6c2a14e9d3
Create Date: 2026-05-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b92a8f31c704"
down_revision = "7b6c2a14e9d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "community_moderators",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("community_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'moderator')", name="ck_community_moderator_role"),
        sa.ForeignKeyConstraint(["community_id"], ["communities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "community_id", name="uq_user_community_moderator"),
    )
    with op.batch_alter_table("community_moderators", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_community_moderators_community_id"), ["community_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_community_moderators_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.create_index("ix_posts_community_created", ["community_id", "created_at"], unique=False)
        batch_op.create_index("ix_posts_pinned_created", ["is_pinned", "created_at"], unique=False)
        batch_op.create_index("ix_posts_type_created", ["post_type", "created_at"], unique=False)

    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.create_index("ix_comments_post_created", ["post_id", "created_at"], unique=False)

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index("ix_notifications_user_read_created", ["user_id", "read_at", "created_at"], unique=False)

    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.create_index("ix_messages_pair_created", ["sender_id", "recipient_id", "created_at"], unique=False)


def downgrade():
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_index("ix_messages_pair_created")

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_user_read_created")

    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.drop_index("ix_comments_post_created")

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_index("ix_posts_type_created")
        batch_op.drop_index("ix_posts_pinned_created")
        batch_op.drop_index("ix_posts_community_created")

    with op.batch_alter_table("community_moderators", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_community_moderators_user_id"))
        batch_op.drop_index(batch_op.f("ix_community_moderators_community_id"))
    op.drop_table("community_moderators")
