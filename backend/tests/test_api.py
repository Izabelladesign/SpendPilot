"""Contract tests for Developer 4's shared REST API.

These tests use an isolated temporary SQLite database. They do not call
Coinbase, x402, an external provider, or any paid service.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.main import app
from app.models import Approval, Base, Payment, Provider, PurchaseRequest, Task


@pytest.fixture()
def client(tmp_path) -> Generator[TestClient, None, None]:
    database_url = f"sqlite:///{tmp_path / 'api-test.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.test_session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.test_session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def task_payload() -> dict[str, object]:
    return {
        "objective": "Process a local test batch",
        "budget": {"amount": "10.00", "currency": "USD"},
        "quantity": 5,
        "qualityTarget": "Complete all five items",
        "constraints": ["Local test only"],
    }


def create_task(client: TestClient) -> dict[str, object]:
    response = client.post("/tasks", json=task_payload())
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_task(client: TestClient) -> None:
    created = create_task(client)

    assert created["objective"] == "Process a local test batch"
    assert created["status"] == "REQUESTED"
    assert created["budgetId"]
    assert created["budget"] == {"amount": "10.00", "currency": "USD"}
    assert created["selectedProviderId"] is None

    response = client.get(f"/tasks/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_list_tasks_supports_status_filter(client: TestClient) -> None:
    created = create_task(client)

    response = client.get("/tasks?status=REQUESTED&limit=10")

    assert response.status_code == 200
    assert [task["id"] for task in response.json()["items"]] == [created["id"]]


def test_task_events_are_created_and_execution_is_idempotent(client: TestClient) -> None:
    created = create_task(client)
    task_id = created["id"]

    events = client.get(f"/tasks/{task_id}/events")
    assert events.status_code == 200
    assert [event["type"] for event in events.json()["items"]] == ["TASK_CREATED"]

    execute = client.post(
        f"/tasks/{task_id}/execute",
        json={"idempotencyKey": "api-test-execution-001"},
    )
    assert execute.status_code == 202
    assert execute.json()["status"] == "RESEARCHING"

    duplicate = client.post(
        f"/tasks/{task_id}/execute",
        json={"idempotencyKey": "api-test-execution-001"},
    )
    assert duplicate.status_code == 202

    events = client.get(f"/tasks/{task_id}/events")
    assert [event["type"] for event in events.json()["items"]] == [
        "TASK_CREATED",
        "EXECUTION_REQUESTED",
    ]


def test_budget_returns_available_balance(client: TestClient) -> None:
    created = create_task(client)
    with app.state.test_session_factory() as db:
        task = db.get(Task, created["id"])
        assert task is not None
        budget_id = task.budget_id

    response = client.get(f"/budgets/{budget_id}")
    assert response.status_code == 200
    assert response.json()["available"] == "10.00"
    assert response.json()["currency"] == "USD"


def test_unknown_task_returns_contract_error(client: TestClient) -> None:
    response = client.get("/tasks/not-a-real-task")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_invalid_task_request_returns_validation_error(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={
            "objective": "",
            "budget": {"amount": "-1.00", "currency": "USD"},
        },
    )

    assert response.status_code == 422


def test_payments_are_read_only_and_empty_in_an_isolated_test(client: TestClient) -> None:
    response = client.get("/payments")

    assert response.status_code == 200
    assert response.json() == {"items": [], "nextCursor": None}


def test_execution_summary_keeps_payment_and_task_status_separate(client: TestClient) -> None:
    created = create_task(client)

    with app.state.test_session_factory() as db:
        provider = Provider(name="Local research provider", is_approved=True)
        db.add(provider)
        db.flush()

        purchase = PurchaseRequest(
            task_id=created["id"],
            provider_id=provider.id,
            idempotency_key="execution-summary-001",
            amount="0.50",
            currency="USD",
            decision="REVIEW_REQUIRED",
            decision_reason="Human review is required for this test purchase.",
        )
        db.add(purchase)
        db.flush()
        db.add(
            Approval(
                task_id=created["id"],
                purchase_request_id=purchase.id,
                amount="0.50",
                currency="USD",
                vendor=provider.name,
                status="PENDING",
                reason=purchase.decision_reason,
            )
        )
        db.add(
            Payment(
                task_id=created["id"],
                purchase_request_id=purchase.id,
                provider_id=provider.id,
                amount="0.50",
                currency="USD",
                status="SETTLED",
                transaction_reference="local-test-settlement",
            )
        )
        db.commit()

    response = client.get(f"/tasks/{created['id']}/execution")

    assert response.status_code == 200
    summary = response.json()
    assert summary["taskStatus"] == "REQUESTED"
    assert summary["purchaseRequests"][0]["decision"] == "REVIEW_REQUIRED"
    assert summary["approvals"][0]["status"] == "PENDING"
    assert summary["payments"][0]["status"] == "SETTLED"


def test_execution_summary_unknown_task_returns_contract_error(client: TestClient) -> None:
    response = client.get("/tasks/not-a-real-task/execution")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def research_brief_payload() -> dict[str, object]:
    return {
        "summary": "A comparison for a 50-person engineering team.",
        "copilotSection": "GitHub Copilot pricing and security information.",
        "cursorSection": "Cursor pricing and security information.",
        "pricingSection": "Pricing is based on the cited public vendor pages.",
        "securitySection": "Security details require review against current vendor documentation.",
        "sourceUrls": [
            "https://github.com/features/copilot",
            "https://cursor.com/pricing",
        ],
        "unverifiedInformation": (
            "Enterprise discounts and organization-specific settings are not verified."
        ),
    }


def test_verified_output_completes_task_and_records_events(client: TestClient) -> None:
    created = create_task(client)

    response = client.post(
        f"/tasks/{created['id']}/verify",
        json=research_brief_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["output"]["verification"]["status"] == "VERIFIED"

    events = client.get(f"/tasks/{created['id']}/events").json()["items"]
    assert [event["type"] for event in events] == [
        "TASK_CREATED",
        "OUTPUT_RECEIVED",
        "OUTPUT_VERIFIED",
    ]


def test_failed_output_does_not_complete_task(client: TestClient) -> None:
    created = create_task(client)
    payload = research_brief_payload()
    payload["sourceUrls"] = ["https://github.com/features/copilot"]

    response = client.post(f"/tasks/{created['id']}/verify", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["output"]["verification"]["status"] == "FAILED"
    assert "two_unique_https_sources" in body["failureReason"]

    events = client.get(f"/tasks/{created['id']}/events").json()["items"]
    assert events[-1]["type"] == "VERIFICATION_FAILED"


def test_terminal_task_cannot_be_verified_again(client: TestClient) -> None:
    created = create_task(client)
    first = client.post(f"/tasks/{created['id']}/verify", json=research_brief_payload())
    assert first.status_code == 200

    second = client.post(f"/tasks/{created['id']}/verify", json=research_brief_payload())

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invalid_state_transition"
