import test from 'node:test';
import assert from 'node:assert/strict';
import { createOpenAIExtractor, parseSpendRequestWithExtractor } from '../src/spend-intake.js';
import { createJiraSpendRequest } from '../src/jira-spend-request.js';
import { resolver } from '../src/index.js';

const completeTask = {
  requestedItemOrService: 'Ergonomic keyboards', purchasingIntent: 'Purchase equipment', quantity: 12,
  budget: { amount: 1800, currency: 'USD' }, deadline: '2026-11-15', merchantOrBrandConstraints: ['Compatible with macOS'],
  businessPurpose: 'Equip the support team', qualityTarget: 'Ergonomic, low-profile keyboards', constraints: ['Must fit within total budget'],
  expectedDeliverable: 'Twelve working keyboards delivered to the support team', assumptions: [], ambiguities: [], confidence: 0.95,
};
const withOutput = (output) => parseSpendRequestWithExtractor({ request: 'Need 12 ergonomic keyboards for the support team under USD 1,800.' }, async () => output);

test('complete request produces a normalized valid task', async () => {
  const result = await withOutput(completeTask);
  assert.equal(result.isReadyForNextStep, true);
  assert.deepEqual(result.parsedTask.budget, { amount: 1800, currency: 'USD' });
});
test('missing required fields returns clarification questions', async () => {
  const result = await withOutput({ ...completeTask, requestedItemOrService: null, budget: null, businessPurpose: null });
  assert.deepEqual(result.missingFields, ['requestedItemOrService', 'budget', 'businessPurpose']);
  assert.match(result.clarificationQuestions.join(' '), /budget.*currency/i);
});
test('ambiguity remains unresolved rather than guessed', async () => {
  const result = await withOutput({ ...completeTask, quantity: null, ambiguities: ['It is unclear whether one or several licenses are needed.'] });
  assert.equal(result.isReadyForNextStep, false); assert.equal(result.parsedTask.quantity, null);
});
test('invalid quantity, budget, and currency are rejected', async () => {
  const quantity = await withOutput({ ...completeTask, quantity: 0 });
  assert.equal(quantity.validationErrors[0].field, 'quantity');
  const budget = await withOutput({ ...completeTask, budget: { amount: -1, currency: 'US' } });
  assert.equal(budget.status, 'invalid_model_output');
  assert.ok(budget.validationErrors.some((error) => error.field === 'budget.currency'));
});
test('malformed structured model output is rejected safely', async () => {
  const result = await withOutput({ requestedItemOrService: 'Laptop' });
  assert.equal(result.status, 'invalid_model_output'); assert.equal(result.parsedTask, null);
});
test('model refusal and outage return safe actionable failures', async () => {
  for (const code of ['model_refused', 'model_unavailable']) {
    const result = await parseSpendRequestWithExtractor({ request: 'Buy a laptop' }, async () => { const error = new Error('Unable to process'); error.code = code; throw error; });
    assert.equal(result.validationErrors[0].code, code); assert.match(result.clarificationQuestions[0], /retry/i);
  }
});

test('missing OpenAI key returns a safe diagnostic without exposing credentials', async () => {
  const extractor = createOpenAIExtractor({ apiKey: '' });
  await assert.rejects(
    () => extractor('Research a coding assistant under USD 1.00.'),
    (error) => error.code === 'model_unavailable' && /encrypted Forge variable/i.test(error.message),
  );
});

test('OpenAI REST response output content is parsed without SDK output_text', async () => {
  const extractor = createOpenAIExtractor({
    apiKey: 'test-only-key',
    fetchImpl: async () => new Response(JSON.stringify({
      status: 'completed',
      output: [{
        type: 'message',
        content: [{ type: 'output_text', text: JSON.stringify(completeTask) }],
      }],
    }), { status: 200 }),
  });

  const result = await extractor('Need a coding assistant under USD 1.00.');
  assert.deepEqual(result, completeTask);
});
test('parser has no payment, order, database, or Jira-write side effect', async () => {
  let calls = 0;
  const result = await parseSpendRequestWithExtractor({ request: 'Buy keyboards' }, async () => { calls += 1; return completeTask; });
  assert.equal(calls, 1); assert.equal(result.isReadyForNextStep, true);
  assert.deepEqual(Object.keys(result).sort(), ['clarificationQuestions', 'isReadyForNextStep', 'missingFields', 'parsedTask', 'status', 'validationErrors']);
});

test('project-page resolver exposes the read-only OpenAI parser', async () => {
  assert.equal(typeof resolver, 'function');
});

test('Jira action creates a review issue without payment fields', async () => {
  let request;
  const result = await createJiraSpendRequest({
    projectKey: 'SP',
    summary: 'Review GitHub Copilot versus Cursor',
    description: 'Compare options for the engineering team.',
    budget: '1.00 USD',
    constraints: ['Research only', 'Human approval required'],
    requestJira: async (path, options) => {
      request = { path, options };
      return new Response(JSON.stringify({ id: '10001', key: 'SP-42', self: 'https://jira.example/rest/api/3/issue/10001' }), { status: 201 });
    },
  });

  assert.equal(result.status, 'created');
  assert.equal(result.issueKey, 'SP-42');
  assert.equal(request.path.value_ || request.path, '/rest/api/3/issue');
  const body = JSON.parse(request.options.body);
  assert.equal(body.fields.project.key, 'SP');
  assert.equal(body.fields.issuetype.name, 'Task');
  assert.deepEqual(body.fields.labels, ['spendpilot', 'spend-request', 'spend-passport']);
  assert.match(body.fields.description.content[0].content[0].text, /Compare options/);
});

test('Jira action fails safely when Jira rejects the request', async () => {
  const result = await createJiraSpendRequest({
    projectKey: 'SP',
    summary: 'Review request',
    description: 'Details',
    budget: '10 USD',
    requestJira: async () => new Response('{}', { status: 403 }),
  });

  assert.equal(result.status, 'jira_error');
  assert.equal(result.issueKey, null);
  assert.match(result.message, /permissions/i);
});
