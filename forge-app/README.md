# SpendPilot Forge intake shell

This is the read-only SpendPilot Rovo intake shell. It accepts a natural-language
spending request, extracts validated planning data, and returns missing fields
and clarification questions. It does not approve spending, read or write Jira,
shop, research providers, persist data, or take a payment action.

## Local development

Use Node.js 22 or 24 and Forge CLI 14 or later.

```bash
npm install
npm test
```

The parser expects `OPENAI_API_KEY` to be configured as an encrypted Forge
variable when deployed. Do not place credentials in source or `.env` files.

## Register and deploy

Developer 4 owns final Jira integration and deployment. Before deployment,
register this app (or insert the team's registered app ID into `manifest.yml`):

```bash
forge register
forge deploy
forge install --demo-site --product jira
```

The manifest includes an external-fetch permission for the OpenAI host. After
that permission or any future scope change, deploy and run the appropriate
`forge install --upgrade` command for the team's Jira site.

## Integration boundary

This shell is intentionally temporary as a local intake experience. It must
later call the shared FastAPI backend's SP-101 parser rather than maintain a
second parser implementation. Developer 4 owns the final Forge/Jira surface;
this project must remain read-only until that shared integration is defined.
