# Message TTS — Design Document

Add a **speaker button** beside the existing copy button on each assistant message in the
WebUI. Clicking it reads the message aloud via a remote Qwen3‑TTS service. Only the **plain
prose** is spoken — code, tables, math, charts, and media are skipped.

This document is the complete, build-ready design. Section 1 restates the task and the resolved
product decisions; sections 2–11 are the architecture, the backend proxy, the frontend, the
plain‑text extraction rules, config/secrets, the build/patch loop, edge cases, security, and the
testing plan; section 12 is the concrete file-change checklist.

---

## 1. Task & resolved decisions

### 1.1 Original task

> Add a speaker button to the right of the copy button in a message. When clicked, play the
> speech of the current message. Play **only the plain text** — do not speak code, charts, tables,
> or other non-prose (e.g. video embeds).

### 1.2 TTS API (upstream)

The remote service is OpenAI-`/v1/audio/speech`-compatible:

```bash
curl -X POST https://llm.andyjjrt.cc/v1/audio/speech \
     -H "Content-Type: application/json" \
     -H 'Authorization: Bearer <TTS_API_KEY>' \
     -d '{
        "model": "DGX/Qwen3-TTS",
        "input": "<input text>",
        "voice": "<VOICE>",
        "stream": true,
        "response_format": "pcm"
    }' --no-buffer | play -t raw -r 24000 -e signed -b 16 -c 1 -
```

- `TTS_API_KEY` lives in this repo's `.env` (server-side only).
- Default `voice` is `"chris"`.
- The documented stream format is **raw PCM**: `24000 Hz, signed 16-bit little-endian, mono`
  (that is what the `play -t raw -r 24000 -e signed -b 16 -c 1` flags decode). Browsers cannot
  play raw PCM directly, so the proxy wraps it in a WAV container (§4.3).

### 1.3 Decisions (confirmed with the product owner)

| # | Decision | Choice |
|---|----------|--------|
| D1 | **When is audio generated?** | Support **both** an *auto-prefetch* mode (generate as soon as a reply finishes streaming, cache it, play instantly on click) **and** an *on-demand* mode (generate lazily on first click, cache for replays). A **Settings toggle** switches between them. Pure "fetch every click, never cache" is **not** wanted — caching is always on. |
| D2 | **How does the browser reach the TTS API / where does the key live?** | **Gateway proxy.** Add a `/api/tts` route to the gateway; `TTS_API_KEY` stays server-side. The browser calls same-origin `/api/tts`, so there is no CORS issue and the bearer token never ships in the bundle. |
| D3 | **Voice configurability** | A **voice dropdown in the WebUI Settings panel**, persisted to `localStorage`, defaulting to `"chris"`. |

Default trigger mode (D1): **on-demand** (no TTS spend on replies nobody plays); the user can opt
into auto-prefetch.

---

## 2. Why a gateway proxy (and the GET-only constraint)

A direct browser → `llm.andyjjrt.cc` call is a non-starter for two independent reasons:

1. **Key exposure.** The bearer token would have to be baked into the JS bundle (or fetched to the
   client), visible to any Cloudflare-Access-authed user in the network tab. Today **no secret
   reaches the browser** — settings are masked (`••••{last4}`), and the WebUI talks to the gateway
   over an authenticated WebSocket. The TTS feature must preserve that posture.
2. **CORS.** `llm.andyjjrt.cc` is an inference endpoint with no reason to send
   `Access-Control-Allow-Origin` for our WebUI origin; a browser `fetch` would be blocked.

So the browser calls the **same-origin gateway**, which proxies to the upstream with the key
injected server-side. This matches the repo's zero-trust architecture (`OPENAI_API_KEY`,
`REELS_CF_*` are all server-side only).

### 2.1 The GET-only constraint

