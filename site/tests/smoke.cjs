/* Smoke test of the static site in demo mode (?demo=1): no network, deterministic.
 * Serves site/ locally, drives it with Playwright, asserts the key flows work and that
 * nothing throws in the console. Run: `node site/tests/smoke.cjs`
 * (CI installs playwright; locally pass PW_EXECUTABLE_PATH=/opt/pw-browsers/chromium). */
const { chromium } = require("playwright");
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");            // the site/ folder
const PORT = 8771;

function serve() {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    if (p === "/") p = "/index.html";
    const fp = path.join(ROOT, p);
    if (!fp.startsWith(ROOT) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
      res.statusCode = 404; return res.end("not found");
    }
    const ext = path.extname(fp);
    res.setHeader("Content-Type", ext === ".js" ? "text/javascript" : ext === ".html" ? "text/html" : "text/plain");
    res.end(fs.readFileSync(fp));
  });
  return new Promise((resolve) => server.listen(PORT, () => resolve(server)));
}

function assert(cond, msg) { if (!cond) throw new Error("ASSERTION FAILED: " + msg); }

(async () => {
  const server = await serve();
  const launchOpts = process.env.PW_EXECUTABLE_PATH ? { executablePath: process.env.PW_EXECUTABLE_PATH } : {};
  const browser = await chromium.launch(launchOpts);
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

  try {
    await page.goto(`http://localhost:${PORT}/?demo=1`, { waitUntil: "networkidle" });
    await page.waitForSelector("#view-app:not([hidden])", { timeout: 10000 });

    // Offers tab renders
    const nOffers = await page.$$eval("#offer-list .offer", (e) => e.length);
    assert(nOffers > 0, "offers render in demo mode");

    // criteria filters: city = Paris reduces, reset restores
    await page.click('#offres .filters button[data-f="all"]');
    await page.waitForTimeout(100);
    const all = await page.$$eval("#offer-list .offer", (e) => e.length);
    await page.selectOption("#f-city", "Paris");
    await page.waitForTimeout(100);
    const paris = await page.$$eval("#offer-list .offer", (e) => e.length);
    assert(paris <= all && paris > 0, "city filter narrows the list");
    await page.click("#f-reset");
    await page.waitForTimeout(100);
    const reset = await page.$$eval("#offer-list .offer", (e) => e.length);
    assert(reset === all, "reset restores the full list");

    // « Suivre ce métier » appears on an à-vérifier offer and opens the confirm box
    await page.click('#offres .filters button[data-f="proche"]');
    await page.waitForTimeout(100);
    const promoteBtns = await page.$$eval(".promote > button", (b) => b.length);
    assert(promoteBtns > 0, "promote button on à-vérifier offers");
    await page.click(".promote > button");
    await page.waitForTimeout(100);
    assert((await page.$(".promote-box")) !== null, "promote confirm box opens");

    // Sources tab: filters + global criteria editor
    await page.click("#tab-sources");
    await page.waitForSelector("#sources:not([hidden])");
    assert((await page.$("#src-filters")) !== null, "sources filter bar present");
    await page.click("#defcrit > summary");
    await page.waitForTimeout(100);
    const checkedTypes = await page.$$eval("#dc-types input:checked", (i) => i.length);
    assert(checkedTypes > 0, "global criteria editor is populated");
    await page.fill("#dc-kw", "M&A");
    await page.click("#dc-save");
    await page.waitForFunction(() => /enregistr/i.test(document.getElementById("dc-msg").textContent), { timeout: 5000 });

    // « Nouvellement ajoutées » filter works
    await page.click('#src-filters button[data-sf="new"]');
    await page.waitForTimeout(100);
    const newCards = await page.$$eval("#source-list .src", (c) => c.length);
    assert(newCards >= 1, "nouvellement ajoutées filter shows recent companies");

    // Other tabs render
    await page.click("#tab-blocages");
    await page.waitForSelector("#blocages:not([hidden])");
    await page.click("#tab-ajouter");
    await page.waitForSelector("#ajouter:not([hidden])");

    assert(errors.length === 0, "no console errors (" + JSON.stringify(errors) + ")");
    console.log(`OK — site smoke test passed (${nOffers} offers, filters, promote, criteria editor, tabs).`);
  } finally {
    await browser.close();
    server.close();
  }
})().catch((e) => { console.error(e.message || e); process.exit(1); });
