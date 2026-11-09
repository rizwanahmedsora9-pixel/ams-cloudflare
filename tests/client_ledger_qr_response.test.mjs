// Run with: node --test tests/client_ledger_qr_response.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const template = readFileSync(new URL('../templates/client_ledger.html', import.meta.url), 'utf8');
const controller = template.slice(template.indexOf('(function () {\n    var modalEl'),
    template.indexOf('</script>', template.indexOf('(function () {\n    var modalEl')));
// Check the entire controller's syntax, then exercise its response reader.
new vm.Script(controller);
const readerSource = controller.match(/function readFragment\(response\) \{[\s\S]*?\n    \}/)[0];
const readFragment = vm.runInNewContext(`(${readerSource})`);
function response(status, body, { redirected = false, type = 'text/html' } = {}) {
    return { status, redirected, headers: { get: () => type }, text: async () => body };
}

for (const status of [200, 400, 409, 503]) {
    test(`renders QR fragments and actionable form errors (${status})`, async () => {
        const html = '<div class="cl-qr-dialog text-center">QR or form error</div>';
        assert.equal(await readFragment(response(status, html)), html);
    });
}
test('shows the actual CSRF error from the server', async () => {
    await assert.rejects(async () => readFragment(response(400,
        JSON.stringify({ error: 'Invalid or expired form token. Reload the page and try again.' }),
        { type: 'application/json' })), /Invalid or expired form token/);
});
test('does not insert a redirected login or permission page', async () => {
    await assert.rejects(async () => readFragment(response(200, '<html>login</html>',
        { redirected: true })), /session or permissions changed/);
});
test('does not mistake a full page for a successful generation', async () => {
    await assert.rejects(async () => readFragment(response(200, '<html>login</html>')), /QR request failed/);
});
test('reports a permission failure', async () => {
    await assert.rejects(async () => readFragment(response(403, '<html>Forbidden</html>')), /do not have permission/);
});
test('never displays raw server errors', async () => {
    await assert.rejects(async () => readFragment(response(500, 'Traceback SECRET SQL')),
        error => error.message.includes('(500)') && !error.message.includes('SECRET'));
});
