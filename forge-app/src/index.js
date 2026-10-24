// Entry point for the SpendPilot Rovo agent.
//
// Rovo invokes the agent directly from the rovo:agent module. The parser
// action below is deliberately read-only: it only returns validated planning
// data and never talks to Jira or a commerce system.

import { parseSpendRequest as parseRequest } from './spend-intake.js';

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
