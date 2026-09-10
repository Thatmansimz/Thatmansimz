import { NextResponse } from "next/server";
export const dynamic = "force-dynamic";
export async function GET() {
  if (process.env.VERCEL && !process.env.TAJARI_API_URL) {
    return NextResponse.json(
      {
        connection_status: "not_connected",
        message:
          "This shared workspace is not connected to the local paper engine. Its orders, positions and P&L are not available here. Historical evidence, the test plan and pricing tools are ready to use.",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
  try {
    const origin = process.env.TAJARI_API_URL || "http://127.0.0.1:8000";
    const response = await fetch(`${origin}/api/workspace`, {
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) throw new Error("Workspace endpoint unavailable");
    const data = await response.json();
    if (typeof data.broker !== "string" || !data.readiness)
      throw new Error("Unsupported backend version");
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      {
        error:
          "Engine status unavailable. The backend may be offline or running the older app. Historical evidence is still available.",
      },
      { status: 503 },
    );
  }
}
