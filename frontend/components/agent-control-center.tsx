"use client";

import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleDollarSign,
  FileSearch,
  Search,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AgentEvent, LocalDemoRun, Payment, Task } from "@/lib/spendpilot-api";

type AgentControlCenterProps = {
  task: Task | null;
  events: AgentEvent[];
  verificationStatus: string;
  payments: Payment[];
};

const sampleLicenseInventory = [
  {
    id: "figma",
    product: "Figma Professional",
    seats: "3 of 18 seats",
    detail: "No activity in 30+ days",
    action: "Review seats",
  },
  {
    id: "notion",
    product: "Notion Plus",
    seats: "2 of 12 seats",
    detail: "Assigned but never activated",
    action: "Review seats",
  },
  {
    id: "slack",
    product: "Slack guest access",
    seats: "7 guests",
    detail: "Access review due this week",
    action: "Review access",
  },
] as const;

const workflowStages = [
  { label: "Understand", detail: "Capture the business need", icon: FileSearch },
  { label: "Research", detail: "Find products and services", icon: Search },
  { label: "Recommend", detail: "Rank by fit and cost", icon: Sparkles },
  { label: "Govern", detail: "Check limits and approval", icon: ShieldCheck },
  { label: "Execute", detail: "Buy only when allowed", icon: ShoppingCart },
] as const;

