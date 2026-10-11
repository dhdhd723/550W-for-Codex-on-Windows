/** Build fidelity and offline asset checks; no third-party Node dependencies. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');
const source = read('web/source/550C-source.html');
const originalCss = source.match(/<style>([\s\S]*?)<\/style>/)[1];
assert.equal(read('web/animation.css'), '/* GENERATED: original 550C stylesheet, unchanged. */\n' + originalCss);
const page = read('web/index.html');
assert.equal((page.match(/<path class="(?:white|red)"/g) || []).length, 6);
assert(!/<text\b/.test(page), '550W wordmark must be drawn geometry, not plain SVG text');
assert(page.includes('aria-label="550W"'));
assert(page.includes('550W SYSTEM BOOT'));
assert(page.includes('550W // UAV-BS-07'));
assert(page.includes("media-src 'self'"), 'Local audio needs an explicit CSP media source');
const pathGeometry = text => [...text.matchAll(/<path\s+class="(?:white|red)"[^>]*\sd="([^"]+)"/g)].map(m => m[1]);
assert.deepEqual(pathGeometry(page).slice(0, 4), pathGeometry(source).slice(0, 4), 'Original 550 geometry must remain byte-identical');
assert(page.includes('SYSTEM IS REWRITTEN'));
assert(page.includes('550W CORE TERMINAL'));
assert(!/codex/i.test(page), 'Animation model labels must all use 550W');
assert(!/https?:\/\//.test(page.replace(/http:\/\/www\.w3\.org\/2000\/svg/g, '')));
const script = read('web/animation.js');
assert(!/codex/i.test(script), 'Logs, certificates and displayed code must all use 550W');
for (const label of ['[550W]', '550W-ROOT', '550W-CTRL', '550W-QUANTUM-0', 'CA_550W']) assert(script.includes(label));
assert(!/require\(|fetch\(|ctx\.slots|__DSH_BOOT/.test(script));
for (const phase of ['Boot', 'Auth', 'Link', 'Tunnel', 'Isolate', 'Rewrite', 'Verify', 'Arm', 'Finish']) {
  assert(script.includes(`async function phase${phase}()`));
  assert(script.includes(`await phase${phase}()`));
}
assert(script.includes('const NODE_COUNT = 47;'));
for (const name of ['setReady', 'finish', 'setWaiting', 'showError']) assert(read('web/launcher.js').includes(name));
console.log('PASS: unchanged source CSS; six filled SVG paths; original nine phases and 47 nodes; offline resources; native lifecycle API.');
