const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type TaskStatus =
  | "REQUESTED"
  | "RESEARCHING"
  | "PLANNING"
  | "AWAITING_APPROVAL"
  | "EXECUTING"
  | "VERIFYING"
  | "COMPLETED"
  | "FAILED";

export type Money = {
  amount: string;
  currency: string;
};

export type Task = {
  id: string;
  userId: string;
  budgetId: string | null;
  objective: string;
  budget: Money;
  quantity: string | null;
  qualityTarget: string | null;
  constraints: string[];
  status: TaskStatus;
  selectedProviderId: string | null;
  output: Record<string, unknown> | null;
  failureReason: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AgentEvent = {
  id: string;
  taskId: string;
  type: string;
  message: string;
  metadata: Record<string, unknown>;
  createdAt: string;
};

export type Budget = {
  id: string;
  name: string;
  currency: string;
  total: string;
  spent: string;
  reserved: string;
  available: string;
  createdAt: string;
  updatedAt: string;
};

export type Payment = {
  id: string;
  taskId: string;
  purchaseRequestId: string;
  providerId: string;
  amount: string;
  currency: string;
  status: string;
  transactionReference: string | null;
  createdAt: string;
  updatedAt: string;
};

export type PurchaseRequestStatus = {
  id: string;
  taskId: string;
  providerId: string;
  amount: string;
  currency: string;
  decision: string;
  decisionReason: string;
  approvalId: string | null;
  createdAt: string;
  updatedAt: string;
};

export type Approval = {
  id: string;
  taskId: string;
  purchaseRequestId: string;
  amount: string;
  currency: string;
  vendor: string;
  status: string;
  reason: string;
  decidedBy: string | null;
  decidedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type ExecutionSummary = {
  taskId: string;
  taskStatus: string;
  purchaseRequests: PurchaseRequestStatus[];
  payments: Payment[];
  approvals: Approval[];
  events: AgentEvent[];
};

export type LocalDemoCandidate = {
  name: string;
  rank: number;
  selected: boolean;
  comparison: string;
  evidence: string[];
};

export type LocalDemoRun = {
  mode: string;
  scenario: string;
  candidates: LocalDemoCandidate[];
  recommendation: {
    selectedProduct: string;
    alternativeProduct: string;
    rationale: string;
    estimatedResearchCost: string;
    evidenceStatus: string;
  };
  governance: {
    status: string;
    budgetCap: string;
    approvalRequired: boolean;
    paymentAuthorized: boolean;
    reason: string;
  };
  purchase: {
    state: string;
    executed: boolean;
    fundsMoved: boolean;
    providerCalled: boolean;
    nextStep: string;
  };
  licenseHealth: {
    mode: string;
    vendorAccountsAccessed: boolean;
    items: Array<{
      id: string;
      product: string;
      seats: string;
      detail: string;
      action: string;
    }>;
  };
};

export type CreateTaskInput = {
  objective: string;
  budget: Money;
  quantity: number;
  qualityTarget: string;
  constraints: string[];
};

export type VerifyResearchBriefInput = {
  summary: string;
  copilotSection: string;
  cursorSection: string;
  pricingSection: string;
  securitySection: string;
  sourceUrls: string[];
  unverifiedInformation: string;
};

type ListResponse<T> = {
  items: T[];
  nextCursor?: string | null;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message || `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function createTask(input: CreateTaskInput): Promise<Task> {
  return request<Task>("/tasks", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function verifyTask(
  taskId: string,
  input: VerifyResearchBriefInput,
): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/verify`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function runLocalDemo(taskId: string): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/demo-run`, {
    method: "POST",
  });
}

export function listTasks(): Promise<ListResponse<Task>> {
  return request<ListResponse<Task>>("/tasks?limit=100");
}

export function getTaskEvents(taskId: string): Promise<ListResponse<AgentEvent>> {
  return request<ListResponse<AgentEvent>>(`/tasks/${taskId}/events`);
}

export function getTaskExecution(taskId: string): Promise<ExecutionSummary> {
  return request<ExecutionSummary>(`/tasks/${taskId}/execution`);
}

export function getBudget(budgetId: string): Promise<Budget> {
  return request<Budget>(`/budgets/${budgetId}`);
}

export function listPayments(): Promise<ListResponse<Payment>> {
  return request<ListResponse<Payment>>("/payments?limit=100");
}
