import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import i18n, { LANGUAGE_KEY } from "./i18n";

vi.mock("@/components/MarkdownText", () => ({ MarkdownText: ({ children }: { children: string }) => <div>{children}</div> }));
vi.mock("@/components/AttachmentTile", () => ({ AttachmentTile: () => null, MediaPlaybackProvider: ({ children }: { children: React.ReactNode }) => children }));
const dataset = { id: "test", model: "test", target_count: 2, items: [
  { id: "q001", query_en: "Question one", query_zh_tw: "問題一", answer: "Original answer one", media: [] },
  { id: "q002", query_en: "Question two", query_zh_tw: "問題二", answer: "Original answer two", media: [] },
] };
let currentDataset = dataset;
let saved: Record<string, unknown>[];
let failSave: boolean;
beforeEach(async () => {
  await i18n.changeLanguage("zh-TW");
  localStorage.clear(); localStorage.setItem("badmintongpt-evaluator-code", "reviewer-01");
  saved = []; failSave = false; currentDataset = dataset;
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      if (failSave) return { ok: false, json: async () => ({ detail: "儲存失敗" }) };
      const result = { item_id: url.split("/").at(-1), ...JSON.parse(String(init.body)), updated_at: "now" };
      saved = [...saved.filter(r => r.item_id !== result.item_id), result];
      return { ok: true, json: async () => result };
    }
    return { ok: true, json: async () => url === "/api/dataset" ? currentDataset : { ratings: saved } };
  }));
});

describe("evaluation workflow", () => {
  it("gates the answer, clears Q2, and restores saved progress after remount", async () => {
    const app = render(<App />);
    await screen.findByText("Question one");
    expect(screen.queryByText("Original answer one")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /^合理/ }));
    expect(screen.getByText("Original answer one")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /^完全符合/ }));
    fireEvent.click(screen.getByRole("radio", { name: /^不合理/ }));
    expect(screen.queryByText("Original answer one")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0].q2).toBeNull();
    app.unmount(); render(<App />);
    await screen.findByText("Question two");
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "1");
  });

  it("keeps failed saves editable and only counts server-confirmed completion", async () => {
    render(<App />); await screen.findByText("Question one");
    fireEvent.click(screen.getByRole("radio", { name: /^有些牽強/ }));
    fireEvent.click(screen.getByRole("radio", { name: /^部分符合/ }));
    failSave = true;
    fireEvent.click(screen.getByRole("button", { name: "儲存並下一題" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("radio", { name: /^部分符合/ })).toBeChecked();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "0");
    failSave = false;
    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("value", "1"));
  });

  it("retains unsaved drafts when navigating and requires Q2 for completion", async () => {
    render(<App />); await screen.findByText("Question one");
    fireEvent.click(screen.getByRole("radio", { name: /^合理/ }));
    expect(screen.getByRole("button", { name: "儲存並下一題" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "第 2 題" }));
    fireEvent.click(screen.getByRole("button", { name: "第 1 題，尚未儲存" }));
    expect(screen.getByRole("radio", { name: /^合理/ })).toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent("尚未儲存");
  });
});

 it("switches UI and errors without refetching, losing drafts, or translating content", async () => {
   render(<App />); await screen.findByText("Question one");
   fireEvent.click(screen.getByRole("radio", { name: /^合理/ }));
   fireEvent.click(screen.getByRole("radio", { name: /^部分符合/ }));
   failSave = true;
   fireEvent.click(screen.getByRole("button", { name: "儲存" }));
   expect(await screen.findByRole("alert")).toHaveTextContent("無法儲存或讀取資料");
   const calls = vi.mocked(fetch).mock.calls.length;
   fireEvent.change(screen.getByRole("combobox"), { target: { value: "en" } });
   expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
   expect(screen.getByRole("radio", { name: /^Partially addresses/ })).toBeChecked();
   expect(screen.getByRole("alert")).toHaveTextContent("Unable to save or load data");
   expect(screen.getByText("Question one")).toBeVisible();
   expect(screen.getByText("問題一")).toBeVisible();
   expect(screen.getByText("Original answer one")).toBeVisible();
   expect(localStorage.getItem(LANGUAGE_KEY)).toBe("en");
   expect(document.documentElement.lang).toBe("en");
   expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
   fireEvent.change(screen.getByRole("combobox"), { target: { value: "zh-TW" } });
   expect(screen.getByRole("radio", { name: /^部分符合/ })).toBeChecked();
   expect(screen.getByRole("alert")).toHaveTextContent("無法儲存或讀取資料");
 });

