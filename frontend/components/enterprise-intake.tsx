"use client";

import { FormEvent, useState } from "react";
import { AlertCircle, CheckCircle2, Play, Send } from "lucide-react";
import { createTask, verifyTask, type Task } from "@/lib/spendpilot-api";
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

const demoBrief = {
  summary: "Recommendation: GitHub Copilot is the preferred option for a 50-person engineering team; Cursor remains the comparison alternative.",
  copilotSection: "GitHub Copilot is the selected product in this local demo because it is treated as the stronger fit for a team-wide managed rollout.",
  cursorSection: "Cursor is the researched alternative and remains visible for reviewer comparison.",
  pricingSection: "The local demo compares pricing evidence structurally; it does not claim a live quote or charge a provider.",
  securitySection: "Security details require review against current vendor documentation before a production purchase.",
  sourceUrls: [
    "https://github.com/features/copilot",
    "https://cursor.com/pricing",
  ],
  unverifiedInformation: "Enterprise discounts and organization-specific settings are not verified.",
};

type EnterpriseIntakeProps = {
  onTaskUpdated: (task: Task) => void;
};

export function EnterpriseIntake({ onTaskUpdated }: EnterpriseIntakeProps) {
  const [objective, setObjective] = useState(
    "Compare GitHub Copilot and Cursor for a 50-person engineering team",
  );
  const [budget, setBudget] = useState("1.00");
  const [task, setTask] = useState<Task | null>(null);
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
      setTask(created);
      onTaskUpdated(created);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to submit the request.");
    } finally {
      setBusy(false);
    }
  }

  async function runLocalDemoResult() {
    if (!task) return;
    setBusy(true);
    setError(null);
    try {
      const verified = await verifyTask(task.id, demoBrief);
      setTask(verified);
      onTaskUpdated(verified);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to verify the local demo result.");
    } finally {
      setBusy(false);
    }
  }

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

        {task ? (
          <div className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">Request submitted</p>
                <p className="text-xs text-muted-foreground">The request is captured. Run the safe local scenario to see the recommendation, guardrails, and verification flow.</p>
              </div>
              <Badge variant={task.status === "COMPLETED" ? "default" : "outline"}>
                {task.status === "COMPLETED" ? <CheckCircle2 /> : <AlertCircle />}
                {task.status.replaceAll("_", " ")}
              </Badge>
            </div>
            <Button type="button" variant="outline" onClick={() => void runLocalDemoResult()} disabled={busy || task.status === "COMPLETED"} className="w-fit">
              <Play />
              Run safe local agent simulation
            </Button>
            <p className="text-xs text-muted-foreground">
              This demo compares GitHub Copilot and Cursor, chooses Copilot explicitly, and stops before any purchase. It does not call a provider or execute payment.
            </p>
          </div>
        ) : null}

        {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
