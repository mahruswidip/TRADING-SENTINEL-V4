import { CONTRACT_V1 } from "../../../../domain/contracts-v1.ts";

export function GET() {
  return Response.json(CONTRACT_V1, {
    headers: { "Cache-Control": "public, max-age=86400, immutable" },
  });
}
