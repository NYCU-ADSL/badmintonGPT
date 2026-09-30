import { test, expect } from "@playwright/test";

test("real renderer and API: save, resume, Q2 reset and responsive layout", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("combobox", { name: "介面語言" }).selectOption("en");
  await page.getByLabel("Evaluator code", { exact: true }).fill(`browser-${Date.now()}`);
  await page.getByRole("button", { name: "Start evaluation" }).click();
  await expect(page.getByText("在這份測試資料中", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Rendering test fixture" })).toHaveCount(0);
  await page.getByRole("radio", { name: /^Realistic/ }).check();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.locator(".katex")).toHaveCount(1);
  await expect.poll(() => page.getByAltText("fixture.png").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);
  await expect(page.locator("video")).toHaveAttribute("src", "/api/media/q001/fixture.webm");
  await expect.poll(() => page.locator("video").evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThan(1);
  const visual = page.frameLocator('iframe[title="visualization"]');
  await expect(visual.getByRole("heading", { name: "Interactive chart fixture" })).toBeVisible();
  await visual.getByRole("button", { name: "Select player A" }).click();
  await expect(visual.getByRole("button", { name: "Selected" })).toBeVisible();
  await page.getByRole("radio", { name: /^Partially addresses/ }).check();
  const queries = await page.locator(".query-block p").allTextContents();
  await page.getByRole("combobox").selectOption("zh-TW");
  await expect(page.getByRole("radio", { name: /^部分符合/ })).toBeChecked();
  await expect(page.getByRole("button", { name: "複製程式碼" })).toBeVisible();
  expect(await page.locator(".query-block p").allTextContents()).toEqual(queries);
  await page.getByRole("combobox").selectOption("en");
  await expect(page.getByRole("button", { name: "Copy code" })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "../test-results/desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Save & next" }).click();
  await expect(page.getByRole("progressbar")).toHaveAttribute("value", "1");
  await page.reload();
  await expect(page.getByRole("combobox")).toHaveValue("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByText("Second browser test question.")).toBeVisible();
  await page.getByRole("button", { name: "Question 1, completed" }).click();
  await expect(page.getByRole("radio", { name: /^Partially addresses/ })).toBeChecked();
  await page.getByRole("radio", { name: /^Unrealistic/ }).check();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved to server")).toBeVisible();
  await page.getByRole("radio", { name: /^Realistic/ }).check();
  await expect(page.getByRole("radio", { name: /^Partially addresses/ })).not.toBeChecked();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "../test-results/mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});


test("240-question navigation on desktop and mobile in both languages", async ({ page }) => {
  const items = Array.from({ length: 240 }, (_, index) => ({ id: `q${index + 1}`,
    query_en: `Large dataset question ${index + 1}.`, query_zh_tw: `大量題庫問題 ${index + 1}。`,
    answer: `Original answer ${index + 1}.`, media: [],
  }));
  await page.route("**/api/dataset", route => route.fulfill({ json: { id: "large-navigation-fixture", model: "test", target_count: 240, items } }));
  await page.route("**/api/evaluators/*/ratings", route => route.fulfill({ json: { ratings: [] } }));
  await page.addInitScript(() => localStorage.setItem("badmintongpt-evaluator-code", "navigation-fixture"));
  await page.goto("/");
  await expect(page.locator(".question-grid button")).toHaveCount(20);
  await page.getByRole("spinbutton", { name: "跳至題號" }).fill("240");
  await page.getByRole("button", { name: "前往", exact: true }).click();
  await expect(page.getByText(items[239].query_en, { exact: true })).toBeVisible();
  await expect(page.getByText(items[239].query_zh_tw, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "第 240 題", exact: true })).toHaveAttribute("aria-current", "step");
  await page.getByRole("radio", { name: /^合理/ }).check();
  await page.getByRole("button", { name: "下一個未完成", exact: true }).click();
  await expect(page.getByText(items[0].query_en, { exact: true })).toBeVisible();
  await page.getByRole("combobox").selectOption("en");
  await page.getByRole("spinbutton", { name: "Jump to question" }).fill("240");
  await page.getByRole("button", { name: "Go", exact: true }).click();
  await expect(page.getByRole("radio", { name: /^Realistic/ })).toBeChecked();
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({ path: "../test-results/navigation-240-desktop.png", fullPage: true });
  for (const language of ["en", "zh-TW"]) {
    await page.getByRole("combobox").selectOption(language);
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  }
  await page.screenshot({ path: "../test-results/navigation-240-mobile.png", fullPage: true });
});


test("failed retrieval URL shows a reason; switching questions loads a compatible video", async ({ page }) => {
  const original = "/retrieval/encoded-id";
  const answer = `Original response.\n\n![Clip.mp4](${original})`;
  await page.route("**/api/dataset", route => route.fulfill({ json: {
    id: "playback-fixture", model: "test", target_count: 2,
    items: [1, 2].map(number => ({ id: `q${number}`, query_en: `Playback question ${number}`,
      query_zh_tw: `播放問題 ${number}`, answer, media: [], output_messages: [{ text: answer, media_urls: [] }],
      playback_sources: number === 2 ? { [original]: "/api/media/q001/fixture.webm" } : {},
    })),
  } }));
  await page.route("**/api/evaluators/*/ratings", route => route.fulfill({ json: { ratings: [] } }));
  await page.route("**/retrieval/encoded-id", route => route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"file not found"}' }));
  await page.addInitScript(() => {
    localStorage.setItem("badmintongpt-evaluator-code", "playback-fixture");
    localStorage.setItem("badmintongpt-evaluation-language", "en");
  });
  await page.goto("/");
  await page.getByRole("radio", { name: /^Realistic/ }).check();
  await expect(page.getByText(/This video could not be played/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open original video" })).toHaveAttribute("href", original);
  await page.getByRole("button", { name: "Retry playback" }).click();
  await expect(page.getByText(/This video could not be played/)).toBeVisible();
  await page.getByRole("button", { name: "Question 2", exact: true }).click();
  await page.getByRole("radio", { name: /^Realistic/ }).check();
  await expect(page.locator(".answer-body video")).toHaveAttribute("src", "/api/media/q001/fixture.webm");
  await expect.poll(() => page.locator(".answer-body video").evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThan(1);
  await expect(page.getByText("Original response.")).toBeVisible();
});
