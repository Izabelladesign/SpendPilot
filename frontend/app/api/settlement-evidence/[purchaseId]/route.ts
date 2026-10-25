import { NextRequest, NextResponse } from "next/server";


export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ purchaseId: string }> },
) {
  if (process.env.SPENDPILOT_ENABLE_EVIDENCE_PROXY !== "true") {
    return NextResponse.json({ error: "Evidence proxy disabled" }, { status: 403 });
  }
  const token = process.env.SPENDPILOT_PAYMENT_TOKEN;
  if (!token) return NextResponse.json({ error: "Server token not configured" }, { status: 503 });
  const { purchaseId } = await context.params;
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(purchaseId)) {
    return NextResponse.json({ error: "Invalid purchase ID" }, { status: 400 });
  }
  const base = process.env.SPENDPILOT_BACKEND_URL || "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${base}/api/payments/purchase/${encodeURIComponent(purchaseId)}/evidence`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const payload = await response.json().catch(() => ({ error: "Backend returned an invalid response" }));
    if (!response.ok) return NextResponse.json({ error: payload.detail || payload.error || "Evidence unavailable" }, { status: response.status });
    return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Backend unavailable" }, { status: 502 });
  }
}
