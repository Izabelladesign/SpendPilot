# SpendPilot shared API contract

This document is the integration contract for the shared FastAPI backend. It
defines the stable identifiers and response shapes that orchestration,
governance, the enterprise dashboard, the Forge app, and the shopping UI can
share. It is intentionally independent of the database implementation.

Base URL in local development: `http://localhost:8000`

## Contract rules

- JSON uses `camelCase` field names at the API boundary.
- Every resource has an opaque UUID `id`, an ISO-8601 UTC `createdAt`, and an
  ISO-8601 UTC `updatedAt` unless noted otherwise.
- Money is represented as a decimal `amount` plus an uppercase ISO-4217
  `currency`; clients must not use floating-point arithmetic for settlement.
- The LLM may propose task information, but it never authorizes spending.
- Authorization, reservations, approvals, and payment state are server-owned.
- Unknown fields are rejected in request bodies.

## Shared enums

### Task status

```text
REQUESTED
RESEARCHING
PLANNING
AWAITING_APPROVAL
EXECUTING
VERIFYING
COMPLETED
FAILED
```

### Decision

```text
ALLOW
BLOCK
REVIEW_REQUIRED
```

### Payment status

```text
PENDING
IN_PROGRESS
PENDING_RECONCILIATION
SETTLED
FAILED
UNCERTAIN
```

### Approval status

```text
PENDING
APPROVED
REJECTED
EXPIRED
```

## Core resources

### Task

```json
{
  "id": "uuid",
  "userId": "uuid",
  "budgetId": "uuid",
  "objective": "Process 1000 documents",
  "budget": { "amount": "50.00", "currency": "USD" },
  "quantity": 1000,
  "qualityTarget": "At least 95% accuracy",
  "constraints": ["Do not exceed the budget"],
  "status": "REQUESTED",
  "selectedProviderId": null,
  "output": null,
  "failureReason": null,
  "createdAt": "2026-10-24T12:00:00Z",
  "updatedAt": "2026-10-24T12:00:00Z"
}
```

`budget` is a task limit, not permission to spend. `selectedProviderId`,
`output`, and `failureReason` may be `null`.

### Agent event

```json
{
  "id": "uuid",
  "taskId": "uuid",
  "type": "POLICY_DECISION",
  "message": "Purchase blocked: provider is not approved",
  "metadata": { "decision": "BLOCK" },
  "createdAt": "2026-10-24T12:01:00Z"
}
```

Event types are implementation-extensible, but initial events should include
`TASK_CREATED`, `STATE_CHANGED`, `PROVIDER_RESEARCHED`, `POLICY_DECISION`,
`APPROVAL_REQUESTED`, `PAYMENT_STATUS_CHANGED`, `OUTPUT_VERIFIED`, and
`ERROR`.

### Budget

```json
{
  "id": "uuid",
  "name": "Operations budget",
  "currency": "USD",
  "total": "500.00",
  "spent": "100.00",
  "reserved": "50.00",
  "available": "350.00",
  "createdAt": "2026-10-24T12:00:00Z",
  "updatedAt": "2026-10-24T12:00:00Z"
}
```

The server calculates `available = total - spent - reserved`. Reservations
must be atomic and must not be created when available funds are insufficient.

### Payment

```json
{
  "id": "uuid",
  "taskId": "uuid",
  "purchaseRequestId": "uuid",
  "providerId": "uuid",
  "amount": "5.00",
  "currency": "USD",
  "status": "SETTLED",
  "transactionReference": "testnet-reference-or-null",
  "createdAt": "2026-10-24T12:02:00Z",
  "updatedAt": "2026-10-24T12:03:00Z"
}
```

Secrets, private keys, authorization headers, and raw payment credentials must
never appear in API responses or event metadata.

### Approval

```json
{
  "id": "uuid",
  "taskId": "uuid",
  "purchaseRequestId": "uuid",
  "amount": "75.00",
  "currency": "USD",
  "vendor": "Example Provider",
  "status": "PENDING",
  "reason": "Amount exceeds automatic approval threshold",
  "decidedBy": null,
  "decidedAt": null,
  "createdAt": "2026-10-24T12:02:00Z",
  "updatedAt": "2026-10-24T12:02:00Z"
}
```

## Endpoints

### `GET /tasks`

Returns the most recently updated tasks for dashboard and workspace views.
Optional filters are `status` and `limit` (1–100). Response:

```json
{ "items": [], "nextCursor": null }
```

### `POST /tasks`

Creates a task in `REQUESTED` state. It stores an intake specification but does
not execute a purchase.

Request:

```json
{
  "objective": "Process 1000 documents",
  "budget": { "amount": "50.00", "currency": "USD" },
  "quantity": 1000,
  "qualityTarget": "At least 95% accuracy",
  "constraints": ["Do not exceed the budget"]
}
```

Response: `201 Created` with a `Task` resource.

### `GET /tasks/{taskId}`

Returns the task, current status, selected provider, and verified output when
available. Response: `200 OK`.

### `GET /tasks/{taskId}/events`

Returns chronological agent events:

```json
{ "items": [{ "id": "uuid", "taskId": "uuid", "type": "TASK_CREATED", "message": "Task received", "metadata": {}, "createdAt": "2026-10-24T12:00:00Z" }] }
```

Response: `200 OK`.

### `POST /tasks/{taskId}/execute`

Requests execution of a task. The backend must enforce idempotency and policy
before any payment attempt.

Request:

```json
{ "idempotencyKey": "client-generated-unique-key" }
```

Response: `202 Accepted` with the current `Task` resource. Repeating the same
key must not create a duplicate execution or payment.

### `GET /budgets/{budgetId}`

Returns the calculated budget balances. Response: `200 OK`.

### `GET /payments`

Returns payment history. Supported filters are `taskId`, `status`, and
`limit`. Response:

```json
{ "items": [], "nextCursor": null }
```

### `POST /approvals/{approvalId}/decision`

Records an authorized human approval decision. The backend, not the client UI,
must verify authorization and prevent replay.

Request:

```json
{ "decision": "APPROVED", "comment": "Reviewed provider and amount" }
```

Response: `200 OK` with an updated `Approval` resource. Valid decisions are
`APPROVED` and `REJECTED`.

## Error format

All non-success responses use this shape:

```json
{
  "error": {
    "code": "budget_exceeded",
    "message": "The requested reservation exceeds available funds.",
    "requestId": "uuid",
    "fieldErrors": []
  }
}
```

Initial error codes include `validation_error`, `not_found`,
`invalid_state_transition`, `budget_exceeded`, `policy_blocked`,
`approval_required`, `duplicate_request`, and `payment_uncertain`.

## Ownership and integration

- Developer 1 owns task planning and state-transition behavior, using the
  `Task` and `AgentEvent` contracts.
- Developer 2 owns budget, policy, approval, and payment enforcement, using the
  `Budget`, `Approval`, and `Payment` contracts.
- Developer 3 can consume task and shopping endpoints without owning payment
  authorization.
- Developer 4 owns the FastAPI routes, persistence, dashboard-facing reads, and
  Forge-to-backend integration.
