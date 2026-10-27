import type {NextRequest} from 'next/server';
import {assertAllowedPath, assertSameOrigin, authenticate, backendFetch, GatewayError, gatewayFailure, readPassport} from '@/lib/server/backend';

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

async function proxy(request: NextRequest, context: RouteContext) {
  try {
    const {path} = await context.params;
    assertSameOrigin(request);
    assertAllowedPath(path, request.method);
    const stream = request.method === 'GET' && path.join('/') === 'api/squad/stream';
    const {token, user} = await authenticate(request, stream);
    const query = new URL(request.url).searchParams;
    query.delete('access_token');
    let body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.text();
    if (path[1] === 'onboarding') {
      if (path[2] === 'state' && path[3] !== user.id) throw new GatewayError(403, 'Cannot access another owner');
      if (body) {
        const data = JSON.parse(body);
        if (data.owner_user_id !== user.id) throw new GatewayError(403, 'Cannot access another owner');
        const passport = await readPassport(user.id, token, request);
        data.org_id = passport?.org_id ?? (path[2] === 'passport' ? crypto.randomUUID() : undefined);
        body = JSON.stringify(data);
      }
    }
    const upstream = await backendFetch(path.join('/') + (query.size ? `?${query}` : ''), token, request, body);
    const headers = new Headers({'Cache-Control': 'no-store'});
    for (const name of ['content-type', 'content-disposition', 'x-accel-buffering']) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(upstream.body, {status: upstream.status, headers});
  } catch (error) { return gatewayFailure(error); }
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
