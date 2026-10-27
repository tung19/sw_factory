// area.verify.visual — pixel layer. Screenshot the booted clone and the live
// reference at an identical viewport, then diff them.
//
// Run:  node visual_diff.mjs <cloneUrl> <referenceUrl> <outDir>
// Out:  <outDir>/{clone.png, reference.png, diff.png, pixel.json}
//       pixel.json = { mismatch, diffPixels, total, width, height }
//
// Image work lives here (JS) rather than in Python so AREA stays stdlib-only: the
// Playwright/chromium toolchain is already the e2e gate's. Every dependency is
// resolved dynamically and a clear message + non-zero exit is the contract when
// something is missing — the Python side turns that into a graceful skip.
const [cloneUrl, refUrl, outDir] = process.argv.slice(2);
if (!cloneUrl || !refUrl || !outDir) {
  console.error('usage: node visual_diff.mjs <cloneUrl> <referenceUrl> <outDir>');
  process.exit(2);
}

const VIEWPORT = { width: 1280, height: 800 };
const NAV_TIMEOUT = 45_000;

async function load(...names) {
  let last;
  for (const n of names) {
    try { return await import(n); } catch (e) { last = e; }
  }
  throw new Error(`cannot resolve ${names.join(' / ')} — ${last?.message ?? 'not installed'}`);
}

const { writeFileSync, mkdirSync } = await import('node:fs');
const path = await import('node:path');

let chromium, pixelmatch, PNG;
try {
  ({ chromium } = await load('playwright', '@playwright/test', 'playwright-core'));
  pixelmatch = (await load('pixelmatch')).default;
  ({ PNG } = await load('pngjs'));
} catch (e) {
  console.error(`missing dependency: ${e.message}`);
  console.error('enable the pixel layer with: npm i -D playwright pixelmatch pngjs && npx playwright install chromium');
  process.exit(3);
}

mkdirSync(outDir, { recursive: true });

// Fail with ONE clean line on stderr rather than an uncaught crash: the Python
// side reads this to turn a failure into a graceful, well-explained skip (a raw
// Node dump's last line is the useless `Node.js vXX` footer).
const firstLine = (e) => String(e?.message ?? e).split('\n')[0].trim();

let browser;
try {
  browser = await chromium.launch();
} catch (e) {
  console.error(`error: cannot launch chromium — ${firstLine(e)}`);
  if (/Executable doesn't exist|playwright install/i.test(String(e?.message ?? e))) {
    console.error('hint: npx playwright install chromium (the installed playwright '
      + 'expects a browser build that is not in the cache)');
  }
  process.exit(4);
}
try {
  const shoot = async (url, file) => {
    const page = await browser.newPage({ viewport: VIEWPORT });
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: NAV_TIMEOUT });
    } catch {
      // networkidle can never settle (polling/websockets) — a painted DOM is enough
      await page.waitForLoadState('domcontentloaded', { timeout: NAV_TIMEOUT });
    }
    const buf = await page.screenshot({ clip: { x: 0, y: 0, ...VIEWPORT } });
    writeFileSync(path.join(outDir, file), buf);
    await page.close();
    return PNG.sync.read(buf);
  };

  const clone = await shoot(cloneUrl, 'clone.png');
  const reference = await shoot(refUrl, 'reference.png');

  const { width, height } = VIEWPORT;
  const diff = new PNG({ width, height });
  const diffPixels = pixelmatch(
    clone.data, reference.data, diff.data, width, height,
    { threshold: 0.1, includeAA: true },
  );
  writeFileSync(path.join(outDir, 'diff.png'), PNG.sync.write(diff));

  const total = width * height;
  writeFileSync(
    path.join(outDir, 'pixel.json'),
    JSON.stringify({ mismatch: diffPixels / total, diffPixels, total, width, height }, null, 2),
  );
  console.log(`pixel mismatch ${(100 * diffPixels / total).toFixed(2)}% (${diffPixels}/${total})`);
} catch (e) {
  console.error(`error: ${firstLine(e)}`);
  process.exitCode = 5;
} finally {
  await browser.close();
}
