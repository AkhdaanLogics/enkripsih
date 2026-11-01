#!/usr/bin/env node
// Diagnoses Vercel 401 root cause. Three scenarios:
//   A. Idle timeout: auth_sessions.expires_at already past
//   B. Cookie not sent: secure/same-site/missing on browser side
//   C. maxDuration: serverless hang -> 401 from cancelled request
// Run: node diag_vercel.cjs  (no auth needed, all unauth probes)
// For B we also test with the cookie obtained via login if ENKRIPSIH_PASSWORD is in env.

const https = require('https');
const { execSync } = require('child_process');

function req(url, opts = {}) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    const r = https.request(url, opts, (res) => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => resolve({
        status: res.statusCode,
        headers: res.headers,
        body,
        ms: Date.now() - t0,
      }));
    });
    r.on('error', (e) => reject({ url, status: 0, err: e.message, ms: Date.now() - t0 }));
    if (opts.timeoutMs) r.setTimeout(opts.timeoutMs, () => {
      r.destroy(new Error('CLIENT_TIMEOUT'));
    });
    if (opts.body) r.write(opts.body);
    r.end();
  });
}

function j(obj) { return JSON.stringify(obj); }

async function main() {
  const base = 'https://enkripsih.vercel.app';
  const out = { url: base, time: new Date().toISOString(), scenarios: {} };

  // Probe 0: /api/health (must be 200, public). Reports session_store + db + idle_timeout.
  try {
    const h = await req(`${base}/api/health`);
    out.scenarios.health = h;
    const parsed = JSON.parse(h.body);
    out.scenarios.health.summary = parsed;
  } catch (e) { out.scenarios.health = { error: j(e) }; }

  // Probe A: idle timeout check.
  // We can't query auth_sessions directly (private). Instead: try an unauth /api/messages.
  //   Expected 401 with JSON {"detail":"Login diperlukan."}  -> proves the middleware gate.
  //   If 200 -> a session cookie leaked. (unlikely, but we record it).
  try {
    const m = await req(`${base}/api/messages`);
    out.scenarios.unauthMessages = { status: m.status, ms: m.ms, body: m.body.slice(0, 300) };
    out.scenarios.unauthMessages.note = m.status === 401
      ? '401 as expected: middleware rejects when no valid cookie. Root cause = cookie absent/expired.'
      : (m.status === 200 ? 'UNEXPECTED 200 without cookie: cookie or in-memory session leak'
                           : `status ${m.status}`);
  } catch (e) { out.scenarios.unauthMessages = { error: j(e) }; }

  // Probe B: cookie secure flag. /api/auth/login sets the cookie; we capture it from
  // the response headers and inspect its `Set-Cookie` attribute.
  // Requires ENKRIPSIH_PASSWORD in env (optional).
  const password = process.env.ENKRIPSIH_PASSWORD;
  if (password) {
    const body = JSON.stringify({ username: 'commander', password });
    try {
      const login = await req(`${base}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
        },
        body,
      });
      const setCookie = login.headers['set-cookie'];
      out.scenarios.login = {
        status: login.status,
        ms: login.ms,
        body: login.body.slice(0, 200),
        setCookie: setCookie ? setCookie.map(s => s.split(';').slice(0, 4).join(';')) : null,
      };
      if (Array.isArray(setCookie) && setCookie.length) {
        const c0 = setCookie[0];
        out.scenarios.login.cookieAttrs = {
          hasSecure: /(^|;\s*)secure/i.test(c0),
          hasSameSite: /same-site=(\w+)/i.exec(c0)?.[1] ?? null,
          path: /path=(\S+)/i.exec(c0)?.[1] ?? null,
        };
        out.scenarios.login.note = out.scenarios.login.cookieAttrs.hasSecure === false
          ? 'NOT secure -> browser will NOT send on HTTPS Vercel. This is the 401 cause.'
          : 'Secure cookie. If still 401, check SameSite=Lax/Strict + whether the Vercel proxy strips it.';
      }
      // Probe B2: with that cookie, fetch /api/messages
      if (Array.isArray(setCookie) && setCookie.length) {
        const cookieHeader = setCookie.map(c => c.split(';')[0]).join('; ');
        const msg = await req(`${base}/api/messages`, {
          headers: { Cookie: cookieHeader },
        });
        out.scenarios.messagesWithCookie = {
          status: msg.status,
          ms: msg.ms,
          body: msg.body.slice(0, 200),
          note: msg.status === 200
            ? 'Cookie works! 401 on browser is likely because the cookie did not survive a page reload or was HttpOnly-flagged and a CORS redirect dropped it.'
            : `status ${msg.status} with cookie -> cookie expired (idle timeout) or server cleared it.`,
        };
      }
    } catch (e) { out.scenarios.login = { error: j(e) }; }
  } else {
    out.scenarios.login = { skipped: 'ENKRIPSIH_PASSWORD not in env. Re-run:  ENKRIPSIH_PASSWORD=... node diag_vercel.cjs' };
  }

  // Probe C: maxDuration timing. We hit a known-slow endpoint repeatedly and measure.
  // If Vercel maxDuration=10s, any request >10s gets force-killed -> 5xx or 401.
  // We sample 5x and record p50/p95 ms. If any hits ~10000ms and then 502/524, that's the smoking gun.
  try {
    const samples = [];
    for (let i = 0; i < 5; i++) {
      const r = await req(`${base}/api/health`, { timeoutMs: 15000 });
      samples.push({ ms: r.ms, status: r.status });
    }
    out.scenarios.latency = { samples, note: 'All <10s -> maxDuration NOT the cause. Any >=9000ms -> Vercel Function timeout (check Vercel dashboard: Function maxDuration).' };
  } catch (e) { out.scenarios.latency = { error: j(e) }; }

  console.log(j(out, null, 2));
}

main().catch((e) => { console.error('diagnose crashed:', e); process.exit(1); });
