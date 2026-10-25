"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, AlertCircle, ArrowUpRight, CheckCircle2, Clock3, RefreshCw, ShieldCheck, Wallet } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AgentControlCenter } from "@/components/agent-control-center";
import { EnterpriseIntake } from "@/components/enterprise-intake";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  getBudget,
  getTaskExecution,
  listPayments,
  listTasks,
  type AgentEvent,
  type Budget,
  type ExecutionSummary,
  type Payment,
  type Task,
} from "@/lib/spendpilot-api";

function amount(value: string | number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatMoney(value: string | number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount(value));
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusVariant(status: Task["status"]): "default" | "secondary" | "outline" | "destructive" {
  if (status === "COMPLETED") return "default";
  if (status === "FAILED") return "destructive";
  if (status === "AWAITING_APPROVAL") return "outline";
  return "secondary";
}

function statusLabel(status: string): string {
  return status.replaceAll("_", " ").toLowerCase().replace(/(^| )\S/g, (letter) => letter.toUpperCase());
}

function executionStatusVariant(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (["SETTLED", "SIMULATED", "APPROVED", "VERIFIED", "COMPLETED"].includes(status)) return "default";
  if (["FAILED", "BLOCK", "REJECTED", "FAILED_VERIFICATION"].includes(status)) return "destructive";
  if (["REVIEW_REQUIRED", "PENDING", "VERIFYING"].includes(status)) return "outline";
  return "secondary";
}

function verificationStatus(events: AgentEvent[]): string {
  const event = [...events].reverse().find((candidate) => {
    const candidateStatus = candidate.metadata.verificationStatus;
    return candidate.type === "OUTPUT_VERIFIED" || candidate.type === "VERIFICATION_FAILED" || typeof candidateStatus === "string";
  });

  if (!event) return "NOT_REPORTED";
  if (event.type === "OUTPUT_VERIFIED") return "VERIFIED";
  if (event.type === "VERIFICATION_FAILED") return "FAILED_VERIFICATION";
  return String(event.metadata.verificationStatus).toUpperCase();
}

export function EnterpriseDashboard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [execution, setExecution] = useState<ExecutionSummary | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [{ items: nextTasks }, { items: nextPayments }] = await Promise.all([
        listTasks(),
        listPayments(),
      ]);
      const nextBudgets = await Promise.all(
        [...new Set(nextTasks.map((task) => task.budgetId).filter(Boolean))].map((id) =>
          getBudget(id as string),
        ),
      );
      const nextTaskId = selectedTaskId ?? nextTasks[0]?.id ?? null;
      const nextExecution = nextTaskId ? await getTaskExecution(nextTaskId) : null;
      setTasks(nextTasks);
      setPayments(nextPayments);
      setBudgets(nextBudgets);
      setExecution(nextExecution);
      setEvents(nextExecution?.events ?? []);
      if (!selectedTaskId && nextTaskId) setSelectedTaskId(nextTaskId);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to load the dashboard.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // Refresh synchronizes this client component with the external API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    // The selected task is intentionally included so its timeline refreshes when changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTaskId]);

  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;
  const selectedPayments = execution?.payments ?? [];
  const selectedPurchase = execution?.purchaseRequests.at(-1) ?? null;
  const selectedApproval = execution?.approvals.at(-1) ?? null;
  const selectedVerification = verificationStatus(events);
  const totals = useMemo(
    () =>
      budgets.reduce(
        (summary, budget) => ({
          total: summary.total + amount(budget.total),
          spent: summary.spent + amount(budget.spent),
          reserved: summary.reserved + amount(budget.reserved),
          available: summary.available + amount(budget.available),
          currency: budget.currency,
        }),
        { total: 0, spent: 0, reserved: 0, available: 0, currency: "USD" },
      ),
    [budgets],
  );
  const providers = [...new Set(tasks.map((task) => task.selectedProviderId).filter(Boolean))];
  const completed = tasks.filter((task) => task.status === "COMPLETED").length;
  const active = tasks.filter((task) => !["COMPLETED", "FAILED"].includes(task.status)).length;

  function handleTaskUpdated(task: Task) {
    setSelectedTaskId(task.id);
    void refresh();
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-4 py-10 sm:px-6">
      <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium text-primary">Enterprise control room</p>
          <h1 className="text-4xl font-semibold tracking-tight">Agent activity, at a glance.</h1>
          <p className="max-w-2xl text-muted-foreground">
            See what SpendPilot is working on, how funds are allocated, and where human review is needed.
          </p>
        </div>
        <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={loading ? "animate-spin" : undefined} />
          Refresh
        </Button>
      </div>

      <EnterpriseIntake onTaskUpdated={handleTaskUpdated} />

      <AgentControlCenter
        task={selectedTask}
        events={events}
        verificationStatus={selectedVerification}
        payments={selectedPayments}
      />

      {error ? (
        <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm" role="alert">
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
          <div>
            <p className="font-medium">Dashboard data is unavailable</p>
            <p className="mt-1 text-muted-foreground">Start the local API at http://localhost:8000, then refresh.</p>
            <p className="mt-1 text-xs text-muted-foreground">{error}</p>
          </div>
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Platform summary">
        {[
          { label: "Available", value: formatMoney(totals.available, totals.currency), icon: Wallet, detail: "Across tracked budgets" },
          { label: "Reserved", value: formatMoney(totals.reserved, totals.currency), icon: Clock3, detail: "Held for active requests" },
          { label: "Active tasks", value: String(active), icon: Activity, detail: `${tasks.length} total tasks` },
          { label: "Completed", value: String(completed), icon: CheckCircle2, detail: "Verified outcomes" },
        ].map((stat) => (
          <Card key={stat.label}>
            <CardContent className="flex items-start justify-between gap-4 pt-6">
              <div>
                <p className="text-sm text-muted-foreground">{stat.label}</p>
                <p className="mt-2 text-2xl font-semibold tracking-tight">{stat.value}</p>
                <p className="mt-1 text-xs text-muted-foreground">{stat.detail}</p>
              </div>
              <stat.icon className="size-5 text-primary" />
            </CardContent>
          </Card>
        ))}
      </section>

      <section className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,.65fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Tasks</CardTitle>
            <CardDescription>Active and completed work flowing through the shared agent API.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {tasks.length === 0 ? (
              <div className="px-6 pb-6 text-sm text-muted-foreground">No tasks have been created yet.</div>
            ) : (
              <div className="divide-y">
                {tasks.map((task) => (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => setSelectedTaskId(task.id)}
                    className={`flex w-full items-start justify-between gap-4 px-6 py-4 text-left transition-colors hover:bg-muted/50 ${selectedTaskId === task.id ? "bg-muted/50" : ""}`}
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium">{task.objective}</p>
                      <p className="mt-1 text-xs text-muted-foreground">Updated {formatDate(task.updatedAt)}</p>
                    </div>
                    <Badge variant={statusVariant(task.status)}>{statusLabel(task.status)}</Badge>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Execution timeline</CardTitle>
            <CardDescription>{selectedTask ? selectedTask.objective : "Select a task to inspect its events."}</CardDescription>
          </CardHeader>
          <CardContent>
            {events.length === 0 ? (
              <p className="text-sm text-muted-foreground">No agent events recorded yet.</p>
            ) : (
              <ol className="flex flex-col gap-5">
                {events.map((event) => (
                  <li key={event.id} className="relative flex gap-3">
                    <span className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                      {event.type === "POLICY_DECISION" ? <ShieldCheck className="size-3.5" /> : <Activity className="size-3.5" />}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{statusLabel(event.type)}</p>
                      <p className="mt-0.5 text-sm text-muted-foreground">{event.message}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{formatDate(event.createdAt)}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="grid items-start gap-6 lg:grid-cols-3" aria-label="Selected execution state">
        <Card>
          <CardHeader>
            <CardTitle>Governance</CardTitle>
            <CardDescription>Decision recorded for the selected task.</CardDescription>
          </CardHeader>
          <CardContent>
            <Badge variant={executionStatusVariant(selectedPurchase?.decision ?? "NOT_REQUESTED")}>
              {statusLabel(selectedPurchase?.decision ?? "NOT_REQUESTED")}
            </Badge>
            <p className="mt-3 text-sm text-muted-foreground">
              {selectedApproval?.status === "PENDING"
                ? "Human approval is still required."
                : selectedPurchase?.decisionReason ?? "No purchase request has been recorded."}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Payment state</CardTitle>
            <CardDescription>Payment is reported independently from task success.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {selectedPayments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No payment recorded.</p>
            ) : selectedPayments.map((payment) => (
              <div key={payment.id} className="flex items-center justify-between gap-3">
                <span className="text-sm">{formatMoney(payment.amount, payment.currency)}</span>
                <Badge variant={executionStatusVariant(payment.status)}>{statusLabel(payment.status)}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Task verification</CardTitle>
            <CardDescription>Payment settlement never marks a task verified by itself.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm">Task status</span>
              <Badge variant={executionStatusVariant(selectedTask?.status ?? "NOT_REPORTED")}>
                {statusLabel(selectedTask?.status ?? "NOT_REPORTED")}
              </Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm">Verification</span>
              <Badge variant={executionStatusVariant(selectedVerification)}>{statusLabel(selectedVerification)}</Badge>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Budgets and providers</CardTitle>
            <CardDescription>Financial context and provider selection from the shared records.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><p className="text-muted-foreground">Total budget</p><p className="mt-1 font-medium">{formatMoney(totals.total, totals.currency)}</p></div>
              <div><p className="text-muted-foreground">Spent</p><p className="mt-1 font-medium">{formatMoney(totals.spent, totals.currency)}</p></div>
            </div>
            <div className="border-t pt-4">
              <p className="text-sm text-muted-foreground">Selected providers</p>
              {providers.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-2">{providers.map((provider) => <Badge key={provider} variant="outline">{provider}</Badge>)}</div>
              ) : <p className="mt-1 text-sm">No provider selected yet.</p>}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Payment history</CardTitle>
            <CardDescription>Read-only settlement records. No payment is initiated here.</CardDescription>
          </CardHeader>
          <CardContent>
            {payments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No payments recorded.</p>
            ) : (
              <div className="flex flex-col gap-3">
                {payments.map((payment) => (
                  <div key={payment.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                    <div><p className="text-sm font-medium">{payment.providerId}</p><p className="text-xs text-muted-foreground">{statusLabel(payment.status)}</p></div>
                    <p className="text-sm font-medium">{formatMoney(payment.amount, payment.currency)}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      {selectedTask?.output ? (
        <Card>
          <CardHeader>
            <CardTitle>Completed output</CardTitle>
            <CardDescription>Verified output attached to the selected task.</CardDescription>
          </CardHeader>
          <CardContent><pre className="overflow-x-auto rounded-lg bg-muted p-4 text-xs">{JSON.stringify(selectedTask.output, null, 2)}</pre></CardContent>
        </Card>
      ) : null}

      <p className="flex items-center gap-2 text-xs text-muted-foreground"><ArrowUpRight className="size-3.5" /> This control room reads the local SpendPilot API. Swagger is available for developers, but the company demo starts with the intake form above.</p>
    </main>
  );
}