The gateway serves HTTP routes *beside* the WebSocket on port `8765` via
`NanobotWebSocketChannel._dispatch_http` → `_dispatch_api_route`
(`vendor/nanobot/nanobot/channels/websocket.py:696`). It is built on the `websockets` library,
whose HTTP parser **only accepts GET** — the code even folds session deletion into a GET path
(`/api/sessions/{id}/delete`) with the comment:

> *"websockets' HTTP parser only accepts GET, so we cannot expose a true DELETE verb."*

**Consequence:** the TTS proxy route must be a **GET**. The message text therefore cannot be sent
in a POST body — it goes in the query string. To stay well under URL-length limits (and to lower
time-to-first-audio), the frontend extracts the plain text and **splits it into bounded segments**,
issuing one GET per segment (§5.4). Binary responses are returned with the same
`Response(status, reason, Headers(...), body_bytes)` shape already used by `/api/media/...`
(`media_api.py:serve_signed_media`).

---

## 3. High-level architecture

```
┌─────────────────────────── Browser (WebUI, behind Cloudflare Access) ───────────────────────────┐
│                                                                                                  │
│  MessageBubble  ──speaker click──▶  useMessageTts hook                                           │
│     (footer)                          │  1. markdownToSpeechText(message.content)  → plain text  │
│                                       │  2. segment into sentence-bounded chunks               │
│                                       │  3. for each chunk:  GET /api/tts?voice=&text=          │
│                                       │  4. enqueue returned WAV blobs, play gaplessly          │
│                                       │  5. cache by (messageId, voice)                          │
└───────────────────────────────────────│──────────────────────────────────────────────────────┘
                                         │  same-origin GET  (Authorization / ?token = bootstrap token)
                                         ▼
┌──────────────────────── Gateway :8765  (nanobot WebSocket channel, GET-only HTTP) ───────────────┐
│  _dispatch_http → _dispatch_api_route → _handle_tts(request)            [NEW patch]              │
│     • auth-gate with _check_api_token                                                            │
│     • validate voice + text length                                                              │
│     • openai SDK: AsyncOpenAI(base_url=TTS_API_BASE).audio.speech.create  (key server-side)      │
│         model=TTS_MODEL, input=text, voice, response_format="pcm"                                │
│     • read PCM → wrap WAV header (24kHz/s16/mono)                                                │
│     • return Response(200, "OK", {Content-Type: audio/wav, Cache-Control}, wav_bytes)           │
└───────────────────────────────────────│──────────────────────────────────────────────────────┘
                                         │  Authorization: Bearer $TTS_API_KEY
                                         ▼
                         https://llm.andyjjrt.cc/v1/audio/speech  (Qwen3-TTS, PCM stream)
```

**Key properties**

- Same-origin → no CORS; key stays in the gateway container.
- One GET per text segment → URLs stay short; the first segment can start playing while later
  segments are still being fetched.
- The proxy buffers each segment's PCM fully (the `websockets` `Response` is non-streaming) and
  returns a complete, browser-native WAV. Segments are short, so per-request latency is small.

---

## 4. Backend: the `/api/tts` proxy route

A new **nanobot patch** (`patches/webui-tts-proxy.patch`) editing
`vendor/nanobot/nanobot/channels/websocket.py`. It follows the existing patterns
(`webui-trust-proxy-auth.patch`, `reply-language.patch`): a self-contained, marked block.

### 4.1 Routing

Register the route in `_dispatch_misc_api_route`
(`websocket.py:749`, alongside `/api/commands`, `/api/workspaces`):

```python
# [badmintonGPT patch — see patches/webui-tts-proxy.patch]
if got == "/api/tts":
    return await self._handle_tts(request)
```

`_dispatch_misc_api_route` is currently sync; either make the misc dispatch awaitable (it is
already called from the `async _dispatch_api_route`) or branch on the path earlier inside the
`async _dispatch_api_route` so `_handle_tts` can be `async`. (Cleanest: add an
`await self._dispatch_async_misc(...)` branch in `_dispatch_api_route`.)

### 4.2 Request contract

`GET /api/tts?voice=<voice>&text=<url-encoded plain text>[&token=<bootstrap token>]`

