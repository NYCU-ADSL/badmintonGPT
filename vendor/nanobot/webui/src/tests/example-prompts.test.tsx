import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExamplePrompts } from "@/components/thread/ExamplePrompts";
import { ThreadComposer } from "@/components/thread/ThreadComposer";

// [badmintonGPT fork] home-screen example questions fill the composer.
describe("ExamplePrompts", () => {
  it("offers one example per feature and hands the full question to onPick", () => {
    const onPick = vi.fn();
    render(<ExamplePrompts onPick={onPick} />);

    expect(screen.getAllByRole("button")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: /Find any rally/ }));
    expect(onPick).toHaveBeenCalledWith("Find me a rally won with a net kill");
  });
});

describe("ThreadComposer prefill", () => {
  it("fills the input with each new prefill and leaves sending to the user", async () => {
    const onSend = vi.fn();
    const { rerender } = render(<ThreadComposer onSend={onSend} variant="hero" />);
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;

    rerender(<ThreadComposer onSend={onSend} variant="hero" prefill={{ id: 1, text: "first" }} />);
    await waitFor(() => expect(input.value).toBe("first"));

    fireEvent.change(input, { target: { value: "edited" } });
    rerender(<ThreadComposer onSend={onSend} variant="hero" prefill={{ id: 2, text: "second" }} />);
    await waitFor(() => expect(input.value).toBe("second"));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("ignores a prefill that was already there when it mounted", () => {
    render(<ThreadComposer onSend={vi.fn()} prefill={{ id: 3, text: "already sent" }} />);
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
  });
});
