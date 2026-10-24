
import sqlite3

from app.payment_store import connect


class BudgetError(Exception):
    pass


def initialize_budget_database():
    """Create persistent budget and reservation tables."""

    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                task_id TEXT PRIMARY KEY,
                total_cents INTEGER NOT NULL
                    CHECK (total_cents >= 0),
                spent_cents INTEGER NOT NULL DEFAULT 0
                    CHECK (spent_cents >= 0),
                reserved_cents INTEGER NOT NULL DEFAULT 0
                    CHECK (reserved_cents >= 0),
                CHECK (
                    spent_cents + reserved_cents
                    <= total_cents
                )
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS budget_reservations (
                payment_key TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL
                    CHECK (amount_cents > 0),
                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'RESERVED',
                            'COMMITTED',
                            'RELEASED'
                        )
                    ),
                FOREIGN KEY (task_id)
                    REFERENCES budgets(task_id)
            )
        """)


def create_budget(task_id, total_cents):
    """
    Create a task budget.

    Existing budgets cannot be silently reset.
    """

    if not isinstance(task_id, str) or not task_id:
        raise BudgetError("Task ID is required")

    if type(total_cents) is not int or total_cents < 0:
        raise BudgetError("Invalid budget amount")

    with connect() as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO budgets
                (task_id, total_cents)
            VALUES (?, ?)
        """, (task_id, total_cents))

        if cursor.rowcount == 0:
            row = conn.execute("""
                SELECT total_cents
                FROM budgets
                WHERE task_id = ?
            """, (task_id,)).fetchone()

            if row[0] != total_cents:
                raise BudgetError(
                    "Budget already exists with a different limit"
                )

            return False

        return True


def get_budget(task_id):
    """Read the current persistent budget."""

    with connect() as conn:
        row = conn.execute("""
            SELECT
                total_cents,
                spent_cents,
                reserved_cents
            FROM budgets
            WHERE task_id = ?
        """, (task_id,)).fetchone()

    if row is None:
        return None

    total, spent, reserved = row

    return {
        "task_id": task_id,
        "total_cents": total,
        "spent_cents": spent,
        "reserved_cents": reserved,
        "available_cents": total - spent - reserved,
    }


def reserve_budget(task_id, payment_key, amount_cents):
    """
    Atomically reserve funds for a unique payment.

    A repeated payment key cannot reserve funds twice.
    """

    if type(amount_cents) is not int or amount_cents <= 0:
        raise BudgetError("Amount must be positive cents")

    if not isinstance(payment_key, str) or not payment_key:
        raise BudgetError("Payment key is required")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute("""
            SELECT task_id, amount_cents, status
            FROM budget_reservations
            WHERE payment_key = ?
        """, (payment_key,)).fetchone()

        if existing is not None:
            if (
                existing[0] != task_id
                or existing[1] != amount_cents
            ):
                raise BudgetError(
                    "Payment key reused for another reservation"
                )

            return False

        cursor = conn.execute("""
            UPDATE budgets
            SET reserved_cents = reserved_cents + ?
            WHERE task_id = ?
              AND total_cents - spent_cents
                  - reserved_cents >= ?
        """, (amount_cents, task_id, amount_cents))

        if cursor.rowcount != 1:
            raise BudgetError(
                "Budget missing or insufficient funds"
            )

        conn.execute("""
            INSERT INTO budget_reservations
                (payment_key, task_id, amount_cents, status)
            VALUES (?, ?, ?, 'RESERVED')
        """, (payment_key, task_id, amount_cents))

        return True


def commit_budget(payment_key):
    """Convert an existing reservation into spending."""

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute("""
            SELECT task_id, amount_cents, status
            FROM budget_reservations
            WHERE payment_key = ?
        """, (payment_key,)).fetchone()

        if row is None:
            raise BudgetError("Reservation not found")

        task_id, amount, status = row

        if status == "COMMITTED":
            return False

        if status != "RESERVED":
            raise BudgetError(
                "Cannot commit a released reservation"
            )

        conn.execute("""
            UPDATE budgets
            SET reserved_cents = reserved_cents - ?,
                spent_cents = spent_cents + ?
            WHERE task_id = ?
        """, (amount, amount, task_id))

        conn.execute("""
            UPDATE budget_reservations
            SET status = 'COMMITTED'
            WHERE payment_key = ?
        """, (payment_key,))

        return True


def release_budget(payment_key):
    """Release a reservation after confirmed non-settlement."""

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute("""
            SELECT task_id, amount_cents, status
            FROM budget_reservations
            WHERE payment_key = ?
        """, (payment_key,)).fetchone()

        if row is None:
            raise BudgetError("Reservation not found")

        task_id, amount, status = row

        if status == "RELEASED":
            return False

        if status != "RESERVED":
            raise BudgetError(
                "Cannot release committed spending"
            )

        conn.execute("""
            UPDATE budgets
            SET reserved_cents = reserved_cents - ?
            WHERE task_id = ?
        """, (amount, task_id))

        conn.execute("""
            UPDATE budget_reservations
            SET status = 'RELEASED'
            WHERE payment_key = ?
        """, (payment_key,))

        return True