| Param | Required | Notes |
|-------|----------|-------|
| `text` | yes | URL-encoded UTF-8 plain text for **one segment**. Server rejects if empty or longer than `TTS_MAX_INPUT_CHARS` (default 1200). |
| `voice` | no | Defaults to `TTS_DEFAULT_VOICE` (`"chris"`). Validated against an allow-list (`TTS_VOICES`) to avoid passing arbitrary values upstream. |
| `token` | conditionally | The WebUI bootstrap token, the same one the WS handshake uses. Required when a secret is configured; behind Cloudflare Access + `NANOBOT_WEBUI_TRUST_PROXY=1` the gate still runs via `_check_api_token`. |

**Auth.** Gate with `self._check_api_token(request)` (used by the mutating session routes) so the
proxy is **not an open, unauthenticated TTS relay** — important because each call costs upstream
compute. Confirm how existing `/api/*` reads attach the token from the client
(`webui/src/lib/api.ts`); reuse that mechanism (Authorization header or `?token=`).

### 4.3 Upstream call + PCM→WAV wrapping

```python
async def _handle_tts(self, request: WsRequest) -> Response:
    if not self._check_api_token(request):
        return _http_error(401, "Unauthorized")

    query = _parse_query(request.path)
    text = (_query_first(query, "text") or "").strip()
    voice = _query_first(query, "voice") or TTS_DEFAULT_VOICE
    if not text:
        return _http_error(400, "empty text")
    if len(text) > TTS_MAX_INPUT_CHARS:
        return _http_error(413, "text too long")
    if voice not in TTS_VOICES:
        return _http_error(400, "unknown voice")

    api_key = os.environ.get("TTS_API_KEY")
    if not api_key:
        return _http_error(503, "TTS not configured")

    import openai
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=TTS_API_BASE, timeout=TTS_TIMEOUT_S)
    try:
        async with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL, voice=voice, input=text, response_format="pcm",
        ) as resp:
            pcm = await resp.read()
    except openai.APIStatusError as e:
        detail = (getattr(e, "message", "") or str(getattr(e, "body", "")))[:300]
        logger.warning("TTS upstream returned {} for model {!r}: {}", e.status_code, TTS_MODEL, detail)
        return _http_error(502, f"TTS upstream {e.status_code}")
    except openai.APIError as e:
        logger.warning("TTS proxy upstream error: {}", e)
        return _http_error(502, "TTS upstream error")
    finally:
        await client.close()

    wav = _pcm_to_wav(pcm)  # 24000 Hz / 16-bit / mono
    return _http_response(wav, content_type="audio/wav", extra_headers=[("Cache-Control", "no-store")])
```

> **Why the openai SDK, not raw httpx?** `import openai` is a hard nanobot dependency and its
> providers already use `AsyncOpenAI`; `base_url=TTS_API_BASE` (the `/v1` root — the SDK appends
> `/audio/speech`) keeps the call standard, and `response_format="pcm"` returns raw little-endian
> PCM (the upstream mislabels every format as `audio/mpeg` in the header, but the `pcm` **body** is
> genuinely raw PCM — verified), so `_pcm_to_wav` is still correct.

