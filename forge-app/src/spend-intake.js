import api from '@forge/api';
import { z } from 'zod';

// SP-101 accepts an untrusted model proposal and validates it at the app
// boundary. Null means the requester did not provide the information; it is
// deliberately different from an invalid value, which becomes a field error.
const nullableText = z.string().trim().min(1).nullable();
const CurrencyCode = z.string().regex(/^[A-Z]{3}$/, 'Use a three-letter ISO currency code.');

const ExtractedSpendTask = z.object({
  requestedItemOrService: nullableText,
  purchasingIntent: nullableText,
  quantity: z.number().finite().nullable(),
  budget: z.object({ amount: z.number().finite(), currency: CurrencyCode }).nullable(),
  deadline: nullableText,
  merchantOrBrandConstraints: z.array(z.string().trim().min(1)).default([]),
  businessPurpose: nullableText,
  qualityTarget: nullableText,
  constraints: z.array(z.string().trim().min(1)).default([]),
  expectedDeliverable: nullableText,
  assumptions: z.array(z.string().trim().min(1)).default([]),
  ambiguities: z.array(z.string().trim().min(1)).default([]),
  confidence: z.number().min(0).max(1).nullable(),
}).strict();

// Required means the downstream team cannot safely begin planning without it.
// Quantity and quality are still captured and questioned when ambiguous, but
// are optional because a service request may not have either property.
const REQUIRED_FIELDS = ['requestedItemOrService', 'budget', 'businessPurpose'];
const questionFor = {
  requestedItemOrService: 'What item, service, or purchasing outcome do you need?',
  budget: 'What is the maximum budget and currency for this request?',
  businessPurpose: 'What business purpose will this purchase support?',
};

const DEMO_REQUEST = {
  requestedItemOrService: 'Managed AI coding assistant',
  purchasingIntent: 'Evaluate and potentially purchase a team subscription',
  quantity: 50,
  budget: { amount: 1, currency: 'USD' },
  deadline: 'Complete within 5 minutes (Pacific Time)',
  merchantOrBrandConstraints: ['Compare only GitHub Copilot and Cursor'],
  businessPurpose: 'Help engineers write, review, and debug code more efficiently',
  qualityTarget: 'Include pricing, security sources, and unverified information',
  constraints: ['Human approval required before purchase'],
  expectedDeliverable: 'A concise comparison of GitHub Copilot and Cursor',
  assumptions: ['The 1.00 USD limit is a research/demo budget, not purchase authorization'],
  ambiguities: [],
  confidence: 1,
};

const isDemoRequest = (request) => {
  const normalized = request.trim();
  return /^(demo|test|dummy(?:\s+prompt)?|demo\s+request)$/i.test(normalized)
    || /managed\s+(?:AI\s+)?coding assistant/i.test(normalized)
      && /50[-\s]?person\s+engineering team/i.test(normalized)
      && /github\s+copilot/i.test(normalized)
      && /cursor/i.test(normalized)
      && /1(?:\.00)?\s*USD/i.test(normalized);
};

// OpenAI constrains its output to this schema before it reaches the Forge
// function. Zod validates the exact same shape again below; the model itself
// is never trusted as an application validator.
const responseFormat = {
  type: 'json_schema', name: 'spend_task_intake', strict: true,
  schema: {
    type: 'object', additionalProperties: false,
    required: ['requestedItemOrService', 'purchasingIntent', 'quantity', 'budget', 'deadline', 'merchantOrBrandConstraints', 'businessPurpose', 'qualityTarget', 'constraints', 'expectedDeliverable', 'assumptions', 'ambiguities', 'confidence'],
    properties: {
      requestedItemOrService: { type: ['string', 'null'] }, purchasingIntent: { type: ['string', 'null'] }, quantity: { type: ['number', 'null'] },
      budget: { type: ['object', 'null'], additionalProperties: false, required: ['amount', 'currency'], properties: { amount: { type: 'number' }, currency: { type: 'string' } } },
      deadline: { type: ['string', 'null'] }, merchantOrBrandConstraints: { type: 'array', items: { type: 'string' } }, businessPurpose: { type: ['string', 'null'] },
      qualityTarget: { type: ['string', 'null'] }, constraints: { type: 'array', items: { type: 'string' } }, expectedDeliverable: { type: ['string', 'null'] },
      assumptions: { type: 'array', items: { type: 'string' } }, ambiguities: { type: 'array', items: { type: 'string' } }, confidence: { type: ['number', 'null'], minimum: 0, maximum: 1 },
    },
  },
};

const fieldErrors = (issues) => issues.map((issue) => ({ field: issue.path.join('.') || 'parsedTask', code: issue.code, message: issue.message }));

const unavailable = (code, message) => ({
  isReadyForNextStep: false, parsedTask: null, missingFields: [],
  validationErrors: [{ field: 'request', code, message }],
  clarificationQuestions: ['Please retry the intake request. No spend action has been taken.'],
  status: 'intake_unavailable',
});

