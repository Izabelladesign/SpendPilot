"use client";

import { FormEvent, useState } from "react";

type Evidence = {
  purchase_request_id: string;
  payment_id: string;
  status: string;
  shared_payment_status: string;
  governed_payment_status: string;
  settlement_verified: boolean;
  transaction_hash: string | null;
  verified_at: string | null;
  network: string | null;
  asset: string | null;
  recipient: string | null;
  amount_usd: string;
  evidence_type: string;
};

export default function SettlementEvidencePage() {
  const [purchaseId, setPurchaseId] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadEvidence(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setEvidence(null);
    try {
      const response = await fetch(`/api/settlement-evidence/${encodeURIComponent(purchaseId.trim())}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Unable to load evidence");
      setEvidence(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold">Spend Passport · Settlement Evidence</h1>
        <p className="text-sm text-gray-500">Read-only verification. A simulated payment is never represented as on-chain settlement.</p>
      </header>
      <form onSubmit={loadEvidence} className="flex flex-wrap gap-3">
        <input aria-label="Purchase request ID" required value={purchaseId} onChange={e => setPurchaseId(e.target.value)} placeholder="Purchase request ID" className="min-w-64 flex-1 rounded-lg border p-3 text-black" />
        <button disabled={loading} className="rounded-lg bg-black px-5 py-3 text-white disabled:opacity-50">{loading ? "Loading…" : "View evidence"}</button>
      </form>
      {error && <p role="alert" className="rounded-lg border border-red-400 p-4 text-red-600">{error}</p>}
      {evidence && (
        <section className="space-y-4 rounded-xl border p-6">
          <h2 className="text-xl font-semibold">Purchase {evidence.purchase_request_id}</h2>
          <p className={evidence.settlement_verified ? "font-semibold text-green-600" : "font-semibold text-amber-600"}>
            {evidence.settlement_verified ? "Verified on-chain settlement" : "Not verified on-chain — pending, incomplete, or simulated"}
          </p>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {([
              ["Status", evidence.status],
              ["Amount (USD)", evidence.amount_usd],
              ["Shared ledger", evidence.shared_payment_status],
              ["Governed ledger", evidence.governed_payment_status],
              ["Network", evidence.network],
              ["Asset", evidence.asset],
              ["Recipient", evidence.recipient],
              ["Verified at", evidence.settlement_verified ? evidence.verified_at : null],
            ] as [string, string | null][]).map(([label, value]) => (
              <div key={label} className="min-w-0"><dt className="text-sm text-gray-500">{label}</dt><dd className="break-all font-medium">{value || "Not available"}</dd></div>
            ))}
          </dl>
          {evidence.settlement_verified && evidence.transaction_hash && (
            <div><p className="text-sm text-gray-500">Verified transaction hash</p><code className="break-all">{evidence.transaction_hash}</code></div>
          )}
        </section>
      )}
    </main>
  );
}
