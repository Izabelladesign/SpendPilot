
"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
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
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { mockProducts, type MockProduct } from "@/lib/mock-products";
import { cn } from "cn";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

const TRAITS = [
  { id: "fast-shipping", label: "Fast delivery" },
  { id: "highly-rated", label: "Highly rated" },
  { id: "eco-friendly", label: "Meets sustainability policy" },
  { id: "known-brand", label: "Known vendor" },
] as const;

const STEPS = ["Requested", "Searching", "Optimizing"] as const;

type Phase = "idle" | "loading" | "results" | "error";

type GovernanceReview = {
  status: string;
  reason: string;
  proposed_budget_usd: string | number;
  requires_human_approval: boolean;
  payment_authorized: boolean;
};

type ParsedTask = {
  objective: string;
  budget: {
    amount: number;
    currency: string;
  };
  quantity: number;
  constraints: string[];
};

type ParserResponse = {
  is_ready_for_next_step: boolean;
  parsed_task: ParsedTask | null;
  clarification_questions: string[];
};

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

function preferenceLabel(quality: number): string {
  if (quality <= 33) return "Prefer lower cost";
  if (quality >= 67) return "Prefer higher quality";
  return "Balance cost and quality";
}

export function ShoppingRequest() {
  const [request, setRequest] = useState("");
  const [budget, setBudget] = useState("");
  const [quality, setQuality] = useState(50);
  const [traits, setTraits] = useState<string[]>([]);

  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState(-1);

  const [products, setProducts] = useState<MockProduct[]>([]);
  const [submittedRequest, setSubmittedRequest] = useState("");
  const [submittedBudget, setSubmittedBudget] = useState<number | null>(null);
  const [submittedTraits, setSubmittedTraits] = useState<string[]>([]);
  const [governance, setGovernance] = useState<GovernanceReview | null>(null);

  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const requestVersion = useRef(0);

  function clearTimers() {
    for (const id of timers.current) {
      clearTimeout(id);
    }
    timers.current = [];
  }

  useEffect(() => {
    return () => {
      requestVersion.current += 1;
      clearTimers();
    };
  }, []);

  function toggleTrait(id: string) {
    setTraits((current) =>
      current.includes(id)
        ? current.filter((trait) => trait !== id)
        : [...current, id],
    );
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearTimers();

    const version = ++requestVersion.current;
    const text = request.trim();
    const amount = Number(budget);

    setGovernance(null);
    setProducts([]);
    setError(null);

    const requestMissing = text.length === 0;
    const budgetMissing =
      budget.trim().length === 0 ||
      !Number.isFinite(amount) ||
      amount <= 0 ||
      !Number.isSafeInteger(Math.round(amount * 100)) ||
      Math.abs(amount * 100 - Math.round(amount * 100)) > 1e-7;

    if (requestMissing || budgetMissing) {
      setPhase("error");
      setStage(-1);
      setSubmittedBudget(null);

      if (requestMissing && budgetMissing) {
        setError("Enter the purchase need and a valid budget cap.");
      } else if (requestMissing) {
        setError("Enter what the company needs before submitting.");
      } else {
        setError("Enter a positive budget cap with at most two decimal places.");
      }

      return;
    }

    const selectedRules = TRAITS
      .filter((trait) => traits.includes(trait.id))
      .map((trait) => trait.label);

    setPhase("loading");
    setStage(0);
    setSubmittedRequest(text);
    setSubmittedBudget(amount);
    setSubmittedTraits([...traits]);

    timers.current.push(
      setTimeout(() => {
        if (requestVersion.current === version) setStage(1);
      }, 500),
    );

    try {
      const rawTask = [
        text,
        `Total budget: ${amount.toFixed(2)} USD.`,
        `Quality preference: ${preferenceLabel(quality)}.`,
        selectedRules.length
          ? `Buying constraints: ${selectedRules.join(", ")}.`
          : "Buying constraints: No additional buying rules specified.",
      ].join("\n");

      const parserResponse = await fetch(`${API_URL}/api/tasks/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_task: rawTask }),
      });

      if (!parserResponse.ok) {
        throw new Error(`AI parser request failed (${parserResponse.status}).`);
      }

      const result = (await parserResponse.json()) as ParserResponse;

      if (requestVersion.current !== version) return;

      if (!result.is_ready_for_next_step) {
        clearTimers();
        setStage(-1);
        setPhase("error");
        setError(
          result.clarification_questions?.join(" ") ||
            "The AI needs more information before continuing.",
        );
        return;
      }

      const parsed = result.parsed_task;

      if (
        !parsed ||
        typeof parsed.objective !== "string" ||
        !parsed.objective.trim() ||
        !parsed.budget ||
        parsed.budget.currency !== "USD" ||
        typeof parsed.budget.amount !== "number" ||
        !Number.isFinite(parsed.budget.amount) ||
        typeof parsed.quantity !== "number" ||
        !Number.isFinite(parsed.quantity) ||
        parsed.quantity <= 0
      ) {
        throw new Error("AI parser returned incomplete purchasing information.");
      }

      // The form's budget is the user's requested cap.
      // Do not silently replace it with an AI-generated amount.
      if (Math.abs(parsed.budget.amount - amount) > 0.001) {
        throw new Error(
          "The AI interpreted a different budget. Please clarify your request.",
        );
      }

      setStage(2);

      const governanceResponse = await fetch(
        `${API_URL}/api/governance/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            objective: parsed.objective,
            budget_usd: amount.toFixed(2),
            quantity: parsed.quantity,
            constraints: Array.isArray(parsed.constraints)
              ? parsed.constraints
              : [],
          }),
        },
      );

      if (!governanceResponse.ok) {
        throw new Error(
          `Governance review failed (${governanceResponse.status}).`,
        );
      }

      const review =
        (await governanceResponse.json()) as GovernanceReview;

      if (requestVersion.current !== version) return;

      if (
        review.status !== "REVIEW_REQUIRED" ||
        review.payment_authorized !== false ||
        review.requires_human_approval !== true
      ) {
        throw new Error("Unexpected governance review response.");
      }

      const reviewedBudget = Number(review.proposed_budget_usd);

      if (
        !Number.isFinite(reviewedBudget) ||
        Math.abs(reviewedBudget - amount) > 0.001
      ) {
        throw new Error("Governance returned a mismatched budget.");
      }

      clearTimers();
      setGovernance(review);

      // These are sample products only, not live inventory.
      setProducts(mockProducts(text, amount, quality));
      setPhase("results");
    } catch (err) {
      if (requestVersion.current !== version) return;

      clearTimers();
      setStage(-1);
      setPhase("error");
      setGovernance(null);
      setProducts([]);
      setError(
        err instanceof Error
          ? err.message
          : "Could not complete the request review.",
      );
    }
  }

  const requestInvalid =
    phase === "error" && request.trim().length === 0;

  const cap = Number(budget);
  const capReady =
    budget.trim().length > 0 &&
    Number.isFinite(cap) &&
    cap > 0;

  const budgetInvalid =
    phase === "error" &&
    (!capReady ||
      Math.abs(cap * 100 - Math.round(cap * 100)) > 1e-7);

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Request for the agent</CardTitle>
            <CardDescription>
              The company states the need and the rules. The agent may only
              return options at or under the cap.
            </CardDescription>
          </CardHeader>

          <CardContent>
            <form
              className="flex flex-col gap-5"
              onSubmit={onSubmit}
              noValidate
            >
              <div className="flex flex-col gap-2">
                <Label htmlFor="shopping-request">
                  What does the company need?
                </Label>

                <Textarea
                  id="shopping-request"
                  name="request"
                  rows={4}
                  value={request}
                  placeholder="Purchase 5 noise-cancelling headsets for the support team, delivered by October 30, 2026"
                  aria-invalid={requestInvalid || undefined}
                  aria-describedby={
                    error ? "shopping-error" : undefined
                  }
                  onChange={(event) => setRequest(event.target.value)}
                  className="min-h-28"
                />
              </div>

              <div className="flex flex-col gap-2">
                <Label htmlFor="shopping-budget">Budget cap</Label>

                <div className="relative max-w-xs">
                  <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-sm text-muted-foreground">
                    $
                  </span>

                  <Input
                    id="shopping-budget"
                    name="budget"
                    type="number"
                    inputMode="decimal"
                    min={0}
                    step="0.01"
                    value={budget}
                    placeholder="1500"
                    aria-invalid={budgetInvalid || undefined}
                    aria-describedby={
                      error ? "shopping-error" : undefined
                    }
                    onChange={(event) => setBudget(event.target.value)}
                    className="pl-6"
                  />
                </div>

                <p className="text-xs text-muted-foreground">
                  Hard limit for this request. Over-cap options are not shown.
                </p>
              </div>

              <div className="flex flex-col gap-3">
                <div className="flex items-baseline justify-between gap-3">
                  <Label htmlFor="shopping-quality">
                    Cost versus quality
                  </Label>

                  <span className="text-sm text-muted-foreground">
                    {preferenceLabel(quality)}
                  </span>
                </div>

                <Slider
                  id="shopping-quality"
                  min={0}
                  max={100}
                  value={[quality]}
                  aria-label="Cost versus quality"
                  onValueChange={(value) => {
                    const next = Array.isArray(value)
                      ? value[0]
                      : value;

                    if (typeof next === "number") {
                      setQuality(next);
                    }
                  }}
                />

                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Lower cost</span>
                  <span>Higher quality</span>
                </div>
              </div>

              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">
                  Buying rules
                </legend>

                <div className="flex flex-wrap gap-2">
                  {TRAITS.map((trait) => {
                    const selected = traits.includes(trait.id);

                    return (
                      <Button
                        key={trait.id}
                        type="button"
                        size="sm"
                        variant={selected ? "default" : "outline"}
                        aria-pressed={selected}
                        onClick={() => toggleTrait(trait.id)}
                      >
                        {trait.label}
                      </Button>
                    );
                  })}
                </div>
              </fieldset>

              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">
                  Agent progress
                </p>

                <ol
                  aria-label="Shopping progress"
                  className="grid grid-cols-3 gap-3"
                >
                  {STEPS.map((label, index) => {
                    const reached = stage >= index;
                    const current =
                      phase === "loading" && stage === index;

                    return (
                      <li
                        key={label}
                        aria-current={
                          current ? "step" : undefined
                        }
                      >
                        <div
                          className={cn(
                            "mb-2 h-1.5 rounded-full",
                            reached ? "bg-primary" : "bg-muted",
                          )}
                        />

                        <span
                          className={cn(
                            "text-xs font-medium",
                            reached
                              ? "text-foreground"
                              : "text-muted-foreground",
                          )}
                        >
                          {label}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              </div>

              {error ? (
                <p
                  id="shopping-error"
                  role="alert"
                  className="text-sm text-destructive"
                >
                  {error}
                </p>
              ) : null}

              <Button
                type="submit"
                size="lg"
                disabled={phase === "loading"}
                className="w-full sm:w-fit"
              >
                {phase === "loading"
                  ? "Reviewing request…"
                  : "Submit to agent"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {phase === "results" && governance ? (
          <section aria-live="polite">
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <CardTitle>Spending Governance</CardTitle>
                  <Badge variant="secondary">
                    Review Required
                  </Badge>
                </div>

                <CardDescription>
                  The request passed initial validation but still
                  requires human authorization.
                </CardDescription>
              </CardHeader>

              <CardContent className="flex flex-col gap-4">
                <dl className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <dt className="text-sm text-muted-foreground">
                      Proposed budget
                    </dt>
                    <dd className="text-lg font-semibold">
                      {money.format(
                        Number(governance.proposed_budget_usd),
                      )}
                    </dd>
                  </div>

                  <div>
                    <dt className="text-sm text-muted-foreground">
                      Approval status
                    </dt>
                    <dd className="font-medium">
                      Human review required
                    </dd>
                  </div>

                  <div>
                    <dt className="text-sm text-muted-foreground">
                      Payment authorized
                    </dt>
                    <dd className="font-medium">No</dd>
                  </div>

                  <div>
                    <dt className="text-sm text-muted-foreground">
                      Funds reserved
                    </dt>
                    <dd className="font-medium">No</dd>
                  </div>
                </dl>

                <p className="text-sm text-muted-foreground">
                  {governance.reason}
                </p>

                <p className="text-xs text-muted-foreground">
                  This is a preliminary governance review.
                  No approval request has been submitted to a human
                  reviewer, and no payment has been initiated.
                </p>
              </CardContent>
            </Card>
          </section>
        ) : null}

        {phase === "results" && submittedBudget !== null ? (
          <section
            aria-live="polite"
            className="flex flex-col gap-3"
          >
            <div>
              <h2 className="text-lg font-medium">
                Options inside the cap
              </h2>

              <p className="text-sm text-muted-foreground">
                For “{submittedRequest}”. Each displayed sample
                price is at or under{" "}
                {money.format(submittedBudget)}.
              </p>
            </div>

            {submittedTraits.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {submittedTraits.map((id) => {
                  const trait = TRAITS.find(
                    (item) => item.id === id,
                  );

                  return trait ? (
                    <Badge key={id} variant="secondary">
                      {trait.label}
                    </Badge>
                  ) : null;
                })}
              </div>
            ) : null}

            <ul className="grid gap-3">
              {products.map((product) => (
                <li
                  key={`${product.merchant}-${product.name}`}
                >
                  <Card size="sm">
                    <CardHeader>
                      <CardTitle>{product.name}</CardTitle>
                      <CardDescription>
                        Merchant · {product.merchant}
                      </CardDescription>
                    </CardHeader>

                    <CardContent className="flex items-center justify-between gap-3">
                      <p className="text-base font-medium">
                        {money.format(product.price)}
                      </p>

                      <Badge variant="outline">
                        Inside cap
                      </Badge>
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>

            <p className="text-xs text-muted-foreground">
              Sample options for review. Live search is not
              connected, prices are per item, and no payment
              is taken. Multiple units may exceed the total
              request budget.
            </p>
          </section>
        ) : null}
      </div>

      <aside className="rounded-xl bg-card p-4 text-sm ring-1 ring-foreground/10">
        <p className="font-medium">
          Controls on this request
        </p>

        <dl className="mt-4 flex flex-col gap-3">
          <div>
            <dt className="text-muted-foreground">
              Budget cap
            </dt>
            <dd className="font-medium">
              {capReady ? money.format(cap) : "Not set"}
            </dd>
          </div>

          <div>
            <dt className="text-muted-foreground">
              Buying policy
            </dt>
            <dd>{preferenceLabel(quality)}</dd>
          </div>

          <div>
            <dt className="text-muted-foreground">
              Rules
            </dt>
            <dd>
              {traits.length > 0
                ? traits
                    .map(
                      (id) =>
                        TRAITS.find(
                          (trait) => trait.id === id,
                        )?.label,
                    )
                    .filter(Boolean)
                    .join(", ")
                : "None selected"}
            </dd>
          </div>

          <div>
            <dt className="text-muted-foreground">
              Governance
            </dt>
            <dd>
              {governance
                ? "Human review required"
                : "Not yet reviewed"}
            </dd>
          </div>

          <div>
            <dt className="text-muted-foreground">
              Payment
            </dt>
            <dd>Not taken on this page</dd>
          </div>
        </dl>
      </aside>
    </div>
  );
}