`_pcm_to_wav` prepends a 44-byte canonical WAV/RIFF header for `24000 Hz / 16-bit / mono` (use
Python's `wave` module into an `io.BytesIO`, or write the header by hand). No resampling needed —
the browser decodes the rate from the header.

Module constants (top of the patch block):

```python
TTS_API_BASE = os.environ.get("TTS_API_BASE", "https://llm.andyjjrt.cc/v1")  # openai SDK base_url
TTS_MODEL = os.environ.get("TTS_API_MODEL", "DGX/Qwen3-TTS")
TTS_DEFAULT_VOICE = os.environ.get("TTS_DEFAULT_VOICE", "chris")
TTS_VOICES = {"chris"}            # extend once the upstream voice catalog is confirmed (§9)
TTS_MAX_INPUT_CHARS = 1200
TTS_TIMEOUT_S = 60.0
```

> **Why request `pcm` and wrap, instead of asking upstream for `wav`/`mp3`?** The doc only verifies
> `pcm` works. Wrapping PCM→WAV is deterministic and avoids depending on unverified format support.
> If the upstream is later confirmed to support `response_format: "wav"` (or `mp3`), the proxy can
> pass it through unchanged and set the matching `Content-Type`, skipping the wrap step.

### 4.4 Why buffer instead of stream

The `websockets` `Response` carries a single complete `body` (bytes) — it is not a streaming
response object, so the proxy must read the whole upstream PCM for a segment before returning.
Because the frontend sends **short segments**, each buffered response is small and fast; gapless
playback across segments (§5.5) recovers the "streaming feel" without needing a streaming HTTP
transport. (A future WS-based binary transport could stream, but it would touch the agent message
bus and is out of scope.)

---

## 5. Frontend

All new frontend code is a **WebUI patch** (`patches/webui-tts.patch`) on
`vendor/nanobot/webui/`. React 18 + TypeScript + Tailwind + lucide-react.

### 5.1 The speaker button (MessageBubble)

Insert the speaker button into the assistant footer row in
`vendor/nanobot/webui/src/components/MessageBubble.tsx`, **immediately after** the copy button
(currently `MessageBubble.tsx:154–171`, inside the `showAssistantFooterRow` block at lines
152–182). It mirrors the copy button's styling exactly (same 32px rounded hover target):

```tsx
{showSpeakButton ? (
  <button
    type="button"
    onClick={tts.toggle}
    disabled={tts.state === "unavailable"}
    aria-label={t(`message.${tts.ariaKey}`)}
    title={t(`message.${tts.ariaKey}`)}
    className={cn(
      "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
      "transition-colors hover:bg-muted/55 hover:text-foreground",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      "disabled:opacity-40 disabled:hover:bg-transparent",
    )}
  >
    {tts.state === "loading" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> :
     tts.state === "playing" ? <Square className="h-4 w-4" aria-hidden /> :
     <Volume2 className="h-4 w-4" aria-hidden />}
  </button>
) : null}
```

Visibility: show the speaker button under the same conditions as copy
(`showAssistantActions` — assistant role, not streaming, non-empty) **and** only when the message
yields non-empty speech text (`showSpeakButton = showAssistantActions && tts.hasSpeech`). A reply
that is *all* code/tables shows **no** speaker button (nothing to read). Icons (`Volume2`,
`Square`, `Loader2`) all come from the already-bundled `lucide-react`.

### 5.2 The `useMessageTts` hook

A new hook `vendor/nanobot/webui/src/hooks/useMessageTts.ts` encapsulates extraction, fetching,
caching, and playback. State machine per message:

```
idle ──click──▶ loading ──first chunk decoded──▶ playing ──(ended | click | another msg starts)──▶ idle
  ▲                  │                                  │
  └────── error ◀────┴──────────────────────────────────┘     unavailable = no speech text
```

```ts
type TtsState = "idle" | "loading" | "playing" | "error" | "unavailable";
interface MessageTts {
  state: TtsState;
  hasSpeech: boolean;       // false → don't render the button
  ariaKey: "speakReply" | "stopReply" | "speakLoading" | "speakError";
  toggle: () => void;       // idle/error → start; loading/playing → stop
}
```

- `toggle()` while `idle`/`error` → start playback (from cache if present, else fetch).
- `toggle()` while `loading`/`playing` → stop: `AbortController.abort()` any in-flight fetches and
  stop the audio.
- **Single global player.** A small module-level controller (or React context) ensures only one
  message plays at a time: starting message B stops message A. Mirrors how a chat app behaves.

### 5.3 Plain-text extraction — `markdownToSpeechText`

A new util `vendor/nanobot/webui/src/lib/tts-text.ts`. Parse the **raw markdown**
(`message.content`) with the **already-bundled** remark stack — reuse the same plugins the renderer
uses so "what's spoken" matches "what's prose on screen":

- `unified()` + `remark-parse` + `remark-gfm` + `remark-math` (the latter two are direct deps;
  `unified`/`remark-parse` are transitive deps of `react-markdown` and importable from
  `node_modules`).
- Walk the resulting **mdast** and collect text per the rules below, then normalize whitespace and
  collapse blank runs.

**Extraction rules** (satisfies "plain text only; no code/chart/table/video"):

| mdast node | Action | Rationale |
|------------|--------|-----------|
| `text`, `emphasis`, `strong`, `delete` | **keep** text | prose |
| `paragraph` | keep, add sentence break after | prose |
| `heading` | keep heading text, add break | prose |
| `list` / `listItem` | keep item text; add a short pause between items | prose |
| `blockquote` | keep inner text | prose |
| `link` | keep the **link label**, drop the URL | reading a URL aloud is noise |
| `break` / soft breaks | → pause/space | — |
| `inlineCode` | **skip** | "do not say the code" |
| `code` (fenced block, incl. ```` ```visualizer ````) | **skip** | code **and** charts (visualizer fences render as charts) |
| `table` (+ rows/cells, via remark-gfm) | **skip entirely** | "do not say the table" |
| `inlineMath` / `math` (remark-math, `$$…$$`) | **skip** | not plain prose |
| `image` | **skip** | media |
| `html` (raw HTML, `<video>`, `<iframe>`, `<details>`, `<sub>`, `<sup>`, `<mark>`) | **skip** tags; keep readable inner text only where trivial, else skip | "video format" and other embeds |
| `thematicBreak` (`---`) | **skip** | separator |

Output: a single normalized string. If it is empty/whitespace → `hasSpeech = false`.

> The same logic could instead live server-side in the proxy (Python markdown strip), keyed by
> message id. We keep it **client-side** because (a) the frontend already owns the rendered AST and
> knows exactly what counts as prose, and (b) the auto-prefetch mode (§5.6) must produce speech the
> instant a reply finishes streaming, when the client has the content in memory but the server's
> persisted copy / id-mapping may lag. See §10 *Alternatives considered*.

### 5.4 Segmentation

Split the extracted text into ordered segments for the per-GET requests:

- Split on sentence boundaries: `。！？!?；;` and hard line breaks; keep the delimiter.
- Greedily pack sentences into a segment until adding the next would exceed
  `TTS_SEGMENT_CHARS` (default ~400 chars — comfortably under any URL limit even for CJK, which
  URL-encodes to ~9 bytes/char).
- A single oversized sentence is hard-split at the char budget.

Smaller segments → lower time-to-first-audio and shorter URLs; the trade-off is more requests.
~400 chars balances both.

### 5.5 Fetching & gapless playback

For each segment in order:

```
GET /api/tts?voice=<voice>&text=<encodeURIComponent(segment)>   (+ token)
  → Blob (audio/wav)
```

Playback options (pick per complexity budget):

- **MVP — sequential `<audio>` queue.** Create a blob URL per WAV, set it as `audio.src`, and on
  the `ended` event advance to the next segment's blob. Native, simplest; sentence-boundary gaps
  are natural for speech. Prefetch segment *N+1* while *N* plays.
- **Polish — Web Audio gapless.** Decode each WAV with
  `AudioContext.decodeAudioData` and schedule buffers back-to-back on one `AudioContext` for
  zero-gap playback. More code (scheduling, resume-on-gesture), nicer result.

Recommend shipping the `<audio>` queue first; Web Audio is a later enhancement. Either way, fetch
segments with a small look-ahead (e.g. 1–2 ahead) so the first sound starts after just the first
short segment, not the whole reply.

### 5.6 Caching & the two trigger modes (D1)

A module-level **LRU cache** keyed by `${messageId}::${voice}` holds the assembled audio for a
message (array of segment blobs, or decoded `AudioBuffer`s). Bound it (e.g. last ~20 messages) to
avoid unbounded memory from long sessions; evict oldest. Switching voice uses a new key (old audio
stays cached until evicted). Cache is in-memory only (not persisted).

- **On-demand mode (default).** On first speaker click: extract → segment → fetch → play, and store
  the blobs in the cache. Re-clicks replay from cache (no network). A reply nobody plays costs zero
  TTS.
- **Auto-prefetch mode.** When an assistant message transitions to "finished"
  (`role === "assistant" && !isStreaming` and non-empty — the same condition that reveals the
  copy/speaker buttons), kick off the extract→segment→fetch pipeline in the background and fill the
  cache, **without** auto-playing. The click then plays instantly. Guard rails:
  - Only prefetch the **latest** finished message (don't bulk-prefetch history on load).
  - Serialize/limit concurrent prefetches (one at a time) to avoid hammering the upstream.
  - Skip prefetch when `hasSpeech` is false.

The mode is read from the TTS settings (§6); changing it takes effect for subsequently finished
messages.

---

## 6. Settings (D3 + D1 toggle)

Add a **"Speech / 語音" group** to the existing Settings panel
(`vendor/nanobot/webui/src/components/settings/SettingsView.tsx`), persisted to `localStorage`
following the `useTheme.ts` pattern (`STORAGE_KEY = "nanobot-webui.theme"`):

| Setting | Control | localStorage key | Default |
|---------|---------|------------------|---------|
| Voice | dropdown (`TTS_VOICES`) | `nanobot-webui.tts-voice` | `"chris"` |
| Generate speech automatically when a reply completes | toggle (on = auto-prefetch, off = on-demand) | `nanobot-webui.tts-autoprefetch` | `false` (on-demand) |

Implement a small `useTtsSettings()` hook (mirror `useTheme.ts`: read on mount, write on change,
expose `{voice, setVoice, autoPrefetch, setAutoPrefetch}`). `useMessageTts` consumes it.

The voice list (`TTS_VOICES`) is shared in spirit with the backend allow-list (§4.3). Until the
real catalog is known it is just `["chris"]`; see §9.

---

## 7. Config & secrets plumbing

`TTS_API_KEY` must reach the **gateway** process (server-side only — never the browser).

1. **`.env.example`**:
   ```bash
   # --- Message TTS（WebUI 朗讀；只給 gateway，不進前端 bundle）---
   TTS_API_KEY=sk-...
   TTS_AUTO_PREFETCH=false   # WebUI default trigger mode (true = prefetch on reply completion)
   # 選填：覆寫端點 / 模型 / 預設語音
   # TTS_API_BASE=https://llm.andyjjrt.cc/v1
   # TTS_API_MODEL=DGX/Qwen3-TTS
   # TTS_DEFAULT_VOICE=chris  # also the WebUI voice-dropdown default
   ```
   `TTS_DEFAULT_VOICE` and `TTS_AUTO_PREFETCH` are not just server-side: the gateway ships them to
   the browser in the `/webui/bootstrap` JSON (`tts: {default_voice, auto_prefetch}`), and
   `useTtsSettings` uses them as the **default**. Precedence = per-browser localStorage override
   (set only when the user flips a Settings → Speech control) > `.env` default > built-in. The hook
   persists only on an explicit change (never on mount), so a later `.env` edit stays live for
   browsers that never toggled. `TTS_API_KEY`/`TTS_API_MODEL`/`TTS_API_BASE` stay server-side only.
2. **Host mode** — no code change: `scripts/load_env.sh` does `set -a` and sources `.env`, so
   `TTS_API_KEY` is auto-exported into the `nanobot gateway` process. (The DB MCP server does not
   need it.)
3. **Docker mode** — add to the `gateway` service `environment:` block in `docker-compose.yml`
   (next to `OPENAI_API_KEY`, `REELS_CF_*`):
   ```yaml
   TTS_API_KEY: ${TTS_API_KEY:-}                         # unset → speaker button returns 503
   TTS_API_MODEL: ${TTS_API_MODEL:-DGX/Qwen3-TTS}
   TTS_DEFAULT_VOICE: ${TTS_DEFAULT_VOICE:-chris}        # also the WebUI voice default
   TTS_AUTO_PREFETCH: ${TTS_AUTO_PREFETCH:-false}        # WebUI default trigger mode
   ```
   The `badminton-db` and `ingest` services do **not** get it.

No entry in `nanobot/config.json` is needed — the proxy reads `os.environ["TTS_API_KEY"]` directly
(it is not an MCP/provider secret resolved via `${VAR}`).

---

## 8. Build, patch & deploy

This touches **both** the vendored frontend (`vendor/nanobot/webui/`) and the vendored backend
(`vendor/nanobot/nanobot/channels/websocket.py`), so two patches are produced and the full image is
rebuilt.

1. **Edit** the vendored source directly:
   - `vendor/nanobot/nanobot/channels/websocket.py` — the `/api/tts` route + `_pcm_to_wav` helper.
   - `vendor/nanobot/webui/src/...` — button, hook, util, settings, i18n strings.
2. **Build the WebUI to verify** (per the repo's WebUI build notes): build the **vendored** webui
   directly — `cd vendor/nanobot/webui && bun run build` (it has `node_modules`; outputs to
   `vendor/nanobot/nanobot/web/dist`). Do **not** use the stale `scripts/build_webui.sh` clone at
   `/mnt/ssd1/howchien/nanobot-webui` for verification.
3. **Add the i18n keys** to every locale in `vendor/nanobot/webui/src/i18n/locales/*/common.json`
   (mirror how `message.copyReply` / `message.copiedReply` are defined): `message.speakReply`,
   `message.stopReply`, `message.speakLoading`, `message.speakError`, plus the Settings labels.
4. **Regenerate the patch files** from the vendored tree (recipe from the WebUI verification notes):
   `git diff --relative=vendor/nanobot <vendor-base-commit>^ -- <paths>` → write
   `patches/webui-tts.patch` (frontend) and `patches/webui-tts-proxy.patch` (backend). Keep each a
   clean `git diff` so it composes with the existing seven patches.
5. **Rebuild & redeploy** (Docker): `docker compose up -d --build`. The Dockerfile's hatch hook
   (`NANOBOT_FORCE_WEBUI_BUILD=1`) rebuilds the WebUI and bundles it into the wheel; the gateway
   serves the new dist and exposes `/api/tts`.
6. **Note:** editing `vendor/` triggers the slow full nanobot+WebUI image rebuild (unlike a
   config-only change). `uv tool upgrade nanobot-ai` would wipe a host-mode deployed dist — don't.

---

## 9. Open items

- **Voice catalog.** Only `"chris"` is documented. Before exposing a multi-option dropdown, confirm
  the upstream's supported voices (check for a `/v1/audio/voices` or models listing on
  `llm.andyjjrt.cc`, or ask the service owner). Until then `TTS_VOICES = {"chris"}` (dropdown with a
  single entry, default chris). The allow-list lives in both the proxy (§4.3) and the WebUI (§6);
  keep them in sync.
- **Upstream `wav`/`mp3` support.** If confirmed, the proxy can request that format and pass it
  through, dropping the PCM→WAV wrap (§4.3). Worth a one-line probe during implementation.
- **Language/voice match.** Replies are often Chinese (see `reply-language.patch` + `SOUL.md`).
  Qwen3-TTS is multilingual, so `chris` should handle CJK; verify audibly during testing.

---

## 10. Edge cases & alternatives

**Edge cases**

- **All-non-prose message** (only code/tables/charts) → `hasSpeech = false` → no speaker button.
- **Click while loading/playing** → stop: abort in-flight fetches (`AbortController`) and stop audio.
- **Start B while A plays** → single global player stops A first.
- **Upstream error / 401 / timeout** → proxy returns `502/401/503`; hook enters `error` state
  briefly (error icon/title), then back to `idle`. No partial-audio left playing.
- **Voice changed mid-cache** → new cache key; next play re-fetches with the new voice.
- **Autoplay policy** → the first audio always follows a user click (on-demand) or plays only after
  a click (auto-prefetch only *fetches*, never auto-sounds), so browser autoplay restrictions and
  `AudioContext` resume-on-gesture are satisfied.
- **Very long reply** → many segments; look-ahead fetching keeps time-to-first-audio low; the
  server caps each segment via `TTS_MAX_INPUT_CHARS`.

**Alternatives considered (and why not)**

- *Direct browser → TTS with key in bundle* — rejected (D2): leaks the key + CORS.
- *POST body for the full text* — impossible: the gateway's beside-WS HTTP server is GET-only (§2.1).
- *Server-side extraction keyed by message id* (`GET /api/tts?session=&message=`) — viable and keeps
  text off the URL, but duplicates the markdown→prose rules in Python and depends on the UI message
  id resolving to a persisted server copy, which is fragile exactly when auto-prefetch fires (right
  as streaming ends). Client-side extraction + chunked GET is more robust. Could revisit if URL
  length ever becomes a problem.
- *Stream audio over the existing WebSocket* — would touch the agent message bus/protocol and the
  client multiplexer; heavier and less isolated than an HTTP proxy route. Out of scope.

---

## 11. Security

- **Key isolation** — `TTS_API_KEY` only in the gateway env; never in the bundle, bootstrap
  response, or settings payload (which already masks keys).
- **Not an open relay** — `/api/tts` is gated by `_check_api_token` (same token the WS uses) and
  sits behind Cloudflare Access; only authenticated WebUI users can drive it.
- **Input bounds** — server rejects empty text, text over `TTS_MAX_INPUT_CHARS`, and voices outside
  the allow-list, limiting abuse/cost and avoiding passing arbitrary fields upstream.
- **No SSRF surface** — the base URL is a fixed constant (`TTS_API_BASE`), not user-controlled.
- **`Cache-Control: no-store`** on the audio response (the content is ephemeral; caching is the
  client's in-memory job).

---

## 12. File-change checklist

**Backend (patch `patches/webui-tts-proxy.patch`)**
- `vendor/nanobot/nanobot/channels/websocket.py` — `/api/tts` route in the api dispatch,
  `_handle_tts` (async, openai-SDK proxy + auth + validation), `_pcm_to_wav` helper, TTS_* constants.

**Frontend (patch `patches/webui-tts.patch`)**
- `vendor/nanobot/webui/src/components/MessageBubble.tsx` — speaker button after the copy button
  (footer row, ~line 171); `showSpeakButton`; wire `useMessageTts`.
- `vendor/nanobot/webui/src/hooks/useMessageTts.ts` — **new**: state machine, fetch, cache, player.
- `vendor/nanobot/webui/src/hooks/useTtsSettings.ts` — **new**: voice + auto-prefetch prefs
  (localStorage, mirrors `useTheme.ts`).
- `vendor/nanobot/webui/src/lib/tts-text.ts` — **new**: `markdownToSpeechText` (remark mdast walk)
  + segmentation.
- `vendor/nanobot/webui/src/components/settings/SettingsView.tsx` — Speech settings group.
- `vendor/nanobot/webui/src/i18n/locales/*/common.json` — `message.speakReply` / `stopReply` /
  `speakLoading` / `speakError` + Settings labels (all locales).

**Config / secrets (not patched — repo files)**
- `.env.example` — add `TTS_API_KEY` (+ optional overrides).
- `docker-compose.yml` — `TTS_API_KEY` in the `gateway` service `environment:`.
- (`scripts/load_env.sh` needs **no** change — `set -a` auto-exports it in host mode.)

**Docs**
- `docs/MESSAGE_TTS.md` — this document.
- `CLAUDE.md` — once shipped, add `webui-tts*.patch` to the patch list and note the `TTS_API_KEY`
  env requirement.
