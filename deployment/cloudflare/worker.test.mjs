import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const source = await readFile(new URL('./worker.js', import.meta.url), 'utf8');
const { default: worker } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const env = { APP_ORIGIN: 'https://private.example.com' };
const request = path => new Request(`https://public.workers.dev${path}`);
let calls = 0;
globalThis.fetch = async (url, options) => {
  calls++;
  assert.equal(url.origin, env.APP_ORIGIN);
  assert.equal(options.redirect, 'manual');
  return new Response('bill', { headers: { 'Content-Type': url.pathname.endsWith('.pdf') ? 'application/pdf' : 'text/html', 'Set-Cookie': 'private=value' } });
};
let result = await worker.fetch(request('/b/S.1.BILL.SIGNATURE'), env);
assert.equal(result.status, 200);
assert.equal(result.headers.get('Content-Disposition'), null);
assert.equal(result.headers.get('Set-Cookie'), null);
result = await worker.fetch(request('/b/S.1.BILL.SIGNATURE.pdf'), env);
assert.match(result.headers.get('Content-Disposition'), /^attachment/);
result = await worker.fetch(request('/static/fonts/DejaVuSans.ttf'), env);
assert.equal(result.headers.get('Content-Type'), 'font/ttf');
const before = calls;
for (const path of ['/', '/login', '/static/secret', '/download_invoice/1']) {
  assert.equal((await worker.fetch(request(path), env)).status, 404);
}
assert.equal(calls, before);
globalThis.fetch = async () => new Response(null, { status: 302, headers: { Location: env.APP_ORIGIN } });
result = await worker.fetch(request('/b/token'), env);
assert.equal(result.status, 502);
assert.equal(result.headers.get('Location'), null);
globalThis.fetch = async () => new Response('private error', { status: 500 });
result = await worker.fetch(request('/b/token'), env);
assert.equal(await result.text(), 'Download service unavailable.');
console.log('Worker checks passed: view, download, fonts, path restrictions, redirects, and errors.');
