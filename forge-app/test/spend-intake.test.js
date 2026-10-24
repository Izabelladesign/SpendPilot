import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSpendRequestWithExtractor } from '../src/spend-intake.js';

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
test('parser has no payment, order, database, or Jira-write action', async () => {
  let calls = 0;
  const result = await parseSpendRequestWithExtractor({ request: 'Buy keyboards' }, async () => { calls += 1; return completeTask; });
  assert.equal(calls, 1); assert.equal(result.isReadyForNextStep, true);
  assert.deepEqual(Object.keys(result).sort(), ['clarificationQuestions', 'isReadyForNextStep', 'missingFields', 'parsedTask', 'status', 'validationErrors']);
});
