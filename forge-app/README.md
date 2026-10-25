# SpendPilot Forge Jira intake

This Forge app accepts a natural-language spending request, extracts validated
planning data, and can create a Jira Task issue for review after the user
explicitly asks it to do so. It does not approve spending, purchase anything,
reserve funds, or take a payment action.

## Local development

Use Node.js 22 or 24 and Forge CLI 14 or later.

```bash
npm install
npm test
```

The parser expects `OPENAI_API_KEY` to be configured as an encrypted Forge
variable when deployed. OpenAI API usage may incur charges. Do not place
credentials in source or `.env` files.

To configure the live parser, set the encrypted Forge variable interactively
from the `forge-app` directory:

```bash
forge variables set --encrypt OPENAI_API_KEY
```

Only do this if the team has approved OpenAI usage and a billing account is
configured. Jira issue creation does not require a personal Atlassian API
token; Forge uses the logged-in Jira user and the declared Jira scope.

## Register and deploy

Developer 4 owns final Jira integration and deployment. Before deployment,
register this app (or insert the team's registered app ID into `manifest.yml`):

```bash
forge register
forge deploy
forge install --site https://spendpilot.atlassian.net --product jira
```

The manifest includes an external-fetch permission for the OpenAI host and a
`write:jira-work` scope for creating review issues. After deploying, upgrade
the installation so Jira grants the new scope:

```bash
forge install --upgrade --site https://spendpilot.atlassian.net --product jira
```

## Link Jira issues to the shared backend

After the Forge action creates a Jira issue, it can register the same request
as a backend task through `POST /integrations/jira/spend-requests`. The link is
idempotent: retrying the same Jira issue key returns the existing task instead
of creating a duplicate. This creates a local task record and timeline only;
it does not approve, reserve, purchase, or charge money.

For the local demo, start the backend and run the Forge tunnel from separate
terminals. The tunnel runs the Forge resolver on your machine, so it can call
the local API without exposing it publicly:

```bash
# Terminal 1, from the repository root
cd backend
./.venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 2, from forge-app
cd forge-app
# Optional: this is the default for the local Forge tunnel.
export SPENDPILOT_BACKEND_URL=http://127.0.0.1:8000
./node_modules/.bin/forge tunnel
```

Then refresh the Jira **SpendPilot** project page and create the request. The
confirmation should show both the Jira key (for example `KAN-4`) and the
backend task ID. The local tunnel variable is not available to a deployed
Forge function, so do not expect a deployed app to reach `localhost`.

If the Jira issue already exists, enter its key in **Link existing issue to
backend** on the same page. The app reads the issue’s existing description and
links it idempotently; it does not create a second Jira issue.

For a deployed connection, host the backend at an HTTPS origin, then allowlist
that origin when deploying and set the runtime URL in the development
environment:

```bash
export SPENDPILOT_BACKEND_EGRESS=https://your-backend.example.com
./node_modules/.bin/forge deploy
./node_modules/.bin/forge variables set SPENDPILOT_BACKEND_URL https://your-backend.example.com
./node_modules/.bin/forge install --upgrade --site https://spendpilot.atlassian.net --product jira
```

If `SPENDPILOT_BACKEND_URL` is not set, the Jira issue still succeeds and the
UI reports that backend sync is not configured. No spend action is taken.

## Integration boundary

The Jira action is intentionally limited to creating a review issue. Approval,
provider selection, purchase execution, and license management still belong to
the shared backend and must remain separate authorization steps.

### Test Jira without an OpenAI key

You can verify the Jira connection before configuring OpenAI by asking Rovo for
a direct structured issue:

```text
Create a Jira spend request in project SP.
Summary: Compare GitHub Copilot and Cursor.
Description: Research both products for a 50-person engineering team and return pricing, security, sources, and unknowns.
Budget: 1.00 USD.
Constraints: Research only, human approval required.
```

This invokes only the Jira action. It creates a review issue and does not call
OpenAI, approve spending, or make a purchase.

### Jira project page fallback

If Rovo is not available on the site, open the Jira project and select the
**SpendPilot** tab in the project navigation. The page provides the same Jira
review-issue action without requiring Rovo or an OpenAI key.
