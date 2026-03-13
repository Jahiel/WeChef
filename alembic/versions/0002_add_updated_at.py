"""Ajout colonne updated_at sur recipes existantes.

Cette migration est utile si la table recipes existait avant
l'introduction du champ updated_at.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.drop_column("updated_at")
