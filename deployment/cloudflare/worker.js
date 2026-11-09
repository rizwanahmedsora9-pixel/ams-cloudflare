// Set APP_ORIGIN as a Worker secret to the HTTPS PythonAnywhere origin.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const error = (status) => new Response(
      status === 404 ? 'Link unavailable.' : 'Download service unavailable.',
      { status, headers: { 'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } }
    );
    if (!['GET', 'HEAD'].includes(request.method)) return error(405);
    const bill = /^\/b\/[A-Za-z0-9._-]{1,250}(?:\.pdf)?$/.test(url.pathname);
    const ledger = /^\/c\/[A-Za-z0-9_-]{43}$/.test(url.pathname);
    const font = /^\/static\/fonts\/(?:JameelNooriNastaleeq|DejaVuSans|DejaVuSans-Bold)\.ttf$/.test(url.pathname);
    if (!bill && !ledger && !font) return error(404);
    try {
      const origin = new URL(env.APP_ORIGIN);
      if (origin.protocol !== 'https:' || origin.username || origin.password || origin.origin === url.origin) return error(503);
      const upstream = await fetch(new URL(url.pathname, origin.origin), {
        method: request.method, redirect: 'manual',
      });
      if (!upstream.ok) return error(upstream.status === 404 ? 404 : 502);
      const type = upstream.headers.get('Content-Type') || '';
      const pdf = bill && url.pathname.endsWith('.pdf');
      if (!font && !type.toLowerCase().startsWith(pdf ? 'application/pdf' : 'text/html')) return error(502);
      const headers = new Headers({
        'Content-Type': font ? 'font/ttf' : type,
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'X-Robots-Tag': 'noindex, nofollow',
      });
      if (pdf) headers.set('Content-Disposition', 'attachment; filename="bill.pdf"');
      if (ledger) {
        headers.set('Content-Security-Policy', "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'; connect-src 'none'");
      } else if (!font && !pdf) {
        headers.set('Content-Security-Policy', "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'unsafe-inline'; font-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
      }
      // Never forward Location, cookies, app error pages, or other origin headers.
      return new Response(request.method === 'HEAD' ? null : upstream.body, {
        status: 200, headers,
      });
    } catch {
      return error(502);
    }
  },
};
