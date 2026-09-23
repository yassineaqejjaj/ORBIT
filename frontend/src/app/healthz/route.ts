/** Liveness probe for the web container (does not call the backend). */
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok", service: "orbit-web" }, { headers: { "Cache-Control": "no-store" } });
}
