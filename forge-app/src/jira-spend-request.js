import api, { route } from '@forge/api';

const toText = (value) => (typeof value === 'string' ? value.trim() : '');
const LOCAL_DEMO_BACKEND_URL = 'http://127.0.0.1:8000';

const backendUnavailable = (message) => ({
  status: 'unavailable',
  taskId: null,
  message,
});

const parseBudget = (value) => {
  const normalized = toText(value).replaceAll(',', '');
  const match = normalized.match(/(?:\$?\s*(\d+(?:\.\d+)?)\s*([A-Za-z]{3})|([A-Za-z]{3})\s*\$?\s*(\d+(?:\.\d+)?))/);
  if (!match) return null;
  const amount = Number(match[1] || match[4]);
  const currency = (match[2] || match[3]).toUpperCase();
  if (!Number.isFinite(amount) || amount <= 0 || !/^[A-Z]{3}$/.test(currency)) return null;
  return { amount: amount.toFixed(2), currency };
};

const isLoopbackUrl = (value) => /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(?:\/|$)/i.test(value);

const documentText = (node) => {
  if (!node || typeof node !== 'object') return '';
  if (node.type === 'text' && typeof node.text === 'string') return node.text;
  if (!Array.isArray(node.content)) return '';
  return node.content.map(documentText).join(node.type === 'doc' ? '\n' : '');
};

const syncWithBackend = async ({
  backendUrl,
  backendToken,
  issueKey,
  description,
  budget,
  constraints,
  quantity,
  qualityTarget,
  requestBackend,
} = {}) => {
  const normalizedUrl = toText(backendUrl).replace(/\/$/, '');
  if (!normalizedUrl) {
    return {
      status: 'not_configured',
      taskId: null,
      message: 'Backend sync is not configured. The Jira issue was created; no spend action was taken.',
    };
  }

  const parsedBudget = parseBudget(budget);
  if (!parsedBudget) {
    return backendUnavailable('Backend sync skipped because the budget format could not be parsed.');
  }

  const request = requestBackend || (isLoopbackUrl(normalizedUrl) ? globalThis.fetch : api.fetch);
  if (typeof request !== 'function') {
    return backendUnavailable('Backend sync is unavailable in this Forge runtime.');
  }

  try {
    const response = await request(`${normalizedUrl}/integrations/jira/spend-requests`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(toText(backendToken) ? { 'X-SpendPilot-Sync-Token': backendToken } : {}),
      },
      body: JSON.stringify({
        jiraIssueKey: issueKey,
        objective: description,
        budget: parsedBudget,
        quantity: quantity || 1,
        qualityTarget: qualityTarget || 'Return a sourced recommendation for human review.',
        constraints,
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      return backendUnavailable(`Backend sync failed (HTTP ${response.status}). The Jira issue remains available for review.`);
    }
    return {
      status: body.status || 'linked',
      taskId: body.task?.id || null,
      message: body.message || 'Jira issue linked to the backend task.',
    };
  } catch {
    return backendUnavailable('Backend sync could not reach the configured API. The Jira issue remains available for review.');
  }
};

/**
 * Link an already-created Jira issue (for example KAN-4) to the backend task
 * timeline. This reads Jira fields only; it never edits the issue or spends.
 */
export const linkExistingJiraSpendRequest = async ({
  issueKey,
  requestJira,
  backendUrl,
  backendToken,
  requestBackend,
} = {}) => {
  const normalizedIssueKey = toText(issueKey).toUpperCase();
  if (!/^[A-Z][A-Z0-9_]*-\d+$/.test(normalizedIssueKey)) {
    return {
      status: 'invalid_request',
      issueKey: null,
      backend: null,
      message: 'Enter a Jira issue key such as KAN-4.',
    };
  }

  const jiraClient = api.asUser();
  const request = requestJira || jiraClient.requestJira.bind(jiraClient);
  let response;
  try {
    response = await request(route`/rest/api/3/issue/${normalizedIssueKey}?fields=summary,description`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    });
  } catch {
    return {
      status: 'jira_unavailable',
      issueKey: normalizedIssueKey,
      backend: null,
      message: 'Jira could not be reached. No spend action was taken.',
    };
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    return {
      status: 'jira_error',
      issueKey: normalizedIssueKey,
      backend: null,
      message: `Jira could not read ${normalizedIssueKey} (HTTP ${response.status}). Check the issue key and permissions.`,
    };
  }

  const fields = body.fields || {};
  const issueDescription = documentText(fields.description) || toText(fields.summary);
  const budgetLine = issueDescription.match(/(?:^|\n)Budget:\s*([^\n]+)/i)?.[1];
  const constraintsLine = issueDescription.match(/(?:^|\n)Constraints:\s*([^\n]+)/i)?.[1] || '';
  const budget = parseBudget(budgetLine);
  if (!budget) {
    return {
      status: 'invalid_request',
      issueKey: normalizedIssueKey,
      backend: null,
      message: `Jira issue ${normalizedIssueKey} does not contain a readable Budget: amount currency line.`,
    };
  }

  const constraints = constraintsLine && !/^none specified$/i.test(constraintsLine)
    ? constraintsLine.split(',').map(toText).filter(Boolean)
    : [];
  const backend = await syncWithBackend({
    backendUrl: backendUrl ?? process.env.SPENDPILOT_BACKEND_URL ?? LOCAL_DEMO_BACKEND_URL,
    backendToken: backendToken ?? process.env.SPENDPILOT_BACKEND_TOKEN,
    issueKey: normalizedIssueKey,
    description: issueDescription,
    budget: `${budget.amount} ${budget.currency}`,
    constraints,
    requestBackend,
  });

  return {
    status: 'linked',
    issueKey: normalizedIssueKey,
    backend,
    message: backend.message,
  };
};