function useLargeDataset(count: number) {
  currentDataset = { ...dataset, target_count: count, items: Array.from({ length: count }, (_, index) => ({
    id: `q${index + 1}`, query_en: `Question ${index + 1}`, query_zh_tw: `問題 ${index + 1}`,
    answer: `Answer ${index + 1}`, media: [],
  })) };
}

it("navigates 240 questions with bounded pages, direct jumps, drafts and wrapping", async () => {
  useLargeDataset(240);
  render(<App />); await screen.findByText("Question 1");
  expect(document.querySelectorAll(".question-grid button")).toHaveLength(20);
  expect(screen.getByRole("button", { name: "上一頁題號" })).toBeDisabled();
  fireEvent.click(screen.getByRole("radio", { name: /^合理/ }));
  fireEvent.click(screen.getByRole("button", { name: "下一頁題號" }));
  expect(screen.getByText("Question 1")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "第 21 題" }));
  expect(screen.getByText("Question 21")).toBeVisible();
  const jump = screen.getByRole("spinbutton", { name: "跳至題號" });
  fireEvent.change(jump, { target: { value: "240" } });
  fireEvent.click(screen.getByRole("button", { name: "前往" }));
  expect(screen.getByText("Question 240")).toBeVisible();
  expect(screen.getByRole("button", { name: "下一頁題號" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "第 240 題" })).toHaveAttribute("aria-current", "step");
  for (const invalid of ["0", "241", "1.5"]) {
    fireEvent.change(jump, { target: { value: invalid } });
    fireEvent.click(screen.getByRole("button", { name: "前往" }));
    expect(screen.getByRole("alert")).toHaveTextContent("1–240");
    expect(screen.getByText("Question 240")).toBeVisible();
  }
  fireEvent.click(screen.getByRole("button", { name: "下一個未完成" }));
  expect(screen.getByText("Question 1")).toBeVisible();
  expect(screen.getByRole("radio", { name: /^合理/ })).toBeChecked();
  expect(screen.getByRole("button", { name: "第 1 題，尚未儲存" })).toHaveAttribute("aria-current", "step");
  fireEvent.change(jump, { target: { value: "20" } });
  fireEvent.click(screen.getByRole("button", { name: "前往" }));
  fireEvent.click(screen.getByRole("radio", { name: /^不合理/ }));
  fireEvent.click(screen.getByRole("button", { name: "儲存並下一題" }));
  await screen.findByText("Question 21");
  expect(screen.getByRole("button", { name: "第 21 題" })).toHaveAttribute("aria-current", "step");
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "1");
});

it("resumes on a partial last page and disables next incomplete when all are saved", async () => {
  useLargeDataset(23);
  saved = currentDataset.items.slice(0, 22).map(item => ({ item_id: item.id, q1: "unrealistic", q2: null, updated_at: "now" }));
  render(<App />); await screen.findByText("Question 23");
  expect(document.querySelectorAll(".question-grid button")).toHaveLength(3);
  expect(screen.getByRole("button", { name: "第 21 題，已完成" })).toHaveTextContent("21");
  fireEvent.click(screen.getByRole("radio", { name: /^不合理/ }));
  expect(screen.getByRole("button", { name: "下一個未完成" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "儲存並完成" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "下一個未完成" })).toBeDisabled());
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "23");
});
