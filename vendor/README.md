# vendor/nanobot — third-party, vendored

`vendor/nanobot/` is a vendored copy of **[HKUDS/nanobot](https://github.com/HKUDS/nanobot)
@ tag `v0.2.1`** (commit `f309982`), **with this repo's patches applied**:

- `patches/webui-progress.patch` — adds `webui/src/components/ToolProgress.tsx` and a hook in
  `webui/src/components/thread/AgentActivityCluster.tsx` (the tool-progress bar).
- `patches/mcp-probe-origin-aware.patch` — makes `nanobot/agent/tools/mcp.py`'s `_probe_http_url`
  an origin-aware HTTP check instead of a bare TCP connect. A TCP probe can't tell a healthy
  remote MCP from a dead origin behind a reachable reverse proxy/tunnel: Cloudflare answers the
  TCP handshake and returns `502/503/504`, so nanobot would enter `streamable_http_client`, the
  MCP handshake would fail mid-stream, and the anyio task-group teardown crashed the whole gateway
  at startup. The patched probe issues a header-authenticated streaming GET and treats `>= 502`
  (incl. Cloudflare's 520-527), `401`/`403` (auth failure — e.g. a wrong/expired Cloudflare Access
  service token, which would otherwise fail the handshake and crash the same way), or any
  connection/timeout error as "skip", so a down **or mis-credentialed** remote MCP no longer takes
  the gateway down — it is skipped and reconnected on a later turn once it recovers / is fixed.
- `patches/webui-trust-proxy-auth.patch` — adds an opt-in (`NANOBOT_WEBUI_TRUST_PROXY=1`) to
  `nanobot/channels/websocket.py` that delegates WebUI auth to an external authenticating proxy.
  This nanobot version refuses to bind `0.0.0.0` without a `token`/`tokenIssueSecret`
  (`WebSocketConfig.wildcard_host_requires_auth`) **and** gates `/webui/bootstrap` to localhost when
  no secret is set — so a remote client (everything via cloudflared is non-localhost) is forced
  through a nanobot secret prompt. In the Docker deploy 8765 is `expose`-only (only cloudflared →
  Cloudflare Access can reach it), so the env var lets the validator pass and lets bootstrap serve
  remote clients without a nanobot secret; auth is the edge's Access policy. Fails closed (unset → stock
  behavior). The `_is_localhost`-gated WebUI admin controls are intentionally left as-is.
- `patches/webui-branding.patch` — rebrands the WebUI to **badmintonGPT**: adds four assets from the
  `../images/logo/` brand kit — `webui/public/brand/mark-green.svg` (settings icon + apple-touch
  icon + collapsed-sidebar logo), `mark-small-noframe-green.svg` (favicon),
  `lockup-horizontal.svg` / `lockup-horizontal-dark.svg` (expanded-sidebar wordmark, swapped via
  Tailwind `dark:` classes) — points the logo refs in
  `webui/src/components/Sidebar.tsx` and `webui/src/components/settings/SettingsView.tsx` at them, sets
  the `webui/index.html` title/favicon/boot-splash, the hardcoded settings brand label, and the
  user-visible "nanobot" brand strings + badminton-themed empty-state greetings across the nine
  `webui/src/i18n/locales/*/common.json` (the literal `` `nanobot gateway` `` command string is
  deliberately preserved). Skin-only; no behavior change.
- `patches/reply-language.patch` — makes the agent reply in the language selected in the WebUI
  language picker: the WebUI sends a `locale` field on each outbound message
  (`webui/src/lib/types.ts`, `webui/src/lib/nanobot-client.ts`), `nanobot/channels/websocket.py`
  stores it in the inbound `metadata`, and `nanobot/agent/loop.py` maps it to a language name and
  passes it as a per-turn "User UI language" line into the existing `[Runtime Context]` block
  (`build_messages(current_runtime_lines=…)`). Paired with this repo's `nanobot/workspace/SOUL.md`
  rule that honors that hint.
- `patches/webui-thinking-animation.patch` — adds `webui/src/components/BadmintonRallyThinking.tsx`
  (a decorative badminton rally spanning the **full conversation width**: two chibi players exchange
  shots picked at random from a shot table — clear/drop/smash/drive/lift/net, chained by realistic
  contact-height rules — driven by a single rAF engine writing transforms through refs, with an
  amber glowing shuttle trail, pose + facial-expression switching per shot, one-shot comic effects
  via WAAPI (impact star, smash speed lines, sweat drop), and an intensity ramp over ~35s of waiting
  that speeds the rally up, raises the smash rate and hardens the expressions), its `brt-*`
  pose/face cross-fade rules in `webui/src/globals.css` (`prefers-reduced-motion` renders a static
  scene, no engine), and mounts it in `webui/src/components/thread/AgentActivityCluster.tsx` below
  the cluster, gated on `isTurnStreaming` so it shows under the "thinking" process while a turn is
  live. Skin-only; no behavior change.
