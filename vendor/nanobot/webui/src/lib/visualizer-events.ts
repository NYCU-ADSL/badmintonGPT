export const VISUALIZER_SEND_PROMPT_EVENT = "nanobot:visualizer-send-prompt";

export interface VisualizerSendPromptDetail {
  text: string;
}

/** Bridge: a `sendPrompt(text)` call inside a visualizer iframe → the chat composer. */
export function notifyVisualizerSendPrompt(text: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<VisualizerSendPromptDetail>(VISUALIZER_SEND_PROMPT_EVENT, {
    detail: { text },
  }));
}
