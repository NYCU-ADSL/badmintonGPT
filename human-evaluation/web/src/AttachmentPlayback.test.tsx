import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { AttachmentTile, MediaPlaybackProvider } from "@/components/AttachmentTile";
import i18n from "./i18n";

it("offers retry and the original URL, then recovers when a display copy or source changes", async () => {
  await i18n.changeLanguage("en");
  const original = "https://video.example/files/encoded-id";
  const app = render(<AttachmentTile attachment={{ kind: "video", url: original, name: "Clip.mp4" }} />);
  fireEvent.error(screen.getByLabelText("Video attachment: Clip.mp4"));
  expect(screen.getByRole("status")).toHaveTextContent("could not be played");
  expect(screen.getByRole("link", { name: "Open original video" })).toHaveAttribute("href", original);
  fireEvent.click(screen.getByRole("button", { name: "Retry playback" }));
  expect(screen.getByLabelText("Video attachment: Clip.mp4")).toHaveAttribute("src", original);
  fireEvent.error(screen.getByLabelText("Video attachment: Clip.mp4"));
  app.rerender(<AttachmentTile attachment={{ kind: "video", url: "https://video.example/files/next", name: "Clip.mp4" }} />);
  expect(screen.getByLabelText("Video attachment: Clip.mp4")).toHaveAttribute("src", "https://video.example/files/next");
  app.rerender(<MediaPlaybackProvider value={{ [original]: "/api/media/q001/compatible.mp4" }}>
    <AttachmentTile attachment={{ kind: "video", url: original, name: "Clip.mp4" }} />
  </MediaPlaybackProvider>);
  const video = screen.getByLabelText("Video attachment: Clip.mp4");
  expect(video).toHaveAttribute("src", "/api/media/q001/compatible.mp4");
  fireEvent.error(video);
  expect(screen.getByRole("link", { name: "Open original video" })).toHaveAttribute("href", original);
});
