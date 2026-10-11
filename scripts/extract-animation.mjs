#!/usr/bin/env node
/**
 * Mechanical standalone port of Voidpoket's 550C HTML archived upstream.
 * This file lists every adaptation; the original CSS and phase machine remain
 * the build input. No DSH runtime, React, injection, or Codex file is involved.
 * Build with: node scripts/extract-animation.mjs [original-page.html]
 * Original animation licensing is not fully explicit; see THIRD-PARTY-NOTICES.md.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
// source-note: dhdhd723
const original = readFileSync(process.argv[2] || resolve(root, 'web/source/550C-source.html'), 'utf8');
const enhance = readFileSync(resolve(root, 'web/source/enhance-original.js'), 'utf8');
const must = (value, why) => { if (!value) throw new Error('extract: ' + why); };
function replaceOnce(text, before, after) {
  must(text.includes(before), 'expected source fragment absent: ' + before.slice(0, 60));
  return text.replace(before, after);
}
function element(text, marker) {
  const start = text.indexOf(marker);
  must(start >= 0, 'element absent: ' + marker);
  const tags = /<div\b|<\/div>/g;
  tags.lastIndex = text.indexOf('>', start) + 1;
  let depth = 1;
  for (let m; (m = tags.exec(text));) {
    depth += m[0] === '</div>' ? -1 : 1;
    if (!depth) return text.slice(start, m.index + 6);
  }
  throw new Error('unbalanced ' + marker);
}
// The simulated system is 550W throughout. Official Codex discovery lives in
// the native launcher and is independent of these fictional display labels.
const brand = (text) => text.replace(/DeepSeek Harness/g, '550W').replace(/550C/g, '550W');

// Original stylesheet is copied byte for byte (no shadow DOM is necessary).
const originalCss = original.match(/<style>([\s\S]*?)<\/style>/)?.[1];
must(originalCss, 'stylesheet absent');
writeFileSync(resolve(root, 'web/animation.css'), '/* GENERATED: original 550C stylesheet, unchanged. */\n' + originalCss);

// Reuse only upstream's palette indirection and schemes. The optional terminal
// enhancement (new fonts, timestamps, gutters, progress cells) is deliberately
// excluded to keep the original author's animation layout and appearance.
let palette = enhance.slice(enhance.indexOf(':host{\n  --phos:'), enhance.indexOf('/* ── 桌面窗口的原生按钮'));
must(palette.includes('--glow-rgb') && palette.includes('data-scheme="white"'), 'palette extraction failed');
palette = palette.replace(/:host\(\[([^\]]+)\]\)/g, 'html[$1]').replace(/:host/g, ':root');
writeFileSync(resolve(root, 'web/palettes.css'), '/* GENERATED: palette-only part of upstream src/enhance.js (MIT). */\n' + palette);

// User-selected 550W: keep the original 550 geometry byte for byte and replace
// only the final C's two outline fragments. The reference video's stylized W
// shares its visual construction with the red zero: its visible white portion
// is a pointed, slanted two-leg shape with an upper-left cutout (not font text).
// All six path timings, the original viewBox, red zero and despike primitives
// stay intact. The completed red zero's blur glow is suppressed by launcher.css
// so its opening stays crisp through the final hold and native opacity fade.
// White path glows retain their original order; each glyph is still despiked.
let boot = element(original, '<div id="boot">').replace(/550C/g, '550W');
must(/<g id="cee">[\s\S]*?<\/g>/.test(boot), 'original C group absent');
boot = boot.replace(/<g id="cee">[\s\S]*?<\/g>/, `<g id="double-u">
          <path class="white" d="M597 30L620 30L657 176L645 220L627 220L589 80L580 99L572 75Z"/>
          <path class="white" d="M707 30L730 30L657 220L635 220Z"/>
        </g>`);
boot = boot.replace('<g id="logo" filter="url(#despike)">', '<g id="logo" aria-label="550W">');
let markup = boot + '\n' + brand(element(original, '<div id="app">')) + '\n' + element(original, '<div id="dim">') + '\n' + element(original, '<div id="final">');
writeFileSync(resolve(root, 'web/index.html'), `<!doctype html>
<!-- Local adaptation of Voidpoket's 550C page; see THIRD-PARTY-NOTICES.md. -->
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; media-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>550W Launcher</title>
<link rel="stylesheet" href="animation.css"><link rel="stylesheet" href="palettes.css"><link rel="stylesheet" href="launcher.css">
</head><body><div id="launcher-stage">${markup}</div>
<div id="launcher-status" role="status" aria-live="polite" hidden><span id="launcher-message"></span><button id="launcher-close" type="button" hidden>关闭启动器</button></div>
<script src="animation.js"></script><script src="launcher.js"></script></body></html>\n`);

