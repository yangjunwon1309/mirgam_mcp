import { NextRequest } from "next/server";

const METHODS = ["GET", "POST", "DELETE"] as const;

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const endpoint = new URL(path.join("/"), process.env.API_URL ?? "http://127.0.0.1:8000");
  const response = await fetch(endpoint, {
    method: request.method,
    headers: request.headers.get("content-type") ? { "content-type": request.headers.get("content-type")! } : undefined,
    body: ["GET", "DELETE"].includes(request.method) ? undefined : await request.text(),
  });
  return new Response(response.body, { status: response.status, headers: { "content-type": response.headers.get("content-type") ?? "application/json" } });
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;

