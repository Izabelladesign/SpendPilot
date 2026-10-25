
"""Seed deterministic demo records for local development."""

from decimal import Decimal

from app.database import SessionLocal
from app.models import Budget, User


def seed() -> None:
    with SessionLocal.begin() as db:
        # Create the demo user (task and budget owner)
        user = db.query(User).filter_by(
            email="demo@spendpilot.local"
        ).one_or_none()

        if user is None:
            user = User(
                email="demo@spendpilot.local",
                display_name="SpendPilot Demo",
            )
            db.add(user)
            db.flush()

        # Create a separate demo reviewer account
        reviewer = db.query(User).filter_by(
            email="reviewer@spendpilot.local"
        ).one_or_none()

        if reviewer is None:
            reviewer = User(
                email="reviewer@spendpilot.local",
                display_name="SpendPilot Demo Reviewer",
            )
            db.add(reviewer)

        # Create the demo user's $500 operations budget
        if not db.query(Budget).filter_by(
            owner_id=user.id,
            name="Demo operations budget"
        ).one_or_none():
            db.add(
                Budget(
                    owner_id=user.id,
                    name="Demo operations budget",
                    currency="USD",
                    total=Decimal("500.00"),
                )
            )


if __name__ == "__main__":
    seed()
