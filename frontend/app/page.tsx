import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "cn";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <p className="text-sm font-medium text-muted-foreground">SpendPilot</p>
      <h1 className="max-w-lg text-4xl font-semibold tracking-tight">
        Shop against a budget you set.
      </h1>
      <p className="max-w-xl text-lg text-muted-foreground">
        Start with a shopping request: say what you need, how much you can
        spend, and which traits matter.
      </p>
      <Link
        href="/shopping"
        className={cn(buttonVariants({ size: "lg" }), "w-fit")}
      >
        Start a shopping request
      </Link>
    </main>
  );
}
