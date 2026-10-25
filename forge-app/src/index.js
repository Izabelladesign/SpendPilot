// Entry point for the SpendPilot Rovo agent.
//
// Rovo invokes the agent directly from the rovo:agent module. Intake remains
// read-only; the Jira action below creates a review issue only after the user
// explicitly asks for it. Neither action approves or pays for anything.

import { parseSpendRequest as parseRequest } from './spend-intake.js';
import { createJiraSpendRequest as createJiraIssue } from './jira-spend-request.js';
import { makeResolver } from '@forge/resolver';

export const placeholder = async (payload, context) => {
  // Intentionally unused. See the note above.
  // We log the invocation so that, if someone wires a module to this
  // handler by mistake, it's easy to spot in `forge logs`.
  console.log('SpendPilot placeholder function invoked', {
    payload,
    principalType: context?.principal?.accountType,
  });
  return { ok: true, note: 'SpendPilot placeholder — see src/index.js.' };
};

// Rovo action inputs arrive flat on the first argument. This deliberately
// thin handler keeps the parsing contract reusable by future orchestration.
export const parseSpendRequest = async (payload) => parseRequest(payload);

export const createJiraSpendRequest = async (payload) => createJiraIssue(payload);

export const resolver = makeResolver({
  parseSpendRequest: async ({ payload }) => parseRequest(payload),
  createJiraSpendRequest: async ({ payload }) => createJiraIssue(payload),
});
