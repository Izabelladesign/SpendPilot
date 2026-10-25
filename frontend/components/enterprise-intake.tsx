"use client";

import { FormEvent, useState } from "react";
import { AlertCircle, CheckCircle2, Play, Send } from "lucide-react";
import {
  approveLocalPurchase,
  createLocalPurchasePreview,
  createTask,
  runLocalDemo,
  simulateLocalPayment,
  type Task,
} from "@/lib/spendpilot-api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type EnterpriseIntakeProps = {
  onTaskUpdated: (task: Task) => void;
  selectedTask?: Task | null;
};

export function EnterpriseIntake({ onTaskUpdated, selectedTask = null }: EnterpriseIntakeProps) {
  const [objective, setObjective] = useState(
    "Compare GitHub Copilot and Cursor for a 50-person engineering team",
  );
  const [budget, setBudget] = useState("1.00");
  const [createdTask, setCreatedTask] = useState<Task | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await createTask({
        objective: objective.trim(),
        budget: { amount: budget, currency: "USD" },
        quantity: 1,
        qualityTarget: "Include pricing, security, two HTTPS sources, and unverified information",
        constraints: ["Research task only", "Maximum USD 1.00"],
      });
      setCreatedTask(created);
      onTaskUpdated(created);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to submit the request.");
    } finally {
      setBusy(false);
    }
  }

  async function runLocalDemoResult() {
    if (!activeTask) return;
    setBusy(true);
    setError(null);
    try {
      const completed = await runLocalDemo(activeTask.id);
      const withDecisionPacket = await createLocalPurchasePreview(completed.id);
      setCreatedTask(withDecisionPacket);
      onTaskUpdated(withDecisionPacket);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to verify the local demo result.");
    } finally {
      setBusy(false);
    }
  }

  async function createApprovalPacket() {
    if (!activeTask) return;
    setBusy(true);
    setError(null);
    try {
      const withDecisionPacket = await createLocalPurchasePreview(activeTask.id);
      setCreatedTask(withDecisionPacket);
      onTaskUpdated(withDecisionPacket);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to create the approval packet.");
    } finally {
      setBusy(false);
    }
  }

  async function approveDemoRequest() {
    if (!activeTask) return;
    setBusy(true);
    setError(null);
    try {
      const approved = await approveLocalPurchase(activeTask.id);
      setCreatedTask(approved);
      onTaskUpdated(approved);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to approve the demo request.");
    } finally {
      setBusy(false);
    }
  }

  async function simulatePayment() {
    if (!activeTask) return;
    setBusy(true);
    setError(null);
    try {
      const paid = await simulateLocalPayment(activeTask.id);
      setCreatedTask(paid);
      onTaskUpdated(paid);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to simulate the payment stage.");
    } finally {
      setBusy(false);
    }
  }

  const activeTask = selectedTask ?? createdTask;
  const decisionPacket = activeTask?.output?.decisionPacket as {
    purchaseRequestId?: string;
    approvalId?: string;
    approvalStatus?: string;
    paymentStatus?: string;
  } | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tell the agent what your company needs</CardTitle>
        <CardDescription>
          Describe the outcome your team needs. SpendPilot researches products and services, recommends one, checks spending limits, and routes the purchase for approval.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <form className="flex flex-col gap-4" onSubmit={submitRequest}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="enterprise-objective">What should SpendPilot research?</Label>
            <Textarea
              id="enterprise-objective"
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              required
              minLength={1}
              rows={3}
            />
          </div>
          <div className="flex max-w-xs flex-col gap-2">
            <Label htmlFor="enterprise-budget">Maximum research budget (USD)</Label>
            <Input
              id="enterprise-budget"
              type="number"
              min="0.01"
              step="0.01"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              required
            />
          </div>
          <Button type="submit" disabled={busy} className="w-fit">
            <Send />
            {busy ? "Starting agent run…" : "Start agent run"}
          </Button>
        </form>

        {activeTask ? (
          <div className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">Request submitted</p>
                <p className="text-xs text-muted-foreground">The request is captured. Run the safe local scenario to see the recommendation, guardrails, and verification flow.</p>
              </div>
              <Badge variant={activeTask.status === "COMPLETED" ? "default" : "outline"}>
                {activeTask.status === "COMPLETED" ? <CheckCircle2 /> : <AlertCircle />}
                {activeTask.status.replaceAll("_", " ")}
              </Badge>
            </div>
            {decisionPacket ? (
              <div className="flex flex-col gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
                <div>
                  <p className="font-medium">Decision packet: {decisionPacket.paymentStatus === "SIMULATED_NO_FUNDS" ? "demo complete" : "routed for human review"}</p>
                  <p className="text-xs text-muted-foreground">
                    Purchase request {decisionPacket.purchaseRequestId} · approval {decisionPacket.approvalId} · {decisionPacket.approvalStatus}
                  </p>
                </div>
                {decisionPacket.approvalStatus === "PENDING" ? (
                  <Button type="button" variant="outline" onClick={() => void approveDemoRequest()} disabled={busy} className="w-fit">
                    <CheckCircle2 />
                    Approve for demo (no money)
                  </Button>
                ) : null}
                {decisionPacket.approvalStatus === "APPROVED" && decisionPacket.paymentStatus === "NOT_AUTHORIZED" ? (
                  <Button type="button" variant="outline" onClick={() => void simulatePayment()} disabled={busy} className="w-fit">
                    <Play />
                    Simulate Coinbase/x402 payment (no money)
                  </Button>
                ) : null}
                {decisionPacket.paymentStatus === "SIMULATED_NO_FUNDS" ? (
                  <p className="text-xs text-muted-foreground">Payment stage shown for the demo only. No wallet, chain transaction, provider, or funds were touched.</p>
                ) : null}
              </div>
            ) : activeTask.output?.demoRun ? (
              <Button type="button" variant="outline" onClick={() => void createApprovalPacket()} disabled={busy} className="w-fit">
                <Play />
                Create approval packet
              </Button>
            ) : (
              <Button type="button" variant="outline" onClick={() => void runLocalDemoResult()} disabled={busy || activeTask.status === "COMPLETED"} className="w-fit">
                <Play />
                Run safe local agent simulation
              </Button>
            )}
            <p className="text-xs text-muted-foreground">
              This demo compares GitHub Copilot and Cursor, chooses Copilot explicitly, creates a reviewable decision packet, and stops before any purchase. It does not call a provider or execute payment.
            </p>
          </div>
        ) : null}

        {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