const paragraphDocument = (text) => ({
  type: 'doc',
  version: 1,
  content: text.split(/\r?\n/).filter(Boolean).map((line) => ({
    type: 'paragraph',
    content: [{ type: 'text', text: line }],
  })),
});

const invalid = (message) => ({
  status: 'invalid_request',
  issueKey: null,
  issueId: null,
  issueUrl: null,
  message,
});

/**
 * Create a Jira issue from an explicitly requested, structured spend request.
 * This writes a planning/review issue only. It never approves or pays.
 * requestJira is injectable so the contract can be tested without Jira access.
 */
export const createJiraSpendRequest = async ({
  projectKey,
  summary,
  description,
  budget,
  constraints = [],
  quantity = 1,
  qualityTarget,
  backendUrl,
  backendToken,
  requestBackend,
  requestJira,
} = {}) => {
  const normalizedProjectKey = toText(projectKey);
  const normalizedSummary = toText(summary);
  const normalizedDescription = toText(description);
  const normalizedBudget = toText(budget);
  const normalizedConstraints = Array.isArray(constraints)
    ? constraints.map(toText).filter(Boolean)
    : typeof constraints === 'string'
      ? constraints.split(',').map(toText).filter(Boolean)
      : [];

  if (!normalizedProjectKey) return invalid('A Jira project key is required.');
  if (!normalizedSummary || normalizedSummary.length > 255) {
    return invalid('A Jira issue summary between 1 and 255 characters is required.');
  }
  if (!normalizedDescription) return invalid('A spend request description is required.');
  if (!normalizedBudget) return invalid('A budget is required for the Jira spend request.');

  const jiraClient = api.asUser();
  const request = requestJira || jiraClient.requestJira.bind(jiraClient);
  const issueDescription = [
    normalizedDescription,
    `Budget: ${normalizedBudget}`,
    normalizedConstraints.length
      ? `Constraints: ${normalizedConstraints.join(', ')}`
      : 'Constraints: None specified',
    'SpendPilot workflow: Intake -> Research -> Recommendation -> Human approval -> Payment -> Verification.',
    'SpendPilot status: Intake captured; approval and purchase are separate steps.',
    'Decision packet: evidence, budget cap, selected provider, approval state, payment state, and verification state are tracked separately.',
    'License health: after purchase, SpendPilot can flag unused or unactivated access for review before renewal.',
  ].join('\n');

  let response;
  try {
    response = await request(route`/rest/api/3/issue`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        fields: {
          project: { key: normalizedProjectKey },
          summary: normalizedSummary,
          description: paragraphDocument(issueDescription),
          issuetype: { name: 'Task' },
          labels: ['spendpilot', 'spend-request', 'spend-passport'],
        },
      }),
    });
  } catch {
    return {
      status: 'jira_unavailable',
      issueKey: null,
      issueId: null,
      issueUrl: null,
      message: 'Jira could not be reached. No spend action was taken.',
    };
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    return {
      status: 'jira_error',
      issueKey: null,
      issueId: null,
      issueUrl: null,
      message: `Jira rejected the issue request (HTTP ${response.status}). Check the project key and your Jira permissions.`,
    };
  }

  const backend = await syncWithBackend({
    backendUrl: backendUrl ?? process.env.SPENDPILOT_BACKEND_URL ?? LOCAL_DEMO_BACKEND_URL,
    backendToken: backendToken ?? process.env.SPENDPILOT_BACKEND_TOKEN,
    issueKey: body.key,
    description: normalizedDescription,
    budget: normalizedBudget,
    constraints: normalizedConstraints,
    quantity,
    qualityTarget,
    requestBackend,
  });

  return {
    status: 'created',
    issueKey: body.key || null,
    issueId: body.id || null,
    issueUrl: body.self || null,
    backend,
    message: body.key
      ? `Created Jira spend-request issue ${body.key}. ${backend.message}`
      : 'Created the Jira spend-request issue.',
  };
};
