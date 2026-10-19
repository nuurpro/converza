import { NextRequest } from "next/server";

const BACKEND_URL =
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";
const BACKEND_API_KEY = process.env.BACKEND_API_KEY;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function backendUrl(path: string[], request: NextRequest) {
  const upstream = new URL(path.join("/"), BACKEND_URL.endsWith("/") ? BACKEND_URL : `${BACKEND_URL}/`);
  upstream.search = request.nextUrl.search;
  return upstream;
}

async function proxy(request: NextRequest, context: RouteContext) {
  if (!BACKEND_API_KEY) {
    return Response.json(
      { detail: "Backend API key is not configured" },
      { status: 500 },
    );
  }

  const { path } = await context.params;
  if (path[0] === "api" && path[1] === "internal") {
    return Response.json({ detail: "Service-only endpoint" }, { status: 403 });
  }
  const upstreamUrl = backendUrl(path, request);
  const headers = new Headers(request.headers);
  const userAuthorization = headers.get("authorization");
  headers.delete("host");
  headers.delete("authorization");
  if (userAuthorization?.toLowerCase().startsWith("bearer ")) {
    headers.set("x-supabase-access-token", userAuthorization.slice("bearer ".length));
  }
  headers.set("authorization", `Bearer ${BACKEND_API_KEY}`);

  const upstream = await fetch(upstreamUrl, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
    cache: "no-store",
    signal: request.signal,
  });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: upstream.headers,
  });
}

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) { return proxy(request, context); }
export async function PATCH(request: NextRequest, context: RouteContext) { return proxy(request, context); }
export async function DELETE(request: NextRequest, context: RouteContext) { return proxy(request, context); }