let js = original.match(/<script>([\s\S]*?)<\/script>/)?.[1].trim();
must(js?.startsWith('(() => {') && js.endsWith('})();'), 'script IIFE absent');
js = js.slice('(() => {'.length, -'})();'.length).trim();
js = replaceOnce(js, 'const sleep = ms => new Promise(r => setTimeout(r, ms));', '/* sleep is supplied by the cancellable wrapper. */');
js = js.replace(/async function bootUp\(\)\{[\s\S]*?\n\}\n/, '');
js = js.replace(/window\.addEventListener\("keydown", e => \{[\s\S]*?\n\}\);/, '');
js = js.replace(/\/\* 自动开机[\s\S]*?document\.addEventListener\("touchstart", bootUp, \{ passive: true \}\);/, '');
js = js.replace(/\n\s*\$\(["']#hint["']\)\.classList\.add\(["']show["']\);/, '');
must(!/bootUp|#hint|window\.addEventListener|document\.addEventListener/.test(js), 'page triggers survived');
// Every timer and animation-frame callback is tracked, including popup timers
// and wave/injection intervals the plugin extractor did not fully cancel.
js = js.replace(/\bsetTimeout\(/g, 'later(').replace(/\bsetInterval\(/g, 'every(').replace(/\bclearInterval\(/g, 'stopEvery(').replace(/\brequestAnimationFrame\(/g, 'nextFrame(');
js = brand(js);
// Colored node inline SVGs follow the selected palette; default values remain
// the exact original RGB values. This is the only phase-machine color rewrite.
js = js.replace(/"#ffc043"/g, 'color("--amber-b")').replace(/"#e05030"/g, 'color("--red")').replace(/"#b8c840"/g, 'color("--green")');
// Record actual phase changes for tests and diagnostics, with no timing changes.
js = js.replace(/(\$\("#b-stage"\)\.textContent = "([^"]+)";)/g, '$1 options.onPhase?.("$2");');
// Preserve the six-fragment completion event for diagnostics. The independent
// controller starts sound with the animation and defers the final plate until
// the supplied track ends; the original phase timing remains unchanged.
js = replaceOnce(js, "later(() => logo.classList.add('finished'), totalMs);",
  "later(() => { logo.classList.add('finished'); options.onLogoVisible?.(); }, totalMs);");
js = replaceOnce(js, '$("#final").classList.add("show");',
  'await options.beforeReady?.();\n  if (cancelled) throw CANCELLED;\n  $("#final").classList.add("show"); options.onSystemReady?.();');
// Keep the original four countdown entries and their order. The requested
// slower countdown occupies the gap left by starting the 13-second MP3 early.
js = replaceOnce(js, 'mainLine(`[T-00:00:0${i}]`, "t"); await sleep(160);',
  'mainLine(`[T-00:00:0${i}]`, "t"); await sleep(800);');
const head = `/* GENERATED from original 550C-source.html by extract-animation.mjs. */
window.create550CShow = function create550CShow(options) {
  const CANCELLED = Symbol('cancelled');
  let cancelled = false;
  const pending = new Set(), intervals = new Set(), frames = new Set();
  const color = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  function sleep(ms) { return new Promise((resolve, reject) => {
    if (cancelled) { reject(CANCELLED); return; }
    const entry = { reject, timer: 0 };
    entry.timer = setTimeout(() => { pending.delete(entry); cancelled ? reject(CANCELLED) : resolve(); }, ms);
    pending.add(entry);
  }); }
  function later(fn, ms) {
    if (cancelled) return 0;
    const entry = { reject: null, timer: 0 };
    entry.timer = setTimeout(() => { pending.delete(entry); if (!cancelled) safe(fn); }, ms);
    pending.add(entry); return entry.timer;
  }
  function safe(fn) { try { fn(); } catch (error) { options.onError?.(error); cancel(); } }
  function every(fn, ms) { if (cancelled) return 0; const id = setInterval(() => { if (!cancelled) safe(fn); }, ms); intervals.add(id); return id; }
  function stopEvery(id) { clearInterval(id); intervals.delete(id); }
  function nextFrame(fn) { if (cancelled) return 0; const id = requestAnimationFrame(() => { frames.delete(id); if (!cancelled) safe(fn); }); frames.add(id); return id; }
  function cancel() {
    if (cancelled) return; cancelled = true;
    for (const entry of pending) { clearTimeout(entry.timer); entry.reject?.(CANCELLED); }
    pending.clear(); for (const id of intervals) clearInterval(id); intervals.clear();
    for (const id of frames) cancelAnimationFrame(id); frames.clear();
  }
  async function start() {
    if (booting || launched) return; booting = true;
    const startedAt = performance.now();
    const totalMs = playBoot();
    await sleep(totalMs + 300);
    if (options.mode !== 'full') { await sleep(600); return; }
    const boot = $("#boot"); boot.classList.add("fade"); await sleep(600); boot.remove();
    $("#app").classList.add("visible"); launched = true; await run();
    // Qt/Chromium timer granularity varies by GPU and machine. Preserve every
    // original phase and delay, then keep its final plate until the requested
    // approximately 16-second full presentation has elapsed. Skip cancels this
    // final hold through the same tracked sleep, with no orphaned timeout.
    const holdMs = 16000 - (performance.now() - startedAt);
    if (holdMs > 0) await sleep(holdMs);
  }
`;
writeFileSync(resolve(root, 'web/animation.js'), head + js + '\nreturn {start, cancel, isCancelled: error => error === CANCELLED, timers: () => ({pending: pending.size, intervals: intervals.size, frames: frames.size})};\n};\n');
console.log('Extracted unchanged stylesheet, original 550 + reference-inspired two-path W, original 9 phases, cancellable timers and upstream palettes.');
