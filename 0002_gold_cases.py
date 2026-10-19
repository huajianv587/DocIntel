"""add human-reviewed evaluation cases

Revision ID: 0002_gold_cases
Revises: 0001_initial
"""

from alembic import op

from app.models import GoldCase


revision = "0002_gold_cases"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    GoldCase.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    GoldCase.__table__.drop(bind=op.get_bind(), checkfirst=True)
