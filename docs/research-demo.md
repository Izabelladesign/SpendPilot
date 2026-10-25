# SpendPilot research demo runbook

## Locked scenario

Create a research brief comparing GitHub Copilot and Cursor for a 50-person
engineering team. The brief must include public pricing and security
information, at least two unique HTTPS sources, and an explicit statement of
anything that was not verified. The research-task budget is USD 1.00.

GitHub Copilot and Cursor are the products being researched. They are not the
research-service providers.

## Safe local demo

This path uses only the local FastAPI app and SQLite records. It does not call
OpenAI, Bright Data, a paid provider, Coinbase, x402, or a wallet.

Start the backend:

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000/enterprise` and create a task from
`http://localhost:8000/docs` with:

```json
{
  "objective": "Create a research brief comparing GitHub Copilot and Cursor for a 50-person engineering team",
  "budget": { "amount": "1.00", "currency": "USD" },
  "quantity": 1,
  "qualityTarget": "Include pricing, security, two HTTPS sources, and unverified information",
  "constraints": ["Research task only", "Maximum USD 1.00"]
}
```

Copy the returned task `id`. Submit a local service response to
`POST /tasks/{taskId}/verify`:

```json
{
  "summary": "A comparison for a 50-person engineering team.",
  "copilotSection": "GitHub Copilot pricing and security information.",
  "cursorSection": "Cursor pricing and security information.",
  "pricingSection": "Pricing is based on the cited public vendor pages.",
  "securitySection": "Security details require review against current vendor documentation.",
  "sourceUrls": [
    "https://github.com/features/copilot",
    "https://cursor.com/pricing"
  ],
  "unverifiedInformation": "Enterprise discounts and organization-specific settings are not verified."
}
```

The server runs the existing verifier, stores the brief and verification
result, records `OUTPUT_RECEIVED` and `OUTPUT_VERIFIED`, and marks the task
`COMPLETED` only after verification passes. Submit the same payload with one
source URL to demonstrate `VERIFICATION_FAILED` and a non-completed task.

For a safe governance-block demo, call `POST /api/governance/review` with a
budget over USD 500:

```json
{
  "objective": "Create the Copilot and Cursor research brief",
  "budget_usd": "501.00",
  "quantity": 1,
  "constraints": ["Maximum USD 1.00"]
}
```

This is preliminary governance only and does not authorize or execute payment.

## Current truth about integrations

### Real in this repository

- Server-owned research-brief structural verification.
- Local task, event, purchase-request, approval, payment, and budget records.
- Governance decision boundaries and idempotency checks.
- Read-only execution summary for the enterprise dashboard.
- Tests for valid/invalid briefs and independent payment/task states.

### Simulated or local-only

- The submitted research brief above is a local service-response fixture.
- Existing provider evidence tests use injected fixtures and do not prove live
  provider pricing.
- No paid research-service request is made by the local demo.

### Not completed yet

- Two current, evidence-backed research-service provider records with
  verified task-specific prices.
- A real research-service adapter that returns the brief.
- A real Base Sepolia x402 settlement and on-chain reconciliation.
- Forge installation and Jira task/approval integration.
- Public deployment.

The x402 implementation fails closed when credentials or settlement evidence
are missing. `READY` must not be presented as `PAID`, and payment settlement
must not be presented as task verification.

## Environment variable names

Only configure these when the team explicitly approves the corresponding
integration. Never commit their values:

```text
BRIGHT_DATA_API_KEY
BRIGHT_DATA_SERP_ZONE
SPENDPILOT_PAYMENT_TOKEN
PAYMENT_PRIVATE_KEY
BASE_SEPOLIA_RPC_URL
EVM_ADDRESS
FACILITATOR_URL
OPENAI_API_KEY
OPENAI_SPEND_INTAKE_MODEL
```

The safe local demo does not require any of them.
