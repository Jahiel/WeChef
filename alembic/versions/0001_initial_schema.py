"""Initial schema — WeChef.

Revision ID: 0001
Revises: —
Create Date: 2026-03-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(200), nullable=False, index=True),
        sa.Column("ingredients", sa.JSON, nullable=False),
        sa.Column("steps", sa.JSON, nullable=False),
        sa.Column("servings", sa.Integer, default=4),
        sa.Column("prep_time", sa.Integer, nullable=True),
        sa.Column("source_url", sa.String(500), unique=True, nullable=True),
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False, index=True),
    )

    op.create_table(
        "recipe_tags",
        sa.Column(
            "recipe_id",
            sa.Integer,
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Integer,
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("recipe_tags")
    op.drop_table("tags")
    op.drop_table("recipes")
