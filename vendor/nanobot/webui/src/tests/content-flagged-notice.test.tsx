import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";

// [badmintonGPT fork] NANOBOT_MODERATION refusals.
describe("content_flagged notice", () => {
  it("asks to rephrase an ordinary flagged message", () => {
    render(<StreamErrorNotice error={{ kind: "content_flagged" }} onDismiss={vi.fn()} />);
    expect(screen.getByText("Message not sent")).toBeInTheDocument();
    expect(screen.getByText(/rephrase your badminton question/)).toBeInTheDocument();
  });

  it("points to crisis support when self-harm was detected", () => {
    render(<StreamErrorNotice error={{ kind: "content_flagged", selfHarm: true }} onDismiss={vi.fn()} />);
    expect(screen.getByText("You're not alone")).toBeInTheDocument();
    expect(screen.getByText(/crisis line/)).toBeInTheDocument();
  });
});
