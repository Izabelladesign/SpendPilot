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
    throw error;
  }
  let response;
  try {
    response = await fetchImpl('https://api.openai.com/v1/responses', {
      method: 'POST', headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: process.env.OPENAI_SPEND_INTAKE_MODEL || 'gpt-4.1-mini',
        instructions: 'Extract only request-supported spend planning fields. Use null or [] for missing values. Never infer authorization, payment details, providers, quantities, limits, or requirements. This is intake only.',
        input: request, text: { format: responseFormat },
      }),
    });
  } catch {
    const error = new Error('The structured extraction service is unavailable.'); error.code = 'model_unavailable'; throw error;
  }
  if (!response.ok) {
    const error = new Error(`The structured extraction service returned HTTP ${response.status}.`); error.code = 'model_unavailable'; throw error;
  }
  const body = await response.json();
  const refusal = body.output?.flatMap((item) => item.content || []).some((content) => content.type === 'refusal');
  if (refusal || body.status === 'incomplete') {
    const error = new Error('The structured extraction service could not process this request.'); error.code = 'model_refused'; throw error;
  }
  // The provider schema-constrains output_text; parsing only decodes its
  // transport representation. The application boundary validation follows.
  try { return JSON.parse(body.output_text); } catch {
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
  const clarificationQuestions = [...missingFields.map((field) => questionFor[field]), ...parsedTask.ambiguities.map((ambiguity) => `Please clarify: ${ambiguity}`)];
  return { isReadyForNextStep: validationErrors.length === 0 && missingFields.length === 0 && parsedTask.ambiguities.length === 0, parsedTask, missingFields, validationErrors, clarificationQuestions, status: 'intake_complete' };
};

// Public Forge action contract. It has no Jira, storage, payment, shopping,
// provider-research, approval, checkout, order, or persistence side effects.
export const parseSpendRequest = async ({ request } = {}) => parseSpendRequestWithExtractor({ request }, createOpenAIExtractor());
