import {authenticate, gatewayFailure, readPassport} from '@/lib/server/backend';

export async function GET(request: Request) {
  try {
    const {token, user} = await authenticate(request);
    const passport = await readPassport(user.id, token, request);
    return Response.json({user, passport}, {headers: {'Cache-Control': 'no-store'}});
  } catch (error) { return gatewayFailure(error); }
}
