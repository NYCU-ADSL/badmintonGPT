// Verify the deployed, genuinely generated dataset. Ratings use a reserved test code.
// Remove that exact code's rows after the check (see report.evaluator_code).
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const base = process.env.EVAL_URL;
if (!base) throw new Error("Set EVAL_URL to the deployed evaluation URL");
const expected = Number(process.env.EVAL_EXPECTED_COUNT ?? 10);
const out = path.resolve("../runtime/live-verification");
await mkdir(out, { recursive: true });
const code = `validation-${Date.now()}`;
const browser = await chromium.launch({ executablePath: process.env.EVAL_BROWSER_EXECUTABLE });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on("pageerror", e => errors.push(e.message));
const report = { url: base, evaluator_code: code, checked_at: new Date().toISOString(), items: [] };
try {
  const response = await page.request.get(base + "/api/dataset");
  if (!response.ok()) throw new Error(`Dataset HTTP ${response.status()}`);
  const dataset = await response.json();
  if (dataset.items.length !== expected) throw new Error(`Expected ${expected} items, got ${dataset.items.length}`);
  report.dataset_id = dataset.id;
  report.model = dataset.model;
  await page.goto(base, { waitUntil: "networkidle" });
  await page.getByLabel("評測代碼", { exact: true }).fill(code);
  await page.getByRole("button", { name: "開始評測" }).click();
  await page.getByText(dataset.items[0].query_en, { exact: true }).waitFor();
  for (let i = 0; i < dataset.items.length; i++) {
    if (i) await page.getByRole("button", { name: `第 ${i + 1} 題`, exact: true }).click();
    await page.getByText(dataset.items[i].query_en, { exact: true }).waitFor();
    await page.getByText(dataset.items[i].query_zh_tw, { exact: true }).waitFor();
    if (await page.locator(".answer-body").count()) throw new Error("Answer visible before Q1");
    await page.getByRole("radio", { name: /^合理 Realistic/ }).check();
    await page.locator(".answer-body").waitFor();
    // The real renderer is lazy-loaded; wait for it, not its plain-text fallback.
    await page.locator(".answer-body .markdown-content").first().waitFor({ state: "attached" });
    if (await page.locator(".answer-body video").count()) {
      await page.waitForFunction(() => [...document.querySelectorAll(".answer-body video")]
        .every(video => video.readyState >= 1 || video.error), undefined, { timeout: 45000 });
    }
    report.items.push({ id: dataset.items[i].id,
      answer_chars: dataset.items[i].answer.length,
      tables: await page.locator(".answer-body table").count(),
      visualizations: await page.locator('iframe[title="visualization"]').count(),
      media: await page.locator(".answer-body video,.answer-body img").evaluateAll(els => els.map(e => ({
        tag: e.tagName, src: e.getAttribute("src"),
        ...(e.tagName === "VIDEO" ? {ready_state: e.readyState, duration: e.duration, error_code: e.error?.code ?? null} : {}),
      }))),
    });
    if (i === 0 || i === dataset.items.length - 1) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(out, `question-${i + 1}.png`), fullPage: true });
    }
  }
  await page.getByRole("radio", { name: /^部分符合/ }).check();
  await page.getByRole("button", { name: "儲存", exact: true }).click();
  await page.getByText("已儲存至伺服器").waitFor();
  const saved = await (await page.request.get(`${base}/api/evaluators/${code}/ratings`)).json();
  if (saved.completed !== 1 || saved.ratings[0].q2 !== "partially_addresses") throw new Error("Server did not save rating");
  await page.reload();
  await page.getByRole("button", { name: `第 ${expected} 題，已完成`, exact: true }).click();
  if (!await page.getByRole("radio", { name: /^部分符合/ }).isChecked()) throw new Error("Rating did not survive reload");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(out, "mobile.png"), fullPage: true });
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error("Mobile horizontal overflow");
  if (errors.length) throw new Error(errors.join("\n"));
  report.status = "passed";
  report.persistence_verified = true;
} catch (error) {
  report.status = "failed";
  report.error = String(error);
  process.exitCode = 1;
} finally {
  report.browser_errors = errors;
  await writeFile(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n");
  await browser.close();
  console.log(JSON.stringify(report, null, 2));
}
