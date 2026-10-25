
import json
import os
import sqlite3
from pathlib import Path


DB_PATH = Path(
    os.getenv(
        "PAYMENT_DATABASE_PATH",
        str(Path(__file__).resolve().parent.parent / "payment_ledger.db"),
    )
)

VALID_STATUSES = {
    "READY",
    "IN_PROGRESS",
    "PAID",
    "FAILED",
    "DENIED",
    "REVIEW_REQUIRED",
    "PENDING_RECONCILIATION",
}

FINAL_STATUSES = {
    "PAID",
    "FAILED",
    "DENIED",
}

ALLOWED_TRANSITIONS = {
    "IN_PROGRESS": {
        "READY",
        "PAID",
        "FAILED",
        "DENIED",
        "REVIEW_REQUIRED",
        "PENDING_RECONCILIATION",
    },
    "READY": {"PENDING_RECONCILIATION"},
    "REVIEW_REQUIRED": {
        "DENIED",
        "IN_PROGRESS",
    },
    "PENDING_RECONCILIATION": {
        "PAID",
        "FAILED",
    },
    "PAID": set(),
    "FAILED": set(),
    "DENIED": set(),
}


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                idempotency_key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS verified_settlements (
                transaction_hash TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                verified_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (idempotency_key)
                    REFERENCES payments(idempotency_key)
            )
        """)


def normalize_fingerprint(fingerprint):
    return json.dumps(
        fingerprint,
        separators=(",", ":"),
        sort_keys=True,
    )


def create_payment(key, fingerprint):
    """
    Atomically create a new payment record.

    Returns True for a new payment.
    Returns False for a duplicate with matching details.
    Raises ValueError if the key is reused for another payment.
    """

    if not key or not isinstance(key, str):
        raise ValueError("Idempotency key is required")

    encoded = normalize_fingerprint(fingerprint)

    with connect() as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO payments
                (idempotency_key, fingerprint, status)
            VALUES (?, ?, 'IN_PROGRESS')
        """, (key, encoded))

        if cursor.rowcount == 1:
            return True

        row = conn.execute("""
            SELECT fingerprint
            FROM payments
            WHERE idempotency_key = ?
        """, (key,)).fetchone()

        if row is None:
            raise RuntimeError(
                "Payment record could not be retrieved"
            )

        existing = json.loads(row[0])

        if existing != json.loads(encoded):
            raise ValueError(
                "Idempotency key reused for a different payment"
            )

        return False


def get_payment(key):
    with connect() as conn:
        row = conn.execute("""
            SELECT fingerprint, status, message, created_at
            FROM payments
            WHERE idempotency_key = ?
        """, (key,)).fetchone()

    if row is None:
        return None

    return {
        "fingerprint": json.loads(row[0]),
        "status": row[1],
        "message": row[2],
        "created_at": row[3],
    }


def update_payment(key, status, message):
    """
    Update payment status only when the transition is allowed.

    Terminal payments cannot be changed.
    Unknown payments cannot be updated.
    """

    if status not in VALID_STATUSES:
        raise ValueError("Invalid payment status")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute("""
            SELECT status
            FROM payments
            WHERE idempotency_key = ?
        """, (key,)).fetchone()

        if row is None:
            raise ValueError(
                "Payment record does not exist"
            )

        current_status = row[0]

        if current_status not in ALLOWED_TRANSITIONS:
            raise ValueError(
                f"Unknown stored payment status: {current_status}"
            )

        if status not in ALLOWED_TRANSITIONS[current_status]:
            raise ValueError(
                f"Invalid payment transition: "
                f"{current_status} -> {status}"
            )

        conn.execute("""
            UPDATE payments
            SET status = ?, message = ?
            WHERE idempotency_key = ?
        """, (status, message, key))



