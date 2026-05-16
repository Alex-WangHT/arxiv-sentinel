import { Flash } from './models';

export interface AuthEnv {
  FRONTEND_PASSWORD?: string;
  SESSION_SECRET?: string;
}

const SESSION_COOKIE = 'ps_session';
const SESSION_TTL_SECONDS = 8 * 60 * 60;

interface SessionPayload {
  sub: 'admin';
  exp: number;
}

function textBytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function asArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary)
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '');
}

function base64UrlToBytes(value: string): Uint8Array {
  const normalized = value.replaceAll('-', '+').replaceAll('_', '/');
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), '=');
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return bytes;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'raw',
    asArrayBuffer(textBytes(secret)),
    {
      name: 'HMAC',
      hash: 'SHA-256',
    },
    false,
    ['sign', 'verify'],
  );
}

function sessionSecret(env: AuthEnv): string {
  return env.SESSION_SECRET?.trim() || env.FRONTEND_PASSWORD?.trim() || 'paper-sniffer-local-session';
}

async function signPayload(payload: string, env: AuthEnv): Promise<string> {
  const signature = await crypto.subtle.sign(
    'HMAC',
    await hmacKey(sessionSecret(env)),
    asArrayBuffer(textBytes(payload)),
  );

  return bytesToBase64Url(new Uint8Array(signature));
}

async function verifyPayload(payload: string, signature: string, env: AuthEnv): Promise<boolean> {
  return crypto.subtle.verify(
    'HMAC',
    await hmacKey(sessionSecret(env)),
    asArrayBuffer(base64UrlToBytes(signature)),
    asArrayBuffer(textBytes(payload)),
  );
}

function getCookie(request: Request, name: string): string | undefined {
  const cookie = request.headers.get('cookie') || '';
  const pairs = cookie.split(';').map(part => part.trim()).filter(Boolean);

  for (const pair of pairs) {
    const separator = pair.indexOf('=');
    if (separator === -1) {
      continue;
    }

    if (pair.slice(0, separator) === name) {
      return decodeURIComponent(pair.slice(separator + 1));
    }
  }

  return undefined;
}

export function frontendAuthEnabled(env: AuthEnv): boolean {
  return Boolean(env.FRONTEND_PASSWORD?.trim());
}

export async function createSessionCookie(request: Request, env: AuthEnv): Promise<string> {
  const payload: SessionPayload = {
    sub: 'admin',
    exp: Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS,
  };
  const encodedPayload = bytesToBase64Url(textBytes(JSON.stringify(payload)));
  const signature = await signPayload(encodedPayload, env);
  const secure = new URL(request.url).protocol === 'https:' ? '; Secure' : '';

  return [
    `${SESSION_COOKIE}=${encodeURIComponent(`${encodedPayload}.${signature}`)}`,
    'Path=/',
    'HttpOnly',
    'SameSite=Lax',
    `Max-Age=${SESSION_TTL_SECONDS}`,
    secure.slice(2),
  ].filter(Boolean).join('; ');
}

export function clearSessionCookie(): string {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
}

export async function isAuthenticated(request: Request, env: AuthEnv): Promise<boolean> {
  if (!frontendAuthEnabled(env)) {
    return true;
  }

  const cookie = getCookie(request, SESSION_COOKIE);
  if (!cookie) {
    return false;
  }

  const [encodedPayload, signature] = cookie.split('.');
  if (!encodedPayload || !signature) {
    return false;
  }

  const verified = await verifyPayload(encodedPayload, signature, env);
  if (!verified) {
    return false;
  }

  try {
    const payload = JSON.parse(new TextDecoder().decode(base64UrlToBytes(encodedPayload))) as SessionPayload;
    return payload.sub === 'admin' && payload.exp > Math.floor(Date.now() / 1000);
  } catch {
    return false;
  }
}

export async function loginResponse(request: Request, env: AuthEnv): Promise<Response> {
  if (!frontendAuthEnabled(env)) {
    return Response.redirect(new URL('/', request.url), 303);
  }

  const form = await request.formData();
  const password = String(form.get('password') || '');
  if (password !== env.FRONTEND_PASSWORD) {
    const { renderLoginPage } = await import('./views');
    return htmlResponse(renderLoginPage({ kind: 'error', message: 'Password is incorrect.' }), 401);
  }

  return redirectWithCookie('/', request, await createSessionCookie(request, env));
}

export function requireLoginRedirect(request: Request): Response {
  const url = new URL('/login', request.url);
  url.searchParams.set('next', new URL(request.url).pathname);
  return Response.redirect(url, 303);
}

export function redirectWithCookie(path: string, request: Request, cookie: string): Response {
  return new Response(null, {
    status: 303,
    headers: {
      location: new URL(path, request.url).toString(),
      'set-cookie': cookie,
    },
  });
}

export function htmlResponse(html: string, status = 200, flash?: Flash): Response {
  const headers = new Headers({
    'content-type': 'text/html; charset=utf-8',
    'cache-control': 'no-store',
  });

  if (flash) {
    headers.set('x-paper-sniffer-flash', flash.message);
  }

  return new Response(html, {
    status,
    headers,
  });
}
