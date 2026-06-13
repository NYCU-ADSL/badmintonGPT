// Message TTS — per-message speak/stop controller.
// [badmintonGPT — see docs/MESSAGE_TTS.md / patches/webui-tts.patch]
//
// Reads the spoken prose from a reply (markdownToSpeechText), splits it into segments, and plays
// them by fetching same-origin GET /api/tts (the gateway proxies to the upstream TTS with the key
// server-side). Audio is fetched as WAV Blobs — not via <audio src> — so the Bearer token can be
// sent and the blobs cached for instant re-plays. A module-level singleton guarantees only one
// message is audible at a time; an LRU cache holds the assembled segments per (messageId, voice).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { useTtsSettings } from "@/hooks/useTtsSettings";
import { markdownToSpeechText, segmentForTts } from "@/lib/tts-text";
import type { UIMessage } from "@/lib/types";

type TtsState = "idle" | "loading" | "playing" | "error";
type AriaKey = "speakReply" | "stopReply" | "speakLoading" | "speakError";

export interface MessageTts {
  state: TtsState;
  hasSpeech: boolean;
  ariaKey: AriaKey;
  toggle: () => void;
}

// --- module-level singletons (shared across all message bubbles) -----------------------------
const AUDIO_CACHE = new Map<string, Blob[]>(); // `${messageId}::${voice}` -> ordered segment WAVs
const CACHE_MAX = 20;
let activeStop: (() => void) | null = null;
let prefetchChain: Promise<void> = Promise.resolve(); // serialize auto-prefetch (one at a time)

function cacheGet(key: string): Blob[] | undefined {
  const v = AUDIO_CACHE.get(key);
  if (v) {
    AUDIO_CACHE.delete(key);
    AUDIO_CACHE.set(key, v); // bump to most-recent
  }
  return v;
}

function cacheSet(key: string, blobs: Blob[]): void {
  AUDIO_CACHE.delete(key);
  AUDIO_CACHE.set(key, blobs);
  while (AUDIO_CACHE.size > CACHE_MAX) {
    const oldest = AUDIO_CACHE.keys().next().value;
    if (oldest === undefined) break;
    AUDIO_CACHE.delete(oldest);
  }
}

function ttsUrl(text: string, voice: string): string {
  return `/api/tts?voice=${encodeURIComponent(voice)}&text=${encodeURIComponent(text)}`;
}

async function fetchSegmentBlob(
  text: string,
  voice: string,
  token: string,
  signal: AbortSignal,
): Promise<Blob> {
  const res = await fetch(ttsUrl(text, voice), {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
    signal,
  });
  if (!res.ok) throw new Error(`TTS ${res.status}`);
  return res.blob();
}

async function fetchAllBlobs(
  segments: string[],
  voice: string,
  token: string,
  signal: AbortSignal,
): Promise<Blob[]> {
  const blobs: Blob[] = [];
  for (const seg of segments) {
    blobs.push(await fetchSegmentBlob(seg, voice, token, signal));
  }
  return blobs;
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

// ---------------------------------------------------------------------------------------------

export function useMessageTts(message: UIMessage): MessageTts {
  const { token } = useClient();
  const { voice, autoPrefetch } = useTtsSettings();
  const [state, setState] = useState<TtsState>("idle");

  const speech = useMemo(
    () => (message.role === "assistant" ? markdownToSpeechText(message.content) : ""),
    [message.role, message.content],
  );
  const hasSpeech = speech.trim().length > 0;

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const urlsRef = useRef<string[]>([]);
  const errorTimerRef = useRef<number | null>(null);

  // Latest token/voice without forcing playback callbacks to be re-created mid-stream.
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const voiceRef = useRef(voice);
  voiceRef.current = voice;

  const cleanupPlayback = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      audio.removeAttribute("src");
      audioRef.current = null;
    }
    for (const url of urlsRef.current) URL.revokeObjectURL(url);
    urlsRef.current = [];
  }, []);

  const scheduleErrorReset = useCallback(() => {
    if (errorTimerRef.current !== null) window.clearTimeout(errorTimerRef.current);
    errorTimerRef.current = window.setTimeout(() => {
      errorTimerRef.current = null;
      setState("idle");
    }, 2000);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    cleanupPlayback();
    clearActiveStop(stop);
    setState("idle");
  }, [cleanupPlayback]);

  const beginPlayback = useCallback(
    (
      count: number,
      getBlob: (i: number) => Promise<Blob>,
      fromCache: boolean,
      onComplete?: () => void,
    ) => {
      const audio = new Audio();
      audioRef.current = audio;
      const urls = urlsRef.current;
      let idx = 0;
      setActiveStop(stop);
      setState(fromCache ? "playing" : "loading");

      const finish = (next: TtsState) => {
        cleanupPlayback();
        clearActiveStop(stop);
        setState(next);
        if (next === "error") scheduleErrorReset();
        else if (next === "idle") onComplete?.();
      };

      const step = async () => {
        if (audioRef.current !== audio) return; // superseded by a newer playback
        if (idx >= count) {
          finish("idle");
          return;
        }
        const cur = idx++;
        if (cur + 1 < count) void getBlob(cur + 1).catch(() => {}); // look-ahead one segment
        try {
          const blob = await getBlob(cur);
          if (audioRef.current !== audio) return;
          if (cur === 0) setState("playing");
          const url = URL.createObjectURL(blob);
          urls.push(url);
          audio.src = url;
          await audio.play();
        } catch (err) {
          if (audioRef.current === audio && !isAbort(err)) finish("error");
        }
      };

      audio.onended = () => {
        void step();
      };
      audio.onerror = () => {
        if (audioRef.current === audio) finish("error");
      };
      void step();
    },
    [cleanupPlayback, scheduleErrorReset, stop],
  );

  const start = useCallback(() => {
    if (!hasSpeech) return;
    abortRef.current?.abort();
    abortRef.current = null;
    cleanupPlayback();
    if (errorTimerRef.current !== null) {
      window.clearTimeout(errorTimerRef.current);
      errorTimerRef.current = null;
    }

    const key = `${message.id}::${voiceRef.current}`;
    const cached = cacheGet(key);
    if (cached && cached.length) {
      beginPlayback(cached.length, (i) => Promise.resolve(cached[i]), true);
      return;
    }

    const segments = segmentForTts(speech);
    if (!segments.length) return;

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const promises: (Promise<Blob> | undefined)[] = new Array(segments.length);
    const getBlob = (i: number): Promise<Blob> => {
      let p = promises[i];
      if (!p) {
        p = fetchSegmentBlob(segments[i], voiceRef.current, tokenRef.current, ctrl.signal);
        promises[i] = p;
      }
      return p;
    };

    const onComplete = () => {
      // Natural completion ⇒ every segment was fetched and resolved; cache for instant replay.
      Promise.all(promises as Promise<Blob>[])
        .then((blobs) => {
          if (!ctrl.signal.aborted) cacheSet(key, blobs);
        })
        .catch(() => {});
    };

    beginPlayback(segments.length, getBlob, false, onComplete);
  }, [hasSpeech, message.id, speech, beginPlayback, cleanupPlayback]);

  const toggle = useCallback(() => {
    if (state === "playing" || state === "loading") stop();
    else start();
  }, [state, stop, start]);

  // Auto-prefetch: when an assistant reply finishes streaming and the setting is on, warm the
  // cache (no playback) so the first click plays instantly. Serialized across messages.
  useEffect(() => {
    if (!autoPrefetch || !hasSpeech) return;
    if (message.role !== "assistant" || message.isStreaming) return;
    const key = `${message.id}::${voiceRef.current}`;
    if (cacheGet(key)) return;
    const segments = segmentForTts(speech);
    if (!segments.length) return;

    const ctrl = new AbortController();
    let cancelled = false;
    prefetchChain = prefetchChain.then(async () => {
      if (cancelled || ctrl.signal.aborted || cacheGet(key)) return;
      try {
        const blobs = await fetchAllBlobs(segments, voiceRef.current, tokenRef.current, ctrl.signal);
        if (!cancelled) cacheSet(key, blobs);
      } catch {
        // ignore prefetch failures — a click will retry
      }
    });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [autoPrefetch, hasSpeech, message.role, message.isStreaming, message.id, speech]);

  // Clean up on unmount.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      cleanupPlayback();
      clearActiveStop(stop);
      if (errorTimerRef.current !== null) window.clearTimeout(errorTimerRef.current);
    },
    [cleanupPlayback, stop],
  );

  const ariaKey: AriaKey =
    state === "playing"
      ? "stopReply"
      : state === "loading"
        ? "speakLoading"
        : state === "error"
          ? "speakError"
          : "speakReply";

  return { state, hasSpeech, ariaKey, toggle };
}

function setActiveStop(stop: () => void): void {
  if (activeStop && activeStop !== stop) activeStop();
  activeStop = stop;
}

function clearActiveStop(stop: () => void): void {
  if (activeStop === stop) activeStop = null;
}
