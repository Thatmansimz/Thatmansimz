import { NextResponse } from "next/server";

const BACKEND_URL = process.env.TAJARI_API_URL || "http://127.0.0.1:8000";

/**
 * GET /api/status
 * Proxy to the Python backend's /api/status endpoint.
 * Returns system health, market status, and AI configuration.
 */
export async function GET() {
  if (process.env.VERCEL && !process.env.TAJARI_API_URL) {
    return NextResponse.json(
      { connection_status: "not_connected" },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
  try {
    const res = await fetch(`${BACKEND_URL}/api/status`, {
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
      headers: { "Content-Type": "application/json" },
    });

    if (!res.ok) {
      return NextResponse.json(
        { error: "Backend unavailable", backend_status: res.status },
        { status: 503 },
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      {
        error: "Cannot reach backend",
        detail: message,
      },
      { status: 503 },
    );
  }
}
