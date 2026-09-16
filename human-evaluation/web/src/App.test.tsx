import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

vi.mock("@/components/MarkdownText", () => ({ MarkdownText: ({ children }: { children: string }) => <div>{children}</div> }));
vi.mock("@/components/AttachmentTile", () => ({ AttachmentTile: () => null }));
const dataset = { id: "test", model: "test", target_count: 2, items: [
  { id: "q001", query_en: "Question one", query_zh_tw: "問題一", answer: "Original answer one", media: [] },
  { id: "q002", query_en: "Question two", query_zh_tw: "問題二", answer: "Original answer two", media: [] },
] };
let saved: Record<string, unknown>[];
let failSave: boolean;
beforeEach(() => {
  localStorage.clear(); localStorage.setItem("badmintongpt-evaluator-code", "reviewer-01");
  saved = []; failSave = false;
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      if (failSave) return { ok: false, json: async () => ({ detail: "儲存失敗" }) };
      const result = { item_id: url.split("/").at(-1), ...JSON.parse(String(init.body)), updated_at: "now" };
      saved = [...saved.filter(r => r.item_id !== result.item_id), result];
      return { ok: true, json: async () => result };
    }
    return { ok: true, json: async () => url === "/api/dataset" ? dataset : { ratings: saved } };
  }));
});

describe("evaluation workflow", () => {
  it("gates the answer, clears Q2, and restores saved progress after remount", async () => {
    const app = render(<App />);
    await screen.findByText("Question one");
    expect(screen.queryByText("Original answer one")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /^合理 Realistic/ }));
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
    fireEvent.click(screen.getByRole("radio", { name: /^合理 Realistic/ }));
    expect(screen.getByRole("button", { name: "儲存並下一題" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "第 2 題" }));
    fireEvent.click(screen.getByRole("button", { name: "第 1 題" }));
    expect(screen.getByRole("radio", { name: /^合理 Realistic/ })).toBeChecked();
    expect(screen.getByText("尚未儲存")).toBeInTheDocument();
  });
});
