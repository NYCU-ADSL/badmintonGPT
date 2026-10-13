import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InviteGate } from "@/components/InviteGate";
import { setAppLanguage } from "@/i18n";

// [badmintonGPT fork] NANOBOT_ACCOUNTS_INVITE_REQUIRED gate.
function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe("InviteGate", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows why a code was refused and activates on a good one", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => respond(400, { ok: false, reason: "invalid", retry_after_s: 0 }))
      .mockImplementationOnce(() =>
        respond(200, { ok: true, account: { email: "a@uni.edu", invite_required: false } }),
      );
    const onActivated = vi.fn();
    render(<InviteGate token="tok" email="a@uni.edu" onActivated={onActivated} onLogout={vi.fn()} />);

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Get started" }));
    await screen.findByText(/isn't valid/);
    expect(onActivated).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: " 開門碼 " } });
    fireEvent.click(screen.getByRole("button", { name: "Get started" }));
    await waitFor(() => expect(onActivated).toHaveBeenCalledWith(
      expect.objectContaining({ email: "a@uni.edu", invite_required: false }),
    ));
    const url = String(fetchMock.mock.calls[1][0]);
    expect(url).toBe(`/api/invite/redeem?code=${encodeURIComponent("開門碼")}`);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ headers: { Authorization: "Bearer tok" } });
  });

  it("locks the form while the gateway asks to wait", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementationOnce(() =>
      respond(429, { ok: false, reason: "cooldown", retry_after_s: 30 }),
    );
    render(<InviteGate token="tok" email="a@uni.edu" onActivated={vi.fn()} onLogout={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "again" } });
    fireEvent.click(screen.getByRole("button", { name: "Get started" }));
    await screen.findByText(/Try again in 30 s/);
    expect(screen.getByRole("button", { name: "Get started" })).toBeDisabled();
  });

  it("switches between Traditional Chinese and English in place", async () => {
    render(<InviteGate token="tok" email="a@uni.edu" onActivated={vi.fn()} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "繁體中文" }));
    expect(await screen.findByRole("heading", { name: "輸入邀請碼" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "繁體中文" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(await screen.findByRole("heading", { name: "Enter your invite code" })).toBeInTheDocument();
    await setAppLanguage("en");
  });
});
