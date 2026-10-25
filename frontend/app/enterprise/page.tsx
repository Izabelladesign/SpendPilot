import type { Metadata } from "next";
import { EnterpriseDashboard } from "@/components/enterprise-dashboard";

export const metadata: Metadata = {
  title: "Enterprise dashboard",
  description: "Monitor SpendPilot agent tasks, budgets, events, and payments.",
};

export default function EnterprisePage() {
  return <EnterpriseDashboard />;
}
