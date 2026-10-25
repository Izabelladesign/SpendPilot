from decimal import Decimal
from uuid import uuid4

from app import payment_store
from app import persistent_budget_service as budgets
from app.policy_engine import PaymentRequest, SpendingPolicy
from app.unified_payment_service import prepare_governed_payment


def test_authorized_payment_reserves_budget_once():
    payment_store.initialize_database()
    budgets.initialize_budget_database()

    task_id = f"lifecycle-{uuid4().hex}"
    key = f"payment-{uuid4().hex}"

    budgets.create_budget(task_id, 10000)

    request = PaymentRequest(
        task_id=task_id,
        vendor="spendpilot-demo",
        amount_usd=Decimal("1.00"),
    )

    policy = SpendingPolicy(
        task_id=task_id,
        allowed_vendors=frozenset({"spendpilot-demo"}),
        max_transaction_usd=Decimal("10.00"),
        approval_threshold_usd=Decimal("5.00"),
    )

    first = prepare_governed_payment(key, request, policy)

    assert first.status == "READY"
    assert payment_store.get_payment(key)["status"] == "READY"
    assert budgets.get_budget(task_id)["reserved_cents"] == 100

    # Same payment must not reserve another dollar.
    prepare_governed_payment(key, request, policy)
    assert budgets.get_budget(task_id)["reserved_cents"] == 100

    # Only one execution claim is allowed.
    assert payment_store.claim_payment_execution(key) is True
    assert payment_store.claim_payment_execution(key) is False

    assert (
        payment_store.get_payment(key)["status"]
        == "PENDING_RECONCILIATION"
    )

    # Funds remain reserved until settlement is verified.
    budget = budgets.get_budget(task_id)
    assert budget["spent_cents"] == 0
    assert budget["reserved_cents"] == 100
