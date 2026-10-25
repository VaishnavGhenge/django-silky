// Browser-side benchmark for the Silk UI.
//
// Loads each page (URLs come from a server_bench results file) in a fresh,
// cache-less browser context several times and records load timings, Largest
// Contentful Paint, layout shift, main-thread blocking and asset weight.
//
//   node benchmarks/browser_bench.mjs --base http://127.0.0.1:8010 \
//        --pages benchmarks/results/baseline-server-5000.json --label baseline [--cpu 4]
//
// Set CHROMIUM_PATH to use a specific Chromium build instead of Playwright's.

import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : dflt;
};
const base = arg('base', 'http://127.0.0.1:8010');
const pagesFile = arg('pages', 'benchmarks/results/baseline-server-5000.json');
const label = arg('label', 'run');
const runs = Number(arg('runs', '5'));
const cpu = Number(arg('cpu', '1')); // CPU slowdown factor, e.g. 4 for an average laptop under load
const out = arg('out', pagesFile.replace('-server-', cpu > 1 ? `-browser-cpu${cpu}x-` : '-browser-'));

const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
const round = (x, d = 0) => Number(x.toFixed(d));

// Collected inside the page after load: navigation timing, LCP, CLS, long tasks.
const PAGE_METRICS = () => new Promise((resolve) => {
  let lcp = 0, cls = 0, tbt = 0;
  new PerformanceObserver((l) => { for (const e of l.getEntries()) lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) tbt += Math.max(0, e.duration - 50); }).observe({ type: 'longtask', buffered: true });
  setTimeout(() => {
    const n = performance.getEntriesByType('navigation')[0];
    // Asset weight from Resource Timing: exact decoded sizes, no race with the network events.
    const kb = { doc: n.decodedBodySize / 1024, js: 0, css: 0, font: 0, img: 0, other: 0 };
    const res = performance.getEntriesByType('resource');
    for (const r of res) {
      const url = r.name.split('?')[0];
      const key = /\.m?js$/.test(url) ? 'js' : /\.css$/.test(url) ? 'css' : /\.(woff2?|ttf|otf)$/.test(url) ? 'font' : /\.(png|jpe?g|gif|svg|webp|ico)$/.test(url) ? 'img' : 'other';
      kb[key] += r.decodedBodySize / 1024;
    }
    resolve({ ttfb: n.responseStart, dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd, lcp, cls, tbt, kb, requests: res.length + 1 });
  }, 600);
});

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const pages = JSON.parse(readFileSync(pagesFile, 'utf8')).pages;
const result = { label, base, runs, cpu, pages: {} };

for (const [name, info] of Object.entries(pages)) {
  const samples = [];
  let assets = null;
  for (let i = 0; i < runs; i++) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    if (cpu > 1) await (await ctx.newCDPSession(page)).send('Emulation.setCPUThrottlingRate', { rate: cpu });
    await page.goto(base + info.url, { waitUntil: 'load' });
    const m = await page.evaluate(PAGE_METRICS);
    // Pages with htmx filter chips: time from a chip click until the swapped results settle.
    m.interaction = await page.evaluate(() => new Promise((resolve) => {
      const chip = document.querySelector('[data-chip="method"]');
      if (!chip || !window.htmx) return resolve(null);
      const start = performance.now();
      document.addEventListener('htmx:afterSettle', () => resolve(performance.now() - start), { once: true });
      chip.click();
      setTimeout(() => resolve(null), 5000);
    }));
    samples.push(m);
    if (!assets) assets = { requests: m.requests, kb: Object.fromEntries(Object.entries(m.kb).map(([k, v]) => [k, round(v, 1)])) };
    await ctx.close();
  }
  const pick = (k) => median(samples.map((s) => s[k]));
  result.pages[name] = {
    url: info.url,
    ttfb_ms: round(pick('ttfb')), dcl_ms: round(pick('dcl')), load_ms: round(pick('load')), lcp_ms: round(pick('lcp')),
    cls: round(pick('cls'), 3), tbt_ms: round(pick('tbt')),
    filter_ms: samples[0].interaction == null ? null : round(median(samples.map((x) => x.interaction))),
    requests: assets.requests, total_kb: round(Object.values(assets.kb).reduce((a, b) => a + b, 0), 1), kb: assets.kb,
  };
  const r = result.pages[name];
  console.log(`${name.padEnd(22)} load ${String(r.load_ms).padStart(5)} ms  lcp ${String(r.lcp_ms).padStart(5)} ms  cls ${r.cls.toFixed(3)}  tbt ${String(r.tbt_ms).padStart(4)} ms  ${String(r.requests).padStart(3)} req  ${r.total_kb} KB (js ${r.kb.js})${r.filter_ms != null ? `  filter ${r.filter_ms} ms` : ''}`);
}

await browser.close();
writeFileSync(out, JSON.stringify(result, null, 2) + '\n');
console.log(`\nwrote ${out}`);
