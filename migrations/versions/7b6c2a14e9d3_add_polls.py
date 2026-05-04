"""add_polls

Revision ID: 7b6c2a14e9d3
Revises: 5fac916d4031
Create Date: 2026-05-02 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "7b6c2a14e9d3"
down_revision = "5fac916d4031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "poll_options",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("poll_options", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_poll_options_post_id"), ["post_id"], unique=False)

    op.create_table(
        "poll_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("option_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["option_id"], ["poll_options.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "post_id", name="uq_user_poll_vote"),
    )
    with op.batch_alter_table("poll_votes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_poll_votes_option_id"), ["option_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_poll_votes_post_id"), ["post_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_poll_votes_user_id"), ["user_id"], unique=False)


def downgrade():
    with op.batch_alter_table("poll_votes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_poll_votes_user_id"))
        batch_op.drop_index(batch_op.f("ix_poll_votes_post_id"))
        batch_op.drop_index(batch_op.f("ix_poll_votes_option_id"))
    op.drop_table("poll_votes")

    with op.batch_alter_table("poll_options", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_poll_options_post_id"))
    op.drop_table("poll_options")
