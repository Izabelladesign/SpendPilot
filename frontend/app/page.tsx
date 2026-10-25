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
        SpendPilot is a security layer for autonomous purchasing agents.
        Define what an agent is allowed to buy, how much it can spend, and
        which vendors it can trust. SpendPilot enforces those boundaries
        before money moves.
      </p>

      <Link
        href="/shopping"
        className={cn(buttonVariants({ size: "lg" }), "w-fit")}
      >
        Test the guardrails
      </Link>
    </main>
  );
}