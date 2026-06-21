// Message TTS — client-side preferences (voice + trigger mode).
// [badmintonGPT — see docs/MESSAGE_TTS.md / patches/webui-tts.patch]
//
// Precedence: a per-browser localStorage override (set when the user flips a control) wins;
// otherwise the repo-root .env default delivered via the bootstrap response (TTS_DEFAULT_VOICE /
// TTS_AUTO_PREFETCH); otherwise the built-in default. We persist ONLY on an explicit change, so a
// later .env edit stays live for browsers that never touched the setting.

import { useCallback, useState } from "react";

import { getTtsBootstrapDefaults } from "@/lib/bootstrap";

/** Voices offered in the picker. Keep in sync with the backend allow-list (TTS_VOICES in
 *  nanobot/channels/websocket.py). Only "chris" is confirmed upstream so far. */
export const TTS_VOICES = ["chris"] as const;
export const DEFAULT_TTS_VOICE = "chris";
// Fallback used only when the bootstrap omits `tts.max_segment_chars` (older gateway). The live
// value is server-driven (TTS_SEGMENT_CHARS). This is an internal latency knob, not a user
// preference, so it has NO localStorage override and NO Settings-UI control.
export const DEFAULT_TTS_SEGMENT_CHARS = 60;

const VOICE_KEY = "nanobot-webui.tts-voice";
const AUTOPREFETCH_KEY = "nanobot-webui.tts-autoprefetch";

function isKnownVoice(v: string | null | undefined): v is string {
  return !!v && (TTS_VOICES as readonly string[]).includes(v);
}

function readVoice(): string {
  try {
    const stored = localStorage.getItem(VOICE_KEY);
    if (isKnownVoice(stored)) return stored;
  } catch {
    // ignore
  }
  const fromEnv = getTtsBootstrapDefaults().defaultVoice;
  if (isKnownVoice(fromEnv)) return fromEnv;
  return DEFAULT_TTS_VOICE;
}

function readAutoPrefetch(): boolean {
  try {
    const stored = localStorage.getItem(AUTOPREFETCH_KEY);
    if (stored !== null) return stored === "1";
  } catch {
    // ignore
  }
  return getTtsBootstrapDefaults().autoPrefetch ?? false;
}

function readMaxSegmentChars(): number {
  const fromEnv = getTtsBootstrapDefaults().maxSegmentChars;
  if (typeof fromEnv === "number" && Number.isFinite(fromEnv) && fromEnv > 0) {
    return Math.floor(fromEnv);
  }
  return DEFAULT_TTS_SEGMENT_CHARS;
}

export interface TtsSettings {
  voice: string;
  setVoice: (voice: string) => void;
  autoPrefetch: boolean;
  setAutoPrefetch: (on: boolean) => void;
  /** Server-driven (bootstrap) max chars per /api/tts request; no per-browser override. */
  maxSegmentChars: number;
}

export function useTtsSettings(): TtsSettings {
  const [voice, setVoiceState] = useState<string>(readVoice);
  const [autoPrefetch, setAutoPrefetchState] = useState<boolean>(readAutoPrefetch);
  const [maxSegmentChars] = useState<number>(readMaxSegmentChars);

  const setVoice = useCallback((next: string) => {
    setVoiceState(next);
    try {
      localStorage.setItem(VOICE_KEY, next);
    } catch {
      // ignore
    }
  }, []);

  const setAutoPrefetch = useCallback((on: boolean) => {
    setAutoPrefetchState(on);
    try {
      localStorage.setItem(AUTOPREFETCH_KEY, on ? "1" : "0");
    } catch {
      // ignore
    }
  }, []);

  return { voice, setVoice, autoPrefetch, setAutoPrefetch, maxSegmentChars };
}