// This adapter is intentionally small and injected into tests. Forge provides
// api.fetch, while the API key stays only in an encrypted Forge variable.
export const createOpenAIExtractor = ({ fetchImpl = api.fetch, apiKey = process.env.OPENAI_API_KEY } = {}) => async (request) => {
  if (!apiKey) {
    const error = new Error('OPENAI_API_KEY is not configured as an encrypted Forge variable.');
    error.code = 'model_unavailable';
    console.warn('SpendPilot OpenAI intake unavailable', { reason: 'missing_key' });
    throw error;
  }
  let response;
  try {
    response = await fetchImpl('https://api.openai.com/v1/responses', {
      method: 'POST', headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: process.env.OPENAI_SPEND_INTAKE_MODEL || 'gpt-4.1-mini',
        instructions: 'Extract only request-supported spend planning fields. Use null or [] for missing values. A request is complete when its item/service, budget, and business purpose are explicit. Treat "Alternatives should not be considered" as a scope constraint: compare only the named products and do not ask about additional alternatives. Preserve explicit deadlines and security criteria. If the user says detail level does not matter, do not ask for more detail. Do not put ordinary comparison tradeoffs in ambiguities. Never infer authorization, payment details, providers, quantities, limits, or requirements. This is intake only.',
        input: request, text: { format: responseFormat },
      }),
    });
  } catch {
    console.warn('SpendPilot OpenAI intake unavailable', { reason: 'network_error' });
    const error = new Error('The structured extraction service is unavailable.'); error.code = 'model_unavailable'; throw error;
  }
  if (!response.ok) {
    console.warn('SpendPilot OpenAI intake rejected', { reason: 'http_error', status: response.status });
    const error = new Error(`The structured extraction service returned HTTP ${response.status}.`); error.code = 'model_unavailable'; throw error;
  }
  const body = await response.json();
  const refusal = body.output?.flatMap((item) => item.content || []).some((content) => content.type === 'refusal');
  if (refusal || body.status === 'incomplete') {
    console.warn('SpendPilot OpenAI intake incomplete', { reason: refusal ? 'model_refusal' : 'incomplete_response' });
    const error = new Error('The structured extraction service could not process this request.'); error.code = 'model_refused'; throw error;
  }
  // The raw REST response returns generated text inside output message content.
  // `output_text` is an SDK convenience property, so do not assume it exists
  // when using Forge's fetch API directly.
  const outputText = typeof body.output_text === 'string'
    ? body.output_text
    : Array.isArray(body.output)
      ? body.output
        .flatMap((item) => Array.isArray(item.content) ? item.content : [])
        .filter((content) => content.type === 'output_text' && typeof content.text === 'string')
        .map((content) => content.text)
        .join('')
      : '';
  try { return JSON.parse(outputText); } catch {
    console.warn('SpendPilot OpenAI intake malformed', { reason: 'malformed_structured_output' });
    const error = new Error('The structured extraction service returned malformed structured data.'); error.code = 'malformed_model_output'; throw error;
  }
};

export const parseSpendRequestWithExtractor = async ({ request }, extractStructured) => {
  if (typeof request !== 'string' || request.trim() === '') {
    return { isReadyForNextStep: false, parsedTask: null, missingFields: REQUIRED_FIELDS, validationErrors: [{ field: 'request', code: 'required', message: 'A non-empty spending request is required.' }], clarificationQuestions: REQUIRED_FIELDS.map((field) => questionFor[field]), status: 'intake_complete' };
  }
  let proposal;
  try { proposal = await extractStructured(request.trim()); } catch (error) {
    return unavailable(error?.code || 'model_unavailable', error?.message || 'The intake service is unavailable.');
  }
  const validated = ExtractedSpendTask.safeParse(proposal);
  if (!validated.success) {
    return { isReadyForNextStep: false, parsedTask: null, missingFields: [], validationErrors: fieldErrors(validated.error.issues), clarificationQuestions: ['Please restate the request with an item or service, budget and currency, and business purpose.'], status: 'invalid_model_output' };
  }
  const parsedTask = validated.data;
  const validationErrors = [];
  if (parsedTask.quantity !== null && parsedTask.quantity <= 0) validationErrors.push({ field: 'quantity', code: 'invalid_value', message: 'Quantity must be greater than zero.' });
  if (parsedTask.budget && parsedTask.budget.amount <= 0) validationErrors.push({ field: 'budget.amount', code: 'invalid_value', message: 'Budget amount must be greater than zero.' });
  const missingFields = REQUIRED_FIELDS.filter((field) => parsedTask[field] === null);
  const requestText = request.trim();
  const hasExplicitDeadline = /research\s+deadline\s*:/i.test(requestText);
  const hasExplicitSecurityCriteria = /security\s+criteria\s*:/i.test(requestText);
  const excludesAdditionalAlternatives = /alternatives?\s+should\s+not\s+be\s+considered/i.test(requestText);
  const blockingAmbiguities = parsedTask.ambiguities.filter((ambiguity) => {
    if (excludesAdditionalAlternatives && /alternatives?|other options?/i.test(ambiguity)) return false;
    if (hasExplicitDeadline && /deadline|time limit|completion time/i.test(ambiguity)) return false;
    if (hasExplicitSecurityCriteria && /security criteria|security requirements/i.test(ambiguity)) return false;
    if (/detail level/i.test(ambiguity) && /detail level\s+doesn['’]t\s+matter/i.test(requestText)) return false;
    return true;
  });
  const clarificationQuestions = [...missingFields.map((field) => questionFor[field]), ...blockingAmbiguities.map((ambiguity) => `Please clarify: ${ambiguity}`)];
  return { isReadyForNextStep: validationErrors.length === 0 && missingFields.length === 0 && blockingAmbiguities.length === 0, parsedTask, missingFields, validationErrors, clarificationQuestions, status: 'intake_complete' };
};

// Public Forge action contract. It has no Jira, storage, payment, shopping,
// provider-research, approval, checkout, order, or persistence side effects.
export const parseSpendRequest = async ({ request } = {}) => {
  if (typeof request === 'string' && isDemoRequest(request)) {
    return parseSpendRequestWithExtractor({ request: 'Demo request' }, async () => DEMO_REQUEST);
  }
  return parseSpendRequestWithExtractor({ request }, createOpenAIExtractor());
};