export function AgentControlCenter({
  task,
  events,
  verificationStatus,
  payments,
}: AgentControlCenterProps) {
  const [reviewedLicenses, setReviewedLicenses] = useState<string[]>([]);
  const [purchasePreviewed, setPurchasePreviewed] = useState(false);
  const demoRun = task?.output?.demoRun as LocalDemoRun | undefined;
  const decisionPacket = task?.output?.decisionPacket as {
    purchaseRequestId?: string;
    approvalId?: string;
    approvalStatus?: string;
    paymentStatus?: string;
    fundsMoved?: boolean;
  } | undefined;
  const demoScenario = Boolean(demoRun);
  const selectedProduct = demoRun?.recommendation.selectedProduct ?? "NOT READY";
  const alternativeProduct = demoRun?.recommendation.alternativeProduct ?? "—";
  const licenseInventory = demoRun?.licenseHealth.items ?? sampleLicenseInventory;
  const completed = task?.status === "COMPLETED" && verificationStatus === "VERIFIED";
  const failed = task?.status === "FAILED" || verificationStatus === "FAILED_VERIFICATION";
  const researchStarted = Boolean(task);
  const purchaseState = purchasePreviewed
    ? "SIMULATED — NO CHARGE"
    : decisionPacket?.paymentStatus === "SIMULATED_NO_FUNDS"
      ? "SIMULATED — NO CHARGE"
    : payments.length > 0
      ? payments.at(-1)?.status ?? "RECORDED"
      : "NOT EXECUTED";
  const activeEvent = [...events].reverse()[0];

  function stageState(index: number): "complete" | "active" | "pending" {
    if (failed) return index === 0 ? "complete" : index === 1 ? "active" : "pending";
    if (!researchStarted) return "pending";
    if (completed && decisionPacket?.paymentStatus === "SIMULATED_NO_FUNDS") return "complete";
    if (completed) return index < 4 ? "complete" : "active";
    return index === 0 ? "complete" : index === 1 ? "active" : "pending";
  }

  function toggleLicense(id: string) {
    setReviewedLicenses((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  return (
    <section className="flex flex-col gap-6" aria-label="Agent control center">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-primary">Agent control center</p>
          <Badge variant="secondary"><Sparkles /> Local demo mode</Badge>
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">From request to responsible action.</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          SpendPilot researches the market, explains its recommendation, checks the company&apos;s spending authority,
          routes approval, and watches for waste after purchase.
        </p>
      </div>

      <Card className="overflow-visible">
        <CardHeader>
          <CardTitle>Agent run</CardTitle>
          <CardDescription>
            {activeEvent?.message ?? "Create a request above to start the agent run."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="grid gap-3 md:grid-cols-5" aria-label="Agent workflow stages">
            {workflowStages.map((stage, index) => {
              const state = stageState(index);
              const Icon = stage.icon;
              return (
                <li key={stage.label} className="relative">
                  {index < workflowStages.length - 1 ? (
                    <ArrowRight className="absolute -right-3 top-5 z-10 hidden size-4 text-muted-foreground md:block" />
                  ) : null}
                  <div className={`flex h-full flex-col gap-3 rounded-lg border p-3 ${
                    state === "complete"
                      ? "border-primary/30 bg-primary/5"
                      : state === "active"
                        ? "border-amber-500/40 bg-amber-500/5"
                        : "bg-muted/20"
                  }`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex size-8 items-center justify-center rounded-full bg-background ring-1 ring-foreground/10">
                        {state === "complete" ? <Check className="size-4 text-primary" /> : <Icon className="size-4" />}
                      </span>
                      <Badge variant={state === "complete" ? "default" : state === "active" ? "outline" : "secondary"}>
                        {state === "complete" ? "Done" : state === "active" ? "Working" : "Queued"}
                      </Badge>
                    </div>
                    <div>
                      <p className="font-medium">{stage.label}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{stage.detail}</p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,.8fr)]">
        <Card className="border-primary/30 bg-primary/[0.025]">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle>What the agent chose</CardTitle>
                <CardDescription>Recommendation is separate from purchase authorization.</CardDescription>
              </div>
              <Badge variant={demoScenario ? "default" : "outline"}>
                {demoScenario ? "Recommendation ready" : "Waiting for matching research"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {demoScenario ? (
              <>
                <div className="flex flex-col gap-1">
                  <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">Preferred product</p>
                  <p className="text-3xl font-semibold tracking-tight">{selectedProduct}</p>
                  <p className="text-sm text-muted-foreground">Chosen from {demoRun?.candidates.length ?? 0} researched options for the 50-person engineering team scenario.</p>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border bg-background p-3">
                    <p className="text-xs text-muted-foreground">Alternative reviewed</p>
                    <p className="mt-1 font-medium">{alternativeProduct}</p>
                  </div>
                  <div className="rounded-lg border bg-background p-3">
                    <p className="text-xs text-muted-foreground">Budget cap</p>
                    <p className="mt-1 font-medium">{demoRun?.governance.budgetCap}</p>
                  </div>
                  <div className="rounded-lg border bg-background p-3">
                    <p className="text-xs text-muted-foreground">Research cost</p>
                    <p className="mt-1 font-medium">{demoRun?.recommendation.estimatedResearchCost}</p>
                  </div>
                </div>

                <div className="rounded-lg border bg-background p-4">
                  <p className="flex items-center gap-2 text-sm font-medium"><Sparkles className="size-4 text-primary" /> Why {selectedProduct} won this demo</p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {demoRun?.recommendation.rationale}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge variant="outline"><ShieldCheck /> Guardrails checked</Badge>
                  <Badge variant="outline"><CircleDollarSign /> No funds moved</Badge>
                  <span className="text-muted-foreground">Next gate: human approval before any purchase.</span>
                </div>
              </>
            ) : (
              <div className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
                Use the default Copilot vs Cursor scenario above, then run the local demo result. The selected product and the alternative will appear here explicitly.
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle>Purchase control</CardTitle>
                <CardDescription>The agent can prepare a purchase, but policy stays in charge.</CardDescription>
              </div>
              <ShoppingCart className="size-5 text-primary" />
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">Recommendation</span>
              <Badge variant={demoScenario ? "default" : "secondary"}>{selectedProduct}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">Policy gate</span>
              <Badge variant={completed ? "default" : "outline"}>{demoRun?.governance.status ?? "REVIEW"}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">Payment</span>
              <Badge variant="secondary">{decisionPacket?.paymentStatus ?? purchaseState}</Badge>
            </div>
            {decisionPacket ? (
              <div className="rounded-lg border bg-background p-3 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">Decision packet</p>
                <p className="mt-1">Purchase request: {decisionPacket.purchaseRequestId}</p>
                <p>Approval: {decisionPacket.approvalId} ({decisionPacket.approvalStatus})</p>
                <p className="mt-1">Funds moved: {decisionPacket.fundsMoved ? "Yes" : "No — local simulation"}</p>
              </div>
            ) : null}
            {demoScenario && completed && !purchasePreviewed && !decisionPacket ? (
              <Button type="button" variant="outline" onClick={() => setPurchasePreviewed(true)}>
                <ShoppingCart />
                Preview governed purchase
              </Button>
            ) : null}
            {purchasePreviewed ? (
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-xs text-muted-foreground">
              Purchase preview passed the demo guardrails. No card, wallet, provider, or funds were touched.
              </div>
            ) : null}
            <div className="rounded-lg bg-muted/40 p-3 text-xs text-muted-foreground">
              Local demo stops before a real purchase. Production execution would require an approved vendor, explicit approval, and a configured payment connector.
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>License health</CardTitle>
              <CardDescription>SpendPilot can find unused access before the next renewal.</CardDescription>
            </div>
            <Badge variant="secondary"><Users /> Sample inventory</Badge>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Seats monitored</p><p className="mt-1 text-xl font-semibold">37</p></div>
            <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">At-risk access</p><p className="mt-1 text-xl font-semibold">{licenseInventory.length + 2}</p></div>
            <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Renewal action</p><p className="mt-1 text-xl font-semibold">Review</p></div>
          </div>
          <div className="divide-y rounded-lg border">
            {licenseInventory.map((license) => {
              const reviewed = reviewedLicenses.includes(license.id);
              return (
                <div key={license.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    {reviewed ? <CheckCircle2 className="mt-0.5 size-4 text-primary" /> : <AlertTriangle className="mt-0.5 size-4 text-amber-600" />}
                    <div>
                      <p className="text-sm font-medium">{license.product}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{license.seats} · {license.detail}</p>
                    </div>
                  </div>
                  <Button type="button" size="sm" variant={reviewed ? "secondary" : "outline"} onClick={() => toggleLicense(license.id)}>
                    {reviewed ? "Marked for review" : license.action}
                  </Button>
                </div>
              );
            })}
          </div>
          <p className="flex items-center gap-2 text-xs text-muted-foreground"><Activity className="size-3.5" /> License rows are sample telemetry for the local demo; no vendor account was accessed.</p>
        </CardContent>
      </Card>
    </section>
  );
}
