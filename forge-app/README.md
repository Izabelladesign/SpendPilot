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

## Integration boundary

The Jira action is intentionally limited to creating a review issue. Approval,
provider selection, purchase execution, and license management still belong to
the shared backend and must remain separate authorization steps.
