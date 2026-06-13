// Message TTS — client-side preferences (voice + trigger mode), persisted to localStorage.
// [badmintonGPT — see docs/MESSAGE_TTS.md / patches/webui-tts.patch]
// Mirrors the useTheme.ts pattern: read on mount, write on change. Usable both in the Settings
// panel (to render the controls) and in useMessageTts (to read the active values).

import { useCallback, useEffect, useState } from "react";

/** Voices offered in the picker. Keep in sync with the backend allow-list (TTS_VOICES in
 *  nanobot/channels/websocket.py). Only "chris" is confirmed upstream so far. */
export const TTS_VOICES = ["chris"] as const;
export const DEFAULT_TTS_VOICE = "chris";

const VOICE_KEY = "nanobot-webui.tts-voice";
const AUTOPREFETCH_KEY = "nanobot-webui.tts-autoprefetch";

function readVoice(): string {
  try {
    const v = localStorage.getItem(VOICE_KEY);
    return v && (TTS_VOICES as readonly string[]).includes(v) ? v : DEFAULT_TTS_VOICE;
  } catch {
    return DEFAULT_TTS_VOICE;
  }
}

function readAutoPrefetch(): boolean {
  try {
    return localStorage.getItem(AUTOPREFETCH_KEY) === "1";
  } catch {
    return false;
  }
}

export interface TtsSettings {
  voice: string;
  setVoice: (voice: string) => void;
  autoPrefetch: boolean;
  setAutoPrefetch: (on: boolean) => void;
}

export function useTtsSettings(): TtsSettings {
  const [voice, setVoiceState] = useState<string>(readVoice);
  const [autoPrefetch, setAutoPrefetchState] = useState<boolean>(readAutoPrefetch);

  useEffect(() => {
    try {
      localStorage.setItem(VOICE_KEY, voice);
    } catch {
      // ignore
    }
  }, [voice]);

  useEffect(() => {
    try {
      localStorage.setItem(AUTOPREFETCH_KEY, autoPrefetch ? "1" : "0");
    } catch {
      // ignore
    }
  }, [autoPrefetch]);

  const setVoice = useCallback((next: string) => setVoiceState(next), []);
  const setAutoPrefetch = useCallback((on: boolean) => setAutoPrefetchState(on), []);

  return { voice, setVoice, autoPrefetch, setAutoPrefetch };
}
