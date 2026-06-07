import { NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * GET /api/status
 * Proxy to the Python backend's /api/status endpoint.
 * Returns system health, market status, and AI configuration.
 */
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/status`, {
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
    });

    if (!res.ok) {
      return NextResponse.json(
        { error: "Backend unavailable", backend_status: res.status },
        { status: 503 }
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
        trading_enabled: false,
        market_open: false,
        scheduler_running: false,
      },
      { status: 503 }
    );
  }
}
