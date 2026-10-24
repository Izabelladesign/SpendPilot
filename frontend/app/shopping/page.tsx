import type { Metadata } from "next";
import { ShoppingRequest } from "@/components/shopping-request";

export const metadata: Metadata = {
  title: "Shopping request",
  description:
    "Describe a purchase, set a budget and preferences, and review sample products.",
};

export default function ShoppingPage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-10">
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-muted-foreground">Shopping</p>
        <h1 className="text-3xl font-semibold tracking-tight">
          What should we find?
        </h1>
        <p className="max-w-xl text-muted-foreground">
          Write the request, set a total budget, and say whether price or
          quality matters more. This page keeps the request and shows sample
          products after a short wait.
        </p>
      </div>
      <ShoppingRequest />
    </main>
  );
}
