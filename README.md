# SpendPilot

**SpendPilot is a governed procurement agent for teams.** It turns a company need into a reviewable decision: structure the request, compare providers, apply spending controls, route approval, prepare payment, execute authorized work, and verify the outcome.

Instead of giving an agent an open-ended company card, SpendPilot creates a transparent **Spend Passport** for every decision—linking the request, evidence, recommendation, budget, approval, payment state, and verification result.

## Why SpendPilot

Organizations want AI agents to take useful action, but they need visibility and control before money moves. SpendPilot helps teams:

- Set clear budget and policy boundaries for agent activity.
- Compare eligible providers using documented evidence.
- Keep recommendation, approval, payment, and task completion as distinct states.
- Require human review when policy requires it.
- Maintain an auditable record of each decision.

## Demo Flow

Our primary demo follows a company request to compare GitHub Copilot and Cursor for a 50-person engineering team:

```text
Company request
  → Research and provider comparison
  → Recommendation with cost evidence
  → Purchase request and governance review
  → Approval and payment preparation
  → Authorized execution
  → Output verification
  → Spend Passport and enterprise dashboard
```

The core safety principle: **a successful payment is not the same thing as a successful task.** A task is complete only after its delivered outcome is verified.

## Core Capabilities

### Structured Intake

SpendPilot converts natural-language requests into a structured task specification containing objectives, budget, quantity, quality expectations, constraints, deadlines, and missing-information questions.

### Provider Research and Optimization

The research layer gathers provider and pricing evidence. The optimizer ranks only providers with comparable pricing and sufficient evidence; it does not guess missing costs, billing terms, currencies, or capabilities.

### Governance and Approvals

Every recommendation becomes a purchase request with a stable identity and idempotency key. Governance evaluates the persisted request against approved providers, spending authority, budget, and approval requirements before a payment can be prepared.

### Payment Lifecycle

SpendPilot keeps payment lifecycle states explicit:

```text
Requested → Recommended → Approved / Review / Blocked → READY → Settled → Executing → Verified
```

`READY` means a payment may be prepared under the required controls; it does not mean that funds have moved or that the task succeeded.

### Outcome Verification

The workflow checks delivered work against the original task. For the research-brief scenario, it verifies a readable summary, coverage of both requested products, pricing and security sections, at least two unique HTTPS sources, and clear treatment of unverified information.

## Architecture

```text
Atlassian Jira / Rovo
        │
        ▼
Forge SpendPilot intake agent
        │
        ▼
FastAPI workflow
  ├── Task parser
  ├── Provider research
  ├── Cost optimizer
  ├── Governance and approval
  ├── Payment preparation
  ├── Execution agent
  └── Outcome verifier
        │
        ▼
Enterprise dashboard + Spend Passport
```

## Technology

- **Atlassian Forge + Rovo** for Jira-facing agent experiences
- **FastAPI + Python** for workflow, policy, provider, and verification services
- **SQLAlchemy** for persisted tasks, purchase requests, approvals, payments, and events
- **Next.js + React** for the enterprise dashboard
- **OpenAI structured outputs** for request parsing
- **Bright Data** provider-research connector
- **Coinbase x402-compatible payment flow** for controlled agent payments

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

The API documentation is available at `http://127.0.0.1:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000/enterprise` for the enterprise dashboard.

### Tests

```bash
cd backend
python -m pytest -q
```

## Safety Model

SpendPilot is intentionally designed around guarded handoffs:

- Provider evidence is cited and time-stamped.
- Missing or incomparable information prevents a recommendation.
- Governance evaluates persisted purchase requests, not an agent's claim that it followed policy.
- Idempotency keys protect against duplicate purchase preparation.
- Approval, payment, execution, and verification are separate steps.
- External actions require explicit authorization.

## Team

Built for the Atlassian Agentic Workforce Challenge and Coinbase Payment Agents track.

SpendPilot demonstrates how agents can deliver real operational value while preserving the controls companies need to trust them.
