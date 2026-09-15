import { NextResponse } from "next/server";
import { isStale, parsePaperStatus } from "../../../lib/paper-status";

export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store" };

export async function GET() {
  const source = process.env.TAJARI_PAPER_SERVICE_URL;
  const token = process.env.TAJARI_PAPER_LOCAL_TOKEN;
  if (!source || !token) {
    return NextResponse.json({ connection_status: "not_connected", message: "The continuous paper worker is not reporting to this view. Its current account and feed status are unavailable here." }, { headers });
  }
  try {
    const response = await fetch(source, { cache: "no-store", signal: AbortSignal.timeout(4000), headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error("Worker unavailable");
    const status = parsePaperStatus(await response.json());
    return NextResponse.json({ status, stale: isStale(status) }, { headers });
  } catch {
    return NextResponse.json({ connection_status: "unavailable", message: "The paper worker could not be reached. No current account or connection status can be inferred." }, { headers, status: 503 });
  }
}
