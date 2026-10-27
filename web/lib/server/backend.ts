export class GatewayError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function assertSameOrigin(request: Request) {
  const origin = request.headers.get('origin');
  if ((origin && origin !== new URL(request.url).origin) || request.headers.get('sec-fetch-site') === 'cross-site') {
    throw new GatewayError(403, 'Cross-origin request denied');
  }
}

const id = '[A-Za-z0-9_-]+';
const routes: [string, RegExp][] = [
  ['GET', new RegExp(`^api/onboarding/state/${id}$`)],
  ['POST', /^api\/onboarding\/(passport|complete|stub-payment)$/],
  ['POST', /^api\/agent\/(milo|sleyz)\/message$/],
  ['POST', /^api\/squad\/message$/],
  ['GET', /^api\/squad\/stream$/],
  ['GET', new RegExp(`^api/dashboard/${id}/stats$`)],
  ['GET', new RegExp(`^api/drafts(/${id})?$`)],
  ['POST', new RegExp(`^api/hitl/${id}/(approve|reject|edit)$`)],
  ['POST', new RegExp(`^api/drafts/${id}/(resolve|deliver|refresh|retry-generation|retry-learning)$`)],
  ['POST', /^api\/simulate\/inbound-dm$/],
  ['GET', /^api\/sleyz\/connections$/],
  ['GET', new RegExp(`^api/memory/${id}/(identity|products|knowledge|search|jobs)$`)],
  ['GET', new RegExp(`^api/memory/${id}/identity/export/[A-Za-z0-9_-]+\\.(md|json)$`)],
  ['PUT', new RegExp(`^api/memory/${id}/identity$`)],
  ['POST', new RegExp(`^api/memory/${id}/(products|knowledge)$`)],
  ['PUT|DELETE', new RegExp(`^api/memory/${id}/(products|knowledge)/${id}$`)],
  ['DELETE', new RegExp(`^api/memory/${id}/sources/${id}$`)],
  ['POST', new RegExp(`^api/memory/${id}/jobs/${id}/retry$`)],
  ['GET', new RegExp(`^api/milo/${id}/(campaigns|jobs|settings|brand|proof-sources|objections)(/${id})?$`)],
  ['PUT', new RegExp(`^api/milo/${id}/(settings|brand)$`)],
  ['POST', new RegExp(`^api/milo/${id}/campaigns$`)],
  ['POST', new RegExp(`^api/milo/${id}/campaigns/${id}/script/(approve|reject|edit)$`)],
  ['POST', new RegExp(`^api/milo/${id}/jobs/${id}/(retry|reconcile)$`)],
  ['GET', new RegExp(`^api/vea/${id}/(presets|assets|variants)(/${id})?$`)],
  ['POST', new RegExp(`^api/vea/${id}/variants(/${id}/(swap|retry))?$`)],
];

export function assertAllowedPath(path: string[], method: string) {
  if (!path.length || path.some(part => !/^[A-Za-z0-9_.-]+$/.test(part) || part === '.' || part === '..') ||
      !routes.some(([methods, pattern]) => methods.split('|').includes(method) && pattern.test(path.join('/')))) {
    throw new GatewayError(403, 'Endpoint not available');
  }
}

export interface VerifiedUser { id: string; email?: string; }
export async function authenticate(request: Request, allowStreamToken = false) {
  assertSameOrigin(request);
  const query = new URL(request.url).searchParams;
  const authorization = request.headers.get('authorization');
  const bearer = authorization?.match(/^Bearer ([^\s,]+)$/i)?.[1];
  const queryTokens = query.getAll('access_token');
  if (queryTokens.length && (!allowStreamToken || queryTokens.length !== 1 || (bearer && bearer !== queryTokens[0]))) {
    throw new GatewayError(401, 'Invalid session credentials');
  }
  const token = bearer || (allowStreamToken ? queryTokens[0] : null);
  if (!token || /[\s,]/.test(token) || (authorization && !bearer)) throw new GatewayError(401, 'Sign in required');
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) throw new GatewayError(503, 'Authentication is not configured');
  const response = await fetch(new URL('/auth/v1/user', url), {
    headers: new Headers({authorization: `Bearer ${token}`, apikey: key}),
    redirect: 'manual', cache: 'no-store', signal: request.signal,
  });
  if (!response.ok) throw new GatewayError(401, 'Invalid user session');
  const user = await response.json();
  if (!user?.id || !/^[A-Za-z0-9_-]+$/.test(user.id)) throw new GatewayError(401, 'Invalid user session');
  return {token, user: {id: user.id, ...(user.email ? {email: user.email} : {})} as VerifiedUser};
}

export async function backendFetch(path: string, token: string, request: Request, body?: string) {
  const key = process.env.BACKEND_API_KEY;
  if (!key) throw new GatewayError(503, 'Backend is not configured');
  const base = new URL(process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://127.0.0.1:8000');
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.pathname !== '/' || base.search || base.hash) {
    throw new GatewayError(503, 'Invalid backend configuration');
  }
  const target = new URL('/' + path, base);
  if (target.origin !== base.origin) throw new GatewayError(403, 'Invalid backend target');
  const headers = new Headers({authorization: `Bearer ${key}`, 'x-supabase-access-token': token});
  for (const name of ['accept', 'content-type', 'idempotency-key', 'last-event-id']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const response = await fetch(target, {
    method: request.method, headers, body, cache: 'no-store', redirect: 'manual', signal: request.signal,
  });
  if (response.status >= 300 && response.status < 400) {
    await response.body?.cancel();
    throw new GatewayError(502, 'Backend redirect refused');
  }
  return response;
}

export async function readPassport(userId: string, token: string, request: Request) {
  const upstream = await backendFetch(`api/onboarding/state/${userId}`, token, new Request(request.url, {headers: request.headers, signal: request.signal}));
  if (!upstream.ok) throw new GatewayError(upstream.status, 'Could not restore workspace');
  const {passport} = await upstream.json();
  if (passport && (passport.owner_user_id !== userId || !passport.org_id)) throw new GatewayError(502, 'Invalid workspace ownership');
  return passport ?? null;
}

export function gatewayFailure(error: unknown) {
  return Response.json({detail: error instanceof GatewayError ? error.message : 'Gateway unavailable'}, {
    status: error instanceof GatewayError ? error.status : 502, headers: {'Cache-Control': 'no-store'},
  });
}
