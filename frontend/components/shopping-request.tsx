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

const TRAITS = [
  { id: "fast-shipping", label: "Fast delivery" },
  { id: "highly-rated", label: "Highly rated" },
  { id: "eco-friendly", label: "Meets sustainability policy" },
  { id: "known-brand", label: "Known vendor" },
] as const;

const STEPS = ["Requested", "Searching", "Optimizing"] as const;

type Phase = "idle" | "loading" | "results" | "error";

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
  const timers = useRef<number[]>([]);

  function clearTimers() {
    for (const id of timers.current) {
      window.clearTimeout(id);
    }
    timers.current = [];
  }

  useEffect(() => clearTimers, []);

  function toggleTrait(id: string) {
    setTraits((current) =>
      current.includes(id)
        ? current.filter((trait) => trait !== id)
        : [...current, id],
    );
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearTimers();

    const text = request.trim();
    const amount = Number(budget);
    const requestMissing = text.length === 0;
    const budgetMissing = !Number.isFinite(amount) || amount <= 0;

    if (requestMissing || budgetMissing) {
      setPhase("error");
      setProducts([]);
      setStage(-1);
      setSubmittedRequest(text);
      setSubmittedBudget(null);
      if (requestMissing && budgetMissing) {
        setError("Enter the purchase need and a budget cap.");
      } else if (requestMissing) {
        setError("Enter what the company needs before submitting.");
      } else {
        setError("Enter a budget cap greater than zero.");
      }
      return;
    }

    setError(null);
    setPhase("loading");
    setProducts([]);
    setSubmittedRequest(text);
    setSubmittedBudget(amount);
    setStage(0);

    timers.current.push(window.setTimeout(() => setStage(1), 500));
    timers.current.push(window.setTimeout(() => setStage(2), 1000));
    timers.current.push(
      window.setTimeout(() => {
        setProducts(mockProducts(text, amount, quality));
        setPhase("results");
      }, 1600),
    );
  }

  const requestInvalid = phase === "error" && request.trim().length === 0;
  const budgetInvalid =
    phase === "error" && (!Number.isFinite(Number(budget)) || Number(budget) <= 0);

  const cap = Number(budget);
  const capReady = Number.isFinite(cap) && cap > 0;

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
            <form className="flex flex-col gap-5" onSubmit={onSubmit} noValidate>
              <div className="flex flex-col gap-2">
                <Label htmlFor="shopping-request">What does the company need?</Label>
                <Textarea
                  id="shopping-request"
                  name="request"
                  rows={4}
                  value={request}
                  placeholder="Noise-cancelling headsets for the support team, black, delivered this week"
                  aria-invalid={requestInvalid || undefined}
                  aria-describedby={error ? "shopping-error" : undefined}
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
                    aria-describedby={error ? "shopping-error" : undefined}
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
                  <Label htmlFor="shopping-quality">Cost versus quality</Label>
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
                    const next = Array.isArray(value) ? value[0] : value;
                    if (typeof next === "number") setQuality(next);
                  }}
                />
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Lower cost</span>
                  <span>Higher quality</span>
                </div>
              </div>

              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">Buying rules</legend>
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
                <p className="text-sm font-medium">Agent progress</p>
                <ol aria-label="Shopping progress" className="grid grid-cols-3 gap-3">
                  {STEPS.map((label, index) => {
                    const reached = stage >= index;
                    const current = phase === "loading" && stage === index;
                    return (
                      <li key={label} aria-current={current ? "step" : undefined}>
                        <div
                          className={cn(
                            "mb-2 h-1.5 rounded-full",
                            reached ? "bg-primary" : "bg-muted",
                          )}
                        />
                        <span
                          className={cn(
                            "text-xs font-medium",
                            reached ? "text-foreground" : "text-muted-foreground",
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
                <p id="shopping-error" role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              ) : null}

              <Button
                type="submit"
                size="lg"
                disabled={phase === "loading"}
                className="w-full sm:w-fit"
              >
                {phase === "loading" ? "Searching…" : "Submit to agent"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {phase === "results" && submittedBudget !== null ? (
          <section aria-live="polite" className="flex flex-col gap-3">
            <div>
              <h2 className="text-lg font-medium">Options inside the cap</h2>
              <p className="text-sm text-muted-foreground">
                For “{submittedRequest}”. Each price is at or under{" "}
                {money.format(submittedBudget)}.
              </p>
            </div>
            {traits.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {traits.map((id) => {
                  const trait = TRAITS.find((item) => item.id === id);
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
                <li key={`${product.merchant}-${product.name}`}>
                  <Card size="sm">
                    <CardHeader>
                      <CardTitle>{product.name}</CardTitle>
                      <CardDescription>Merchant · {product.merchant}</CardDescription>
                    </CardHeader>
                    <CardContent className="flex items-center justify-between gap-3">
                      <p className="text-base font-medium">
                        {money.format(product.price)}
                      </p>
                      <Badge variant="outline">Inside cap</Badge>
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Sample options for review. Live search is not connected, and no
              payment is taken.
            </p>
          </section>
        ) : null}
      </div>

      <aside className="rounded-xl bg-card p-4 text-sm ring-1 ring-foreground/10">
        <p className="font-medium">Controls on this request</p>
        <dl className="mt-4 flex flex-col gap-3">
          <div>
            <dt className="text-muted-foreground">Budget cap</dt>
            <dd className="font-medium">
              {capReady ? money.format(cap) : "Not set"}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Buying policy</dt>
            <dd>{preferenceLabel(quality)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Rules</dt>
            <dd>
              {traits.length > 0
                ? traits
                    .map((id) => TRAITS.find((trait) => trait.id === id)?.label)
                    .filter(Boolean)
                    .join(", ")
                : "None selected"}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Payment</dt>
            <dd>Not taken on this page</dd>
          </div>
        </dl>
      </aside>
    </div>
  );
}
