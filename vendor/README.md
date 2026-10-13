# vendor/nanobot — third-party, vendored as a fork

`vendor/nanobot/` is a **fork** of **[HKUDS/nanobot](https://github.com/HKUDS/nanobot)
@ tag `v0.2.1`** (commit `f309982`), tracked in this repo with **git subtree**. The pristine
upstream tree was seeded as a real ancestor commit (tagged **`nanobot-base-v0.2.1`**) and our
changes sit on top as ordinary commits, so:

- **The source of truth is the live tree under `vendor/nanobot/` + git history.** There is no
  `patches/` directory any more — the authoritative record of "what we changed vs upstream" is

  ```bash
  git diff nanobot-base-v0.2.1..HEAD -- vendor/nanobot
  ```

- **Upgrading upstream is a merge, not a patch re-apply** (see *Updating* below).
- Edit the files directly. This is our fork now — do **not** treat it as untouchable upstream
  code, but **do** keep cosmetic/behavioural changes minimal and well-commented (our changes are
  marked with a `badmintonGPT fork` comment) so future upstream merges stay easy.

## Our changes vs upstream v0.2.1

Backend (Python):

- **project skill continuity** (`nanobot/agent/context.py`, `nanobot/agent/tools/filesystem.py`)
  — project chats retain the agent's `SOUL.md` and `USER.md` while using project-local
  `AGENTS.md`; `read_file` can read agent workspace skills when a project is selected.
  Write/edit tools remain restricted to the selected project. This keeps visualise and the
  badminton playbooks callable from the project groups.
- **accounts, quotas & per-user isolation** (opt-in `NANOBOT_ACCOUNTS=1`; new module
  `nanobot/accounts.py`, tests `tests/test_accounts.py` + `tests/channels/test_websocket_accounts.py`)
  — identity = the Cloudflare Access e-mail (`Cf-Access-Authenticated-User-Email`, or the verified
  `Cf-Access-Jwt-Assertion` when `CF_ACCESS_TEAM_DOMAIN`/`CF_ACCESS_AUD` are set). SQLite ledger
  `~/.nanobot/accounts.db`: session owners, per-call LLM usage, per-job MCP costs.
  `channels/websocket.py` requires an identity for bootstrap/API/WS, claims new chats for their
  creator and filters/404s every session route, attach and message by owner; adds
  `GET /api/usage`, `account` in bootstrap, 403 on `/api/settings*` and refusal of
  `/restart` `/model` `/dream*` `/pairing` for non-whitelisted accounts, and refuses turns once the
  quota is spent (`error` event `quota_exhausted`). Metering: `providers/base.py`
  `_safe_chat`/`_safe_chat_stream` (refuse when exhausted, record `usage` after) and
  `agent/tools/mcp.py` (charges any result carrying `{"job_id", "usage": {"cost_usd"}}` — the
  reels contract — once per job, monotonic). `openai_responses/parsing.py` now keeps
  `cached_tokens`. Isolation beyond the chat list: `agent/tools/filesystem.py` + `sandbox.py`
  (no `sessions/`, `memory/history.jsonl` or other users' `projects/<user>/`; shared config
  read-only), `webui/workspaces.py` (remote projects under `projects/<user>/`),
  `webui/sidebar_state.py` (per-user file), `agent/tools/cron.py` (own jobs only).
  `NANOBOT_DISABLE_SHARED_MEMORY=1` stops `Consolidator.archive` writing the shared
  `history.jsonl`, `context.py` injecting it (and the workspace-wide `memory/MEMORY.md`), and the stale `dream` cron job running
  (`cli/commands.py`). WebUI: `components/UsageView.tsx`, a sidebar balance button, restricted
  Settings (Appearance + Speech), account error banners. Ops: `python -m nanobot.accounts`.
  **Invite codes** (opt-in `NANOBOT_ACCOUNTS_INVITE_REQUIRED=1`): ledger table `invites` (shared
  codes, optional `max_uses`) + `users.activated_at`/`invite_*` columns, added by
  `Ledger._migrate`, which activates every account already there. Until a non-whitelisted
  account redeems a code, `quota_status` reports `invite_required`, `_reject_for_account` sends
  `error` `invite_required`, and `llm_call_refusal`/`mcp_call_refusal` refuse; `GET
  /api/invite/redeem?code=` redeems (wrong codes cool down, 429 + `Retry-After`). WebUI:
  `components/InviteGate.tsx` replaces the app in `App.tsx` while `account.invite_required`.
  CLI: `invite create|list|disable`, `activate`. Tests: `tests/invite-gate.test.tsx` + the two
  Python suites above.
- **link-only puzzle page** (`webui/public/puzzle.html`, `nanobot/puzzle.py`, routes in
  `channels/websocket.py` `_handle_puzzle`; tests `tests/test_puzzle.py` +
  `tests/channels/test_websocket_accounts.py`) — a static answer page nothing links to, behind
  Cloudflare Access like every path but `/welcome.html`. `GET /api/puzzle` (status) and
  `GET /api/puzzle/answer?answer=` check the answer server-side against `NANOBOT_PUZZLE_ANSWER`
  (NFKC, whitespace ignored), so it never reaches the browser. After the n-th wrong answer the
  account waits n/2 minutes (429 + `Retry-After` until then); per-e-mail state in
  `~/.nanobot/puzzle.db` survives restarts.
- **remote restricted projects** (`nanobot/webui/workspaces.py`, opt-in
  `NANOBOT_WEBUI_REMOTE_PROJECTS=1`) — lets the Cloudflare Access WebUI create and select
  one-level project directories under the persistent agent workspace's `projects/` directory.
  Remote clients cannot choose other paths or Full Access; local WebUI behavior is unchanged.
- **origin-aware MCP HTTP probe** (`nanobot/agent/tools/mcp.py` `_probe_http_url`) — a bare TCP
  probe can't tell a healthy remote MCP from a dead origin behind a reachable reverse proxy/tunnel:
  Cloudflare answers the TCP handshake and returns `502/503/504`, so nanobot would enter
  `streamable_http_client`, the MCP handshake would fail mid-stream, and the anyio task-group
  teardown crashed the whole gateway at startup. The fork issues a header-authenticated streaming
  GET and treats `>= 502` (incl. Cloudflare's 520-527), `401`/`403` (auth failure — e.g. a
  wrong/expired Cloudflare Access service token), or any connection/timeout error as "skip", so a
  down **or mis-credentialed** remote MCP no longer takes the gateway down — it is skipped and
  reconnected on a later turn.
- **self-healing MCP sessions** (`nanobot/agent/tools/mcp.py`: `_is_session_expired`, `_ServerLink`,
  `_SessionHealer`, `_reconnect_server`; `connect_mcp_servers(..., state=...)`) — a streamable-HTTP
  MCP server hands out a session id at `initialize` and answers **404 `Session not found`** to every
  later request carrying an id it no longer knows (it restarted, or GC'd an idle session); the SDK
  turns that into `McpError: Session terminated`. Upstream never recovers: the session object stays
  dead so every later call 404s the same way, and `connect_missing_servers` only connects servers
  *missing* from `state._mcp_stacks` — the dead connection is still in there. The server was
  therefore broken until the gateway restarted (observed 2026-09-04: `badminton-analyze` worked at
  06:55 and every call from 08:12 on failed with `MCP tool call failed: McpError`). The fork detects
  that specific error in the tool/resource/prompt wrappers, re-initializes just that server in place
  (unregister → close → `connect_mcp_servers` → re-register) and retries the call once. Reconnects
  are serialized per server by `_RECONNECT_LOCKS` and keyed on the wrapper's `AsyncExitStack`, so a
  batch of parallel calls onto the same dead session reconnects **once**, not once each; a failed
  reconnect returns the original error and is retried on the next call. Transport-level errors
  (`ClosedResourceError` & co.) still take the old retry-once-on-the-same-session path.
- **trust-proxy WebUI auth** (`nanobot/channels/websocket.py`, opt-in `NANOBOT_WEBUI_TRUST_PROXY=1`)
  — delegates WebUI/API auth to an external authenticating proxy. Upstream refuses to bind `0.0.0.0`
  without a `token`/`tokenIssueSecret` (`WebSocketConfig.wildcard_host_requires_auth`) **and** gates
  `/webui/bootstrap` to localhost when no secret is set, so a remote client (everything via
  cloudflared is non-localhost) is forced through a nanobot secret prompt. In the Docker deploy 8765
  is `expose`-only (only cloudflared → Cloudflare Access reaches it), so the env var lets the
  validator pass and lets bootstrap serve remote clients without a nanobot secret; auth is the
  edge's Access policy. Fails closed (unset → stock behavior).
- **reply-language** (`nanobot/agent/loop.py` + `nanobot/channels/websocket.py`, with
  `webui/src/lib/{types,nanobot-client}.ts`) — the agent replies in the WebUI language picker's
  language: the WebUI sends a `locale` field on each outbound message, the channel stores it in the
  inbound `metadata`, and `loop.py` maps it to a language name passed as a per-turn line into the
  existing `[Runtime Context]` block (`build_messages(current_runtime_lines=…)`). Paired with the
  `nanobot/workspace/SOUL.md` rule that honors the hint. The same locale also drives MCP tools:
  `nanobot/agent/tools/mcp.py` (`_fill_language_from_locale`, called at the top of
  `MCPToolWrapper.execute`) defaults a tool's `language` argument from
  `current_request_context().metadata["locale"]` when the model omits it — only for tools whose
  input schema declares a `language` property (today: badminton-reels `generate_reel`), mapped onto
  the schema's enum as exact match → same base language (`zh-CN` → `zh-TW`) → `en` → leave unset
  (server default). An explicit value from the model is never overridden.
- **`/api/tts` proxy** (`nanobot/channels/websocket.py`) — a GET-only route that proxies the WebUI
  speaker button's request to the upstream Qwen3-TTS with `TTS_API_KEY` injected server-side (openai
  SDK, PCM→WAV). See `../docs/MESSAGE_TTS.md`.
- **resolve `${NANOBOT_MODEL}` in Settings** (`nanobot/webui/settings_api.py`) — gives `model` the
  same `${VAR}` resolution the panel already applies to `api_base`/`api_key`, and avoids clobbering
  the `${NANOBOT_MODEL}` ref when the WebUI echoes the resolved value back on save.

Frontend (WebUI, `vendor/nanobot/webui/`):

- **video playback recovery** — `AttachmentTile.tsx` associates failure with the source URL,
  offers retry/open-original controls, and accepts optional `MediaPlaybackProvider` display copies
  for browser codec compatibility. The evaluation site supplies this context; stored replies and
  original attachment URLs are unchanged. Regression tests live in `human-evaluation/web/`.

- **tool-progress bar** — `webui/src/components/ToolProgress.tsx` + a hook in
  `thread/AgentActivityCluster.tsx`; a live progress bar for any tool result with numeric
  `stage`+`total_stages`.
- **badmintonGPT branding** — brand assets under `webui/public/brand/`, logo refs in `Sidebar.tsx` /
  `settings/SettingsView.tsx`, `index.html` title/favicon, and the user-visible brand strings +
  badminton empty-state greetings across the nine `webui/src/i18n/locales/*/common.json` (the literal
  `` `nanobot gateway` `` command string is preserved). Skin-only.
- **public welcome page** — `webui/public/welcome.html` (self-contained bilingual landing page,
  shares the WebUI's `nanobot.locale` key; the sidebar's `brand/lockup-horizontal{,-dark}.svg` +
  favicon inlined as data URIs, kept byte-identical by `src/tests/welcome-page.test.ts`) +
  `channels/websocket.py` `_serve_static` now sends `Cache-Control: no-cache` for every `.html`
  (was: only `index.html`; anything else got `immutable`, so welcome-page edits would never reach
  browsers). Reached via a Cloudflare Redirect Rule + an Access bypass on that path — see
  `docs/DEPLOY.md` step 1.4.
- **badminton rally thinking animation** — `webui/src/components/BadmintonRallyThinking.tsx` (a
  decorative rally driven by a single rAF engine; `prefers-reduced-motion` renders a static scene),
  its `brt-*` rules in `globals.css`, mounted in `thread/AgentActivityCluster.tsx` gated on
  `isTurnStreaming`. Skin-only.
- **home example questions** — `thread/ExamplePrompts.tsx`: one example per feature (data, reel,
  chart, analysis, rally search; the questions `public/welcome.html` demonstrates), one per row
  below the composer of an empty chat, rendered from `ThreadShell.tsx`. The list scrolls on its
  own and its height follows the screen height. Picking one only fills the input via
  `ThreadComposer`'s `prefill` prop (ignored at mount, so it never comes back after sending); the
  user still presses send. `ThreadViewport.tsx` puts the empty-chat greeting in flow above the
  composer (upstream: absolutely positioned), so the taller block scrolls instead of pushing the
  greeting off a short phone screen. Strings in `thread.empty.examples` (en, zh-TW). Test:
  `tests/example-prompts.test.tsx`.
- **animated boot splash** — `webui/index.html` lock-on mark with a play-once gate (intro played
  once AND app mounted), `prefers-reduced-motion` static fallback. Skin-only.
- **visualizer fences** — renders ```` ```visualizer ```` fences (the `skills/visualise` output) as
  live inline iframes (`VisualWidget.tsx`, `lib/visualizer-events.ts`, routed in
  `MarkdownTextRenderer.tsx` gated on `!streaming`, with a `sendPrompt` bridge in `ThreadShell.tsx`).
  **Deliberately NOT security-hardened** (project decision): `sandbox="allow-scripts
  allow-same-origin"`, no CSP. On reload, `nanobot/webui/transcript.py`
  `demote_interrupted_assistant` keeps a text segment holding a visualizer fence as an answer
  even when tool calls follow it (e.g. `complete_goal`); upstream folds such text into the
  reasoning, which the live view never does, so charts used to jump into the thinking section.
- **court theme** — the「淡綠場館 / Ball-in」home redesign: pale-green court tokens in `globals.css`,
  `--brand` tokens (+ `brand` colour in `tailwind.config.js`), court-line utilities + Ball-in
  keyframes, `thread/CourtBackdrop.tsx`, greened composer/accents, `Noto Sans TC`. Skin-only.
- **message TTS speaker button** — `MessageBubble.tsx` speaker button, `hooks/useMessageTts.ts` +
  `hooks/useTtsSettings.ts`, `lib/tts-text.ts`, a Speech group in `settings/SettingsView.tsx`. Pairs
  with the `/api/tts` proxy above. See `../docs/MESSAGE_TTS.md`.

Fork-only build hygiene (no upstream counterpart):

- **`tailwind.config.js` excludes `webui/src/tests/**`** from the content glob — full-tree vendoring
  ships upstream's WebUI tests, and the default `./src/**/*.{ts,tsx}` glob would let test-file class
  names drive production CSS. Excluding them keeps the built `dist` byte-identical to the deployed
  build. Tests still run; the glob only affects CSS generation.
- **`webui/bun.lock`** is kept consistent with `package.json` (the subtree re-seed brought upstream's
  stale lockfile; ours is the one we build with). The Docker image builds the WebUI with **npm**
  (`package-lock.json`, byte-identical to upstream); `bun.lock` is for local `bun` dev only.

## How it builds

The gateway image (`../Dockerfile`) builds this fork hermetically — no clone of an upstream tag, no
`nanobot-ai` PyPI pin, no post-install dist overlay. `uv pip install vendor/nanobot` with
`NANOBOT_FORCE_WEBUI_BUILD=1` rebuilds `nanobot/web/dist` from this source via the hatch hook
(`hatch_build.py`, which uses `bun` if present else `npm`).

License: nanobot is **MIT** — its `LICENSE` and `THIRD_PARTY_NOTICES.md` are retained here.

## Vendoring scope

The **full** upstream tree is vendored (no exclusions). This costs a few MB in git and **nothing in
the image** (the wheel only packages `nanobot/**` + `bridge/` + the rebuilt `nanobot/web/dist/**`).
Full-tree vendoring is what keeps `git subtree pull` clean — a pruned tree would make every upstream
merge re-delete the excluded paths. (The full tree includes upstream's own `CLAUDE.md`/`AGENTS.md`/
`.agent/` agent-guide files, scoped to this subdir; the repo-root `CLAUDE.md` governs the project.)
`node_modules/` and the built `dist/` are git-ignored and never committed.

## Updating to a new upstream nanobot

Upstream bumps happen on a branch, gated by CI (`.github/workflows/` builds the fork), and are merged
to the deploy branch only when green.

```bash
git fetch nanobot-upstream                         # remote: https://github.com/HKUDS/nanobot
git checkout -b chore/nanobot-<new-tag>
git subtree pull --prefix=vendor/nanobot --squash nanobot-upstream <new-tag>
# → resolve any merge conflicts ONCE (3-way; far easier than re-applying a patch stack)
git tag nanobot-base-<new-tag>                      # new base marker for diffing our delta
```

Then verify and bump version comments:

```bash
docker build -f Dockerfile .                        # hermetic build incl. the WebUI dist (hatch hook)
git diff nanobot-base-<new-tag>..HEAD -- vendor/nanobot   # sanity-check our delta survived the merge
```

Bump the image tag in `../docker-compose.yml` + `../Dockerfile` comments, then run the verification
in `../docs/DEPLOY.md`.

**Rollback.** If a merge resolves badly:

- Not yet committed: `git merge --abort` (or `git subtree`'s merge — `git reset --hard`).
- Already committed: `git revert -m 1 <merge-commit>` and rebuild.
- Nuclear: the pre-conversion state is preserved at tag **`pre-fork-refactor`**.
