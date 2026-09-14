import { getD47MonitorSnapshot } from "@/data/d47-monitor";

export const dynamic = "force-dynamic";

export async function GET() {
  const snapshot = await getD47MonitorSnapshot();
  if (!snapshot) return Response.json({ error: "D4.7 checkpoint is unavailable" }, { status: 404 });
  return Response.json(snapshot, { headers: { "Cache-Control": "no-store" } });
}
