import { NextRequest } from "next/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const endpoint = new URL(path.join("/"), process.env.API_URL ?? "http://127.0.0.1:8000");
  endpoint.search = request.nextUrl.search;
  const requestHeaders = new Headers();
  const contentType = request.headers.get("content-type");
  const cookie = request.headers.get("cookie");
  if (contentType) requestHeaders.set("content-type", contentType);
  if (cookie) requestHeaders.set("cookie", cookie);
  const response = await fetch(endpoint, {
    method: request.method,
    headers: requestHeaders,
    body: ["GET", "DELETE"].includes(request.method) ? undefined : await request.text(),
    cache: "no-store",
  });
  const headers = new Headers({ "content-type": response.headers.get("content-type") ?? "application/json" });
  for (const name of ["cache-control", "x-accel-buffering"]) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  const setCookie = response.headers.get("set-cookie");
  if (setCookie) headers.set("set-cookie", setCookie);
  return new Response(response.body, { status: response.status, headers });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;

