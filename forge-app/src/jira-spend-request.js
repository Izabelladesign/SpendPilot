import api, { route } from '@forge/api';

const toText = (value) => (typeof value === 'string' ? value.trim() : '');

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

  return {
    status: 'created',
    issueKey: body.key || null,
    issueId: body.id || null,
    issueUrl: body.self || null,
    message: body.key
      ? `Created Jira spend-request issue ${body.key}. Approval and purchase remain separate.`
      : 'Created the Jira spend-request issue.',
  };
};
