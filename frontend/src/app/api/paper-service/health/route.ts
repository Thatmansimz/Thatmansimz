import { getPaperServiceHealth } from "@/lib/paper-relay";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  return getPaperServiceHealth();
}