- `patches/webui-boot-splash.patch` — replaces the `webui/index.html` boot-splash pulsing dot with
  the animated lock-on mark from `../images/animation/logo-animation.html` (speed lines fly in →
  shuttle lands → lock frame snaps shut → idle breathe loop; brand green `#3fc168`, the localized
  `data-boot-copy` line kept beneath). The splash is a fixed overlay **above** `#root` with a
  play-once gate: it fades out only after BOTH the intro has played once (the lock frame's
  `boot-snap` `animationend`, ~2.2s, with a 2.8s safety timer) AND the app has mounted into
  `#root` (MutationObserver) — so a fast React mount can no longer cut the intro off, and a slow
  load keeps the breathe loop until ready. `prefers-reduced-motion` renders the static mark and
  skips the forced wait. Also fixes the branding patch's boot-copy localization (the head i18n
  script ran before `<body>` was parsed, so the localized "Loading…" line never applied; the swap
  is now deferred to DOMContentLoaded). Applies on top of `webui-branding.patch`'s index.html
  hunks. Splash-only; no app behavior change.
- `patches/webui-visualizer.patch` — renders ```` ```visualizer ```` fences (the
  `skills/visualise` playbook's output) as live inline visuals instead of code blocks. Adds
  `webui/src/components/VisualWidget.tsx` (iframe with the skill's theme CSS + SVG utility
  classes injected ahead of the model HTML, auto-height via ResizeObserver, theme-aware) and
  `webui/src/lib/visualizer-events.ts`; routes the fence in `MarkdownTextRenderer.tsx`'s
  `code`/`pre` handlers gated on `!streaming` — while streaming, a skeleton placeholder card
  (`VisualPlaceholder`, i18n key `visualizer.generating`) stands in so the raw HTML/JS is never
  shown and partial HTML never executes; threads `streaming` through `MarkdownText.tsx`, and adds a
  `sendPrompt(text)` bridge — iframe code calls `window.sendPrompt(...)`, a CustomEvent
  listener in `ThreadShell.tsx` posts it as a user message. **Deliberately NOT
  security-hardened** (project decision): `sandbox="allow-scripts allow-same-origin"`, no CSP,
  any CDN loads — fence content effectively runs with full access to the WebUI origin.

It is committed so the gateway image (`../Dockerfile`) builds the **patched** nanobot
hermetically — no clone of an upstream tag, no `nanobot-ai` PyPI pin, no post-install dist
overlay (the failure modes the host scripts `../scripts/build_webui.sh` /
`../scripts/deploy_webui.sh` work around). `pip install vendor/nanobot` with
`NANOBOT_FORCE_WEBUI_BUILD=1` rebuilds `nanobot/web/dist` from this source via the hatch hook.

License: nanobot is **MIT** — its `LICENSE` and `THIRD_PARTY_NOTICES.md` are retained in this
directory. This is third-party code; do not hand-edit it as if it were ours.

## What was excluded (regenerable / not needed to build)

`.git/`, all `node_modules/`, the prebuilt `nanobot/web/dist/` (rebuilt at image build),
and `tests/`, `images/`, `case/`, `docs/`, `.github/`, `.agent/`.

## Updating to a new upstream nanobot

1. `git clone --branch <new-tag> https://github.com/HKUDS/nanobot /tmp/nanobot`
2. Rebase all patches onto it (`cd /tmp/nanobot && git apply --3way ../patches/webui-progress.patch && git apply --3way ../patches/mcp-probe-origin-aware.patch && git apply --3way ../patches/webui-trust-proxy-auth.patch && git apply --3way ../patches/webui-branding.patch && git apply --3way ../patches/reply-language.patch && git apply --3way ../patches/webui-thinking-animation.patch && git apply --3way ../patches/webui-boot-splash.patch && git apply --3way ../patches/webui-visualizer.patch`), resolving any conflicts; re-export each patch.
3. Re-vendor with the same exclusions (see `git log` for the `rsync` invocation), bump the tag/commit above, and bump the image tag in `../docker-compose.yml` + `../Dockerfile` comments.
4. Rebuild and run the verification in `../DEPLOY.md`.
