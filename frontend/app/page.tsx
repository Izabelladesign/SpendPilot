import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "cn";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <p className="text-sm font-medium text-muted-foreground">
        SpendPilot · AI Agent Security
      </p>

      <h1 className="max-w-2xl text-4xl font-semibold tracking-tight">
        Let AI agents spend. Keep them inside the rules.
      </h1>

      <p className="max-w-2xl text-lg text-muted-foreground">
        SpendPilot is an agentic purchasing control room for companies.
        It researches products and services, recommends the best fit,
        enforces spending limits before money moves, and helps teams find
        unused access after the purchase.
      </p>

      <div className="flex flex-wrap gap-3">
        <Link
          href="/enterprise"
          className={cn(buttonVariants({ size: "lg" }), "w-fit")}
        >
          Open the company control room
        </Link>
        <Link
          href="/shopping"
          className={cn(buttonVariants({ size: "lg", variant: "outline" }), "w-fit")}
        >
          Test the guardrails
        </Link>
      </div>
    </main>
  );
}
