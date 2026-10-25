"""Create the initial SpendPilot schema.

Revision ID: 0001_initial_schema
"""

import os

from alembic import op
from sqlalchemy import create_engine

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import Base

    engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./spendpilot.db"))
    Base.metadata.create_all(engine)


def downgrade() -> None:
    from app.models import Base

    engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./spendpilot.db"))
    Base.metadata.drop_all(engine)