def claim_payment_execution(key):
    """Atomically claim one authorized, reserved payment."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute("""
            SELECT fingerprint FROM payments
            WHERE idempotency_key = ? AND status = 'READY'
        """, (key,)).fetchone()

        if row is None:
            return False

        fingerprint = json.loads(row[0])
        reservation = conn.execute("""
            SELECT status, task_id, amount_cents
            FROM budget_reservations
            WHERE payment_key = ?
        """, (key,)).fetchone()

        from decimal import Decimal
        amount = Decimal(fingerprint["amount_usd"]) * 100

        if (
            reservation is None
            or reservation[0] != "RESERVED"
            or reservation[1] != fingerprint["task_id"]
            or amount != amount.to_integral_value()
            or reservation[2] != int(amount)
        ):
            raise ValueError("Valid budget reservation required")

        cursor = conn.execute("""
            UPDATE payments
            SET status = 'PENDING_RECONCILIATION',
                message = 'Execution claimed; settlement pending'
            WHERE idempotency_key = ? AND status = 'READY'
        """, (key,))

        return cursor.rowcount == 1


def list_payments(limit=50):
    """
    Return recent payment records for the dashboard.
    """

    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError(
            "Limit must be between 1 and 100"
        )

    with connect() as conn:
        rows = conn.execute("""
            SELECT
                idempotency_key,
                fingerprint,
                status,
                message,
                created_at
            FROM payments
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return [
        {
            "idempotency_key": row[0],
            "fingerprint": json.loads(row[1]),
            "status": row[2],
            "message": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def validate_transaction_hash(transaction_hash):
    """
    Normalize and validate an EVM transaction hash.
    """

    if not isinstance(transaction_hash, str):
        raise ValueError("Invalid transaction hash")

    tx_hash = transaction_hash.lower()

    if (
        len(tx_hash) != 66
        or not tx_hash.startswith("0x")
        or any(
            char not in "0123456789abcdef"
            for char in tx_hash[2:]
        )
    ):
        raise ValueError("Invalid transaction hash")

    return tx_hash


def record_verified_settlement(
    idempotency_key,
    transaction_hash,
):
    """
    Bind a verified transaction to one existing payment.

    Returns True when newly recorded.
    Returns False when the same binding already exists.

    IMPORTANT:
    The caller must independently verify settlement
    on-chain before calling this function.
    """

    tx_hash = validate_transaction_hash(
        transaction_hash
    )

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        payment = conn.execute("""
            SELECT status
            FROM payments
            WHERE idempotency_key = ?
        """, (idempotency_key,)).fetchone()

        if payment is None:
            raise ValueError(
                "Payment record does not exist"
            )

        if payment[0] in {"FAILED", "DENIED"}:
            raise ValueError(
                "Cannot bind settlement to a rejected payment"
            )

        existing = conn.execute("""
            SELECT transaction_hash
            FROM verified_settlements
            WHERE idempotency_key = ?
        """, (idempotency_key,)).fetchone()

        if existing is not None:
            if existing[0] == tx_hash:
                return False

            raise ValueError(
                "Payment already bound to another transaction"
            )

        try:
            conn.execute("""
                INSERT INTO verified_settlements
                    (transaction_hash, idempotency_key)
                VALUES (?, ?)
            """, (tx_hash, idempotency_key))

        except sqlite3.IntegrityError as error:
            raise ValueError(
                "Transaction already used for another payment"
            ) from error

        return True


def get_verified_settlement(idempotency_key):
    """
    Retrieve a payment's recorded settlement.
    """

    with connect() as conn:
        row = conn.execute("""
            SELECT transaction_hash, verified_at
            FROM verified_settlements
            WHERE idempotency_key = ?
        """, (idempotency_key,)).fetchone()

    if row is None:
        return None

    return {
        "transaction_hash": row[0],
        "verified_at": row[1],
    }


def finalize_settlement_atomic(
    idempotency_key,
    transaction_hash,
    expected_task_id,
    expected_amount_cents,
):
    """
    Atomically:
      1. Bind a verified transaction hash.
      2. Commit the reserved budget.
      3. Mark the payment PAID.

    The caller MUST independently verify the transaction
    against the approved payment details first.
    """

    tx_hash = validate_transaction_hash(transaction_hash)

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        payment = conn.execute("""
            SELECT status, fingerprint
            FROM payments
            WHERE idempotency_key = ?
        """, (idempotency_key,)).fetchone()

        if payment is None:
            raise ValueError("Payment not found")

        status, fingerprint_json = payment
        fingerprint = json.loads(fingerprint_json)

        if fingerprint["task_id"] != expected_task_id:
            raise ValueError("Task mismatch")

        if status == "PAID":
            existing = conn.execute("""
                SELECT transaction_hash
                FROM verified_settlements
                WHERE idempotency_key = ?
            """, (idempotency_key,)).fetchone()

            if existing and existing[0] == tx_hash:
                return False

            raise ValueError("Payment already finalized")

        if status not in {
            "PENDING_RECONCILIATION",
        }:
            raise ValueError(
                f"Cannot finalize payment in status {status}"
            )

        reservation = conn.execute("""
            SELECT task_id, amount_cents, status
            FROM budget_reservations
            WHERE payment_key = ?
        """, (idempotency_key,)).fetchone()

        if reservation is None:
            raise ValueError("Budget reservation missing")

        task_id, amount_cents, reservation_status = reservation

        if (
            task_id != expected_task_id
            or amount_cents != expected_amount_cents
            or reservation_status != "RESERVED"
        ):
            raise ValueError("Reservation mismatch")

        existing = conn.execute("""
            SELECT idempotency_key
            FROM verified_settlements
            WHERE transaction_hash = ?
        """, (tx_hash,)).fetchone()

        if existing is not None:
            raise ValueError(
                "Transaction already assigned to a payment"
            )

        conn.execute("""
            INSERT INTO verified_settlements
                (transaction_hash, idempotency_key)
            VALUES (?, ?)
        """, (tx_hash, idempotency_key))

        cursor = conn.execute("""
            UPDATE budgets
            SET reserved_cents = reserved_cents - ?,
                spent_cents = spent_cents + ?
            WHERE task_id = ?
              AND reserved_cents >= ?
        """, (
            amount_cents,
            amount_cents,
            task_id,
            amount_cents,
        ))

        if cursor.rowcount != 1:
            raise ValueError("Budget update failed")

        conn.execute("""
            UPDATE budget_reservations
            SET status = 'COMMITTED'
            WHERE payment_key = ?
        """, (idempotency_key,))

        conn.execute("""
            UPDATE payments
            SET status = 'PAID',
                message = 'USDC settlement verified on-chain'
            WHERE idempotency_key = ?
        """, (idempotency_key,))

        return True
