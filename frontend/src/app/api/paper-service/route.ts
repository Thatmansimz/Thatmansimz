import { getPaperServiceStatus, postPaperServiceStatus } from "../../../lib/paper-relay";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  return getPaperServiceStatus();
}

export async function POST(request: Request) {
  return postPaperServiceStatus(request);
}
