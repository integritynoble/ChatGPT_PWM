# Session history

A running log of working sessions on **chatgpt-pwm** (the ChatGPT experience for the
PWM exchange — CLI + web replica). Newest entries first. Modeled on the sibling
`claude-pwm` reference repo.

---

## Deploy targets (IMPORTANT — there are TWO live web backends)

The web UI (`chatgpt-pwm/web/index.html`) is served by **two independent backends**
behind nginx. A deploy must copy `index.html` to **both** live dirs or the two public
domains will drift out of sync (this bit us on 2026-06-29).

| Public domain | nginx → port | Live dir (deploy here) | Backend |
|---|---|---|---|
| `chatgpt.comparegpt.io` | `127.0.0.1:8200` | `/home/spiritai/pwm/chatgpt-web` | `chatgpt-pwm.service` (systemd, `WorkingDirectory=…/chatgpt-web`) |
| `chatgpt.platformai.org` | `127.0.0.1:8201` | `/home/spiritai/pwm/chatgpt-web-dev` | standalone `uvicorn main:app … --port 8201` (cwd `…/chatgpt-web-dev`) |

Canonical git source is `chatgpt-pwm/web/`. To deploy a UI change to both domains:

```bash
cp chatgpt-pwm/web/index.html /home/spiritai/pwm/chatgpt-web/index.html       # → chatgpt.comparegpt.io
cp chatgpt-pwm/web/index.html /home/spiritai/pwm/chatgpt-web-dev/index.html   # → chatgpt.platformai.org
```

No restart needed for `index.html` changes — `main.py` re-reads the file on every
`GET /`. **Backend** (`main.py` / `*.py`) changes still need a restart:
`systemctl restart chatgpt-pwm` for the 8200 backend; the 8201 uvicorn must be
restarted by its own process manager. nginx for both domains sets `proxy_buffering off`
/ `proxy_cache off` (SSE-friendly), so there's no edge cache to bust.

---

## 2026-07-03 — Persistent file library (upload once, reuse in any chat)

**Request:** "Please build the persistent file library next."

**Server-side** (consistent with sync/groups/tasks/shares): a `files` table in the
shared DB keyed by `sha256(key)` — text files store their extracted text, images a
data URL. `POST /api/files {name,kind,content}` (100-file / 8 MB-per-file / 60 MB-per-
user caps, 400 empty, 401 no key), `GET /api/files` (metadata only), `GET
/api/files/{id}` (full content), `DELETE` (owner-checked 403). Cross-device by
construction.

**Frontend:** new **"Files"** sidebar item + view — Upload button / drop-zone, a list
of stored files (type icon, size, date) with **Add to chat** and Delete. Uploads reuse
the existing attachment extractor (`_extractPdf`/`_extractDocx`/`_readText`/
`_readDataURL`) then POST. **"Add from library"** row in the composer **+** menu opens
a picker overlay; choosing a file fetches its content and pushes it into `attachments[]`
exactly like a fresh upload — so it flows through the normal `sendMsgs` path (text →
`[File: name]\n…`, image → `image_url`). Attaching from any view switches to chat
first; guarded against group chats.

**Verified:** backend curl (upload text+image / list / fetch / 400 empty / 401 no key
/ 403 foreign delete / delete). Headless **18/18** against the real backend — Files
view, upload via input, **server-side persistence across reload**, Add-to-chat →
composer chip carrying real content, + menu picker → attach, image round-trip (kind
image → image chip), delete (verified via server state; the DOM-count assertion was
flaky under the async re-render, so it now checks `/api/files`). All regressions green
— **218 checks** across 12 suites (files 18, groups 18, tasks 22, connectors 22, ci
19, sync 11, share 22, canvas 33, voice 20, gpts 16, archive 15, +no-sora). Live:
`/api/files` 401-gated on both domains, UI markers served.

**Parity note:** with the file library done, the earlier audit's remaining gap was
40-file Projects; PWM Projects group chats (not file uploads), so that specific ChatGPT
sub-feature (per-project uploaded files) is the only outstanding item.

---

## 2026-07-03 — Group chats (server-side shared conversations, up to 20)

**Request:** "Please build group chats next."

**Architecture:** unlike personal chats (client-side + sync), a group is one
**canonical server-side conversation** in the shared DB — the sync store made this the
natural foundation. Members are PWM users (`sha256(key)`); the group holds an invite
token, an ordered `group_msgs` log (monotonic `seq`), and an `ai_busy_until` claim
lock. Everyone **polls** `GET …/messages?after=<seq>` (2.5 s) — no per-user fan-out,
no websockets needed.

**Backend** (`web/main.py`, 3 tables `groups`/`group_members`/`group_msgs`):
`POST/GET /api/groups`, `GET /api/group/{id}`, public `GET /api/group-invite/{token}`
(pre-join preview), `POST /api/group-join/{token}` (idempotent; 20-member cap → 409;
posts a "X joined" system msg), `POST /api/group/{id}/leave` (last member out deletes
the group + its messages), `GET/POST …/messages`, and SPA-served `/g/{token}`. **AI
participation:** when a message matches `@?(chatgpt|gpt|ai)`, the sender's backend
does an atomic `UPDATE groups SET ai_busy_until=… WHERE id=? AND (busy IS NULL OR
busy<now)` — only the winner (across both backends/all workers) generates, streaming
the last 40 messages (each user line prefixed with its author name) through the
subscription and appending one `assistant` message, billed to the summoner's key;
the lock clears on completion or error. All member-gated (403 for non-members).

**Frontend** (`web/index.html`): **"New group chat"** sidebar item (name + display
name prompts → creates → copies the invite link). A **Group chats** section pins above
personal chats (unread dot when `last_seq > seen`). Group view: header with member
list + Invite/Leave, own messages right-aligned bubbles, others' name-labelled,
ChatGPT's replies as markdown, join/leave system lines, a "ChatGPT is typing…"
indicator (from the server's busy flag), composer placeholder "mention @ChatGPT to
bring the AI in". `onSend` routes to the group when one is open; the poll uses an
**AbortController** so leaving cancels any in-flight request (fixed a post-leave 403
console error). `/g/<token>` renders a join screen (title + members + name field).
Groups refresh on init, tab focus, and a 60 s heartbeat; never touched by the personal
sync/`persist` path.

**Verified:** backend curl flow (create/invite/join/send/poll/summon→real "391"/403/
list/leave) + **two-browser headless 18/18** — Alice creates, Bob joins via link, msgs
flow both ways with author labels, `@ChatGPT` returns "42" to both, unread dot after
navigating away, Bob leaves → Alice sees "left" system msg, zero console errors. All
regressions green — **200 checks** across 11 suites (groups 18, tasks 22, connectors
22, ci 19, sync 11, share 22, canvas 33, voice 20, gpts 16, archive 15, +no-sora; the
static/proxy stubs all gained a `/api/groups` responder). Live on both domains:
`/api/groups` 401-gated, `/g/<token>` 200, bad invite 404, UI markers served.

---

## 2026-07-03 — Scheduled tasks + time-aware memory (+ invalid-key reminder)

**Request:** "Please build scheduled tasks and time-aware memory next." Mid-session
addition: when the PWM key is invalid, point the user at token.comparegpt.io directly.

**Scheduled tasks** (ChatGPT Tasks):
- **Backend** (`web/main.py`): `tasks` table in the shared sync DB (stores the raw PWM
  key so runs can be balance-checked + billed like interactive turns). CRUD:
  `POST/GET /api/tasks`, `PATCH` (pause/resume, resume recomputes next_run),
  `DELETE` — all key-gated, owner-checked, 10-task cap, once-in-the-past → 400.
  `_task_next_run()` handles once/daily/weekly with a client tz offset (unit-tested:
  past/future once, tz+8 day rollover, weekly weekday, same-day later time).
  **Scheduler**: every uvicorn worker (both backends) runs a tick loop
  (`CHATGPT_TASK_TICK`, default 30 s) over the shared DB; an atomic
  `UPDATE … WHERE next_run<=now` claim guarantees each due task fires exactly once
  across all workers. Runs pull the user's **memories + custom instructions from the
  sync store's kv items**, stream through the subscription, then **append the result
  to a "⏰ <title>" conversation written into the user's sync items** — so it appears
  in the sidebar on the next sync pull, on any device. Invalid key/balance at run
  time → task auto-pauses with an explanatory message. Failures append "⚠️ Task run
  failed" instead of vanishing.
- **Frontend**: `systemContext()` teaches a `[[task]]{title,prompt,when}[[/task]]`
  marker (once `at_local` / daily / weekly, local time, with "right now it is …" so
  the model can compute dates); handled by the same tool loop (hidden markers, "Task"
  block with ✅ + human schedule, feed-back + continuation). **Settings → "Scheduled
  tasks"** manager: list with schedule + next-run, Pause/Resume, delete. `applySync`
  toasts "⏰ <title> ran" for task convos updated in the last 10 min (fresh-run guard
  so a new device's first pull doesn't toast history).

**Time-aware memory:** `memoryBlock()` now states today's date, stamps every fact
with its saved date (`[saved 2026-07-03] …`), and instructs the model to interpret
facts relative to when they were saved — past-tense for elapsed plans, no stale
ages/roles as current. Server-side task runs get the same memories (dates omitted
there; list only).

**Invalid-key reminder:** the Settings balance line and the account menu now render
"Invalid PWM key." with a direct link — *Get a valid token at token.comparegpt.io* —
and chat-stream 401/402 toasts append the same pointer.

**Verified:** backend e2e with a 2 s tick — real task created, claimed once, ran
through the live subscription ("TASK-RAN-OK"), landed in the sync store as
`⏰ Daily hello` (roles user/assistant); 401/400/limit paths. Headless 22/22 (helpers,
time-aware memoryBlock, marker→real POST→block→continuation, settings
list/pause/resume/delete, both invalid-key reminder links, task-convo pull + run
toast). All suites green — **180 checks** (tasks 22, connectors 22 — its stub gained
`/api/tasks`, ci 19, sync 11, share 22, canvas 33, voice 20, gpts 16, archive 15 —
its stub hardened, which surfaced it was quietly at 14/15 since the settings modal
gained async fetches). Live: `/api/tasks` 401-gated on both domains, UI markers
served, schedulers running in both backends.

---

## 2026-07-03 — Sora REMOVED (parity correction)

**Request:** "I think there is no sora in ChatGPT… please check it. If there is no
sora, please remove the sora in ChatGPT of PWM."

**Checked and confirmed:** OpenAI discontinued Sora inside ChatGPT (announced
March 2026; the Sora web/app experience inside ChatGPT ended April 26, 2026) —
Sora 2 lives only at the separate **sora.com**. The real ChatGPT sidebar in July
2026 is: New chat · Search chats · Library · GPTs · Projects — **no Sora**. So the
Sora surface built earlier today (entry below) was parity-wrong and has been removed.

**Removed:** sidebar nav item, `FEATURES.sora`, the `showView` route, the whole Sora
JS module (`renderSora`/`soraGenerate`/`pollSora`/`videoSave|All|Delete`/job
persistence), Sora CSS, the init resume line, and the entire backend
`/api/video` section (both engines). `test_sora.py` retired. **Kept:** the
`cg_library` IndexedDB at **v2 with the `videos` store** — IndexedDB versions can't
be downgraded for browsers that already upgraded, so the (empty, invisible) store
stays. The full implementation remains in git history at `4f00568` if ever wanted.

**Verified:** JS/py syntax OK; headless — sidebar is exactly New chat/Search
chats/Library/GPTs/Projects, all remaining views cycle, zero console errors. All
regressions green (157 checks: gpts 16, archive 14, canvas 33, voice 20, sync 11,
share 22, ci 19, connectors 22). Live on both domains: zero "sora" strings in the
served UI, `/api/video` → 404, chat gate intact, both backends healthy.

---

## 2026-07-03 — Sora video generation (/api/video, real videos from the Sora view)

**Request:** "Please build Sora video generation next" — the final parity item.

**Reality check first:** no GPU (`nvidia-smi` absent), no `OPENAI_API_KEY` anywhere
(`~/.codex/auth.json` has OAuth tokens only), subscription backend is chat+image only.
So `/api/video` has **two engines**:
- **`sora-api`** — the official OpenAI video API (`/v1/videos`, sora-2: create → poll
  → download), used automatically iff `SORA_API_KEY`/`OPENAI_API_KEY` is set. Written
  and wired but dormant on this host (no key).
- **`frames` (active)** — generates 2–5 keyframes through the **subscription's
  image_generation tool** (per-frame shot-progression prompts: establishing → closer →
  detail → concluding; consistent-style instruction), then assembles a real MP4 with
  **ffmpeg**: per-frame Ken Burns zoompan (alternating in/out, 3 s @ 24 fps) +
  0.6 s xfade crossfades; sizes 16:9→1280×720, 9:16→720×1280, 1:1→960×960. PWM
  billing: frame-generation usage tokens accumulated and charged once per job.

**Job model** (needed because 8200 runs 2 uvicorn workers): file-backed jobs under
`~/pwm/chatgpt-sync/video-jobs/<id>/` (`state.json` + `out.mp4`) so ANY worker/backend
serves polls; jobs GC'd after 24 h at creation time. `POST /api/video {prompt, aspect,
frames}` → `{id}` (PWM-gated; 400 empty prompt; 503 if no ffmpeg and no key);
`GET /api/video/{id}` → state (id regex-validated); `GET /api/video/{id}/file` → MP4.

**Frontend:** the Sora sidebar view is now real — prompt textarea, aspect (16:9/9:16/
1:1) + length (~7s/~10s/~12s = 3/4/5 frames) selects, Generate; progress card polls
every 2.5 s (status detail + progress bar; resumes after reload via `cg_video_job`,
incl. from init on any view); completed videos are fetched as blobs into **IndexedDB**
(`cg_library` DB bumped to **v2** with a `videos` store) and shown in a gallery grid —
`<video controls loop muted>`, caption, Download, Delete. Failure shows the error card.

**Verified:** real end-to-end backend run — 2 frames generated through the live
subscription + assembled: 5.4 s, 848 KB MP4 (frame inspected: high-quality balloon-
over-mountains render; motion recipe validated separately with ffmpeg test sources).
Headless UI 14/14 against a stubbed `/api/video` serving the REAL generated MP4
(composer, job store, progress card w/ detail, completion → IndexedDB → gallery,
playable duration ≈5.4 s, reload persistence, delete, zero console errors). All
regressions green — **171 checks** across 9 suites. Live: `/api/video` 401-gated on
both domains, Sora UI markers served. (Test-server note: backgrounded uvicorns die
with their shell here — run server+suite in ONE Bash invocation, or setsid dies too.)

**With this, the ChatGPT parity list is fully closed** — every sidebar surface and
tool is a real, working feature. Drop an `OPENAI_API_KEY` into the service envs to
upgrade Sora from the frames engine to true sora-2 generation with zero code changes.

---

## 2026-07-03 — Connectors (GitHub + Finances via /api/connector)

**Request:** "Please build connectors next." Previously descoped over per-service
OAuth; shipped the honest middle path: a server-side connector proxy for services
that work **token-light** — GitHub (public data unauthenticated; optional user PAT
unlocks code search / private repos) and Finances (Yahoo's public chart API — the
old Stooq CSV endpoint is dead, checked). Tokens are passed per-request from the
browser and never stored server-side (and explicitly never synced).

**Backend** (`web/main.py`): **`POST /api/connector`** `{service, action, params,
token?}` → `{ok, result | error}` — PWM-key-gated like chat; httpx, 15 s timeout;
API errors surface as readable `{ok:false,error}` (never 5xx).
- **github**: `search_repos{q}` (top 5), `repo_info{repo}`, `read_file{repo,path,ref?}`
  (dirs list entries; files capped 50 KB), `list_issues{repo,state?}` (top 10, PR flag),
  `search_code{q}` (requires token → friendly error otherwise).
- **finance**: `quote{symbol}`, `history{symbol, range?}` (daily closes, ≤120 rows).

**Frontend** (`web/index.html`) — same auto-run loop as code interpreter:
- **+ menu rows "GitHub" and "Finances"** with checkmarks — global per-browser
  toggles (`cg_conn_github/finance`), mirrored by checkboxes in **Settings →
  Connectors** plus a GitHub-token field (`cg_github_token`, localStorage only —
  verified absent from sync payloads).
- `systemContext()` teaches enabled connectors only:
  `[[connector]]{"service":…,"action":…,"params":…}[[/connector]]`, one call per
  reply then STOP. After a reply with a call: markers hidden (incl. mid-stream), a
  tool block renders ("Finances · quote" header, pretty-printed result JSON or red
  error), the result feeds back as `[Connector result]` and the model continues —
  same `CI_MAX_STEPS=5` cap and Stop handling; shares the tool-message role with CI
  (`m.conn` vs `m.run` discriminates rendering + sendMsgs mapping).

**Verified:** 22/22 headless (helpers, toggles, per-service system instructions,
full loop against the REAL backend hitting live Yahoo — MSFT quote rendered +
continuation, roles, convo persistence, settings hydration, token-not-synced,
reload) and backend curl checks for every action incl. auth-required and
unknown-service errors. All regressions green — **157 checks** across 8 suites
(connectors 22, ci 19, sync 11, share 22, canvas 33, voice 20, GPTs 16, archive 14;
one ci timing flake re-ran clean). Live on both domains: `/api/connector` 401-gated,
UI markers served.

**Parity list is now closed** except Sora video generation (no video model
available — sidebar item stays a placeholder by design).

---

## 2026-07-03 — Code interpreter (Docker-sandboxed Python via /api/run)

**Request:** "Please build code interpreter next" — the last big parity gap.

**Sandbox** (the crux — this is a prod server): unprivileged `unshare` is blocked on
this host, but the `spiritai` service user can use **Docker**. New image
**`chatgpt-pwm-ci:latest`** (python:3.11-slim + numpy/pandas/matplotlib/scipy/sympy,
`MPLBACKEND=Agg`; one `docker build` serves both backends — same host). Each run:
`--rm --network none --memory 512m --memory-swap 512m --cpus 1 --pids-limit 128
--user 65534:65534 --read-only --tmpfs /tmp:size=64m,exec --cap-drop ALL
--security-opt no-new-privileges`, per-request tmp workdir bind-mounted at `/work`
(script 644, `out/` 777 for plots), 30 s wall clock (`subprocess timeout` +
`docker kill`). Verified: network blocked (URLError), tracebacks captured, timeout
kills at 30 s, zero leftover containers.

**Backend** (`web/main.py`): **`POST /api/run`** `{code}` → `{stdout, stderr, images[],
timed_out, exit_code}` — PWM-key-gated like chat; images = data-URLs of files the code
saves to `/work/out/*.png|jpg|gif` (≤6, ≤4 MB each); 100 KB code cap, 40 KB output
caps; concurrency semaphore (4); `CHATGPT_CI_*` env knobs; 503 if docker/disabled.

**Frontend** (`web/index.html`) — the ChatGPT auto-run loop:
- **"Code interpreter"** row in the **+** menu (pill while armed; mutually exclusive
  with the other tools). `c.ciOn` persists per conversation.
- `systemContext()` teaches the model `[[run-python]] … [[/run-python]]` (one block
  per reply, then STOP; sandbox contents/limits; save plots to `/work/out/`).
- After a reply with a block: code renders as a normal ```python fence (markers never
  visible, incl. mid-stream), a **tool message** is appended ("Analysis" block:
  Running… spinner → stdout / red stderr / plot images / timeout note), the result is
  fed back as a `[Python execution result]` message and the model **continues
  automatically** — capped at `CI_MAX_STEPS=5` rounds; Stop button aborts the loop
  (`ciStopped`). Roles go user/assistant/tool/assistant; tool messages render from
  storage on reload.
- **Sync bug found & fixed:** `applySync` adopted server convos wholesale, but sync
  strips heavy fields — a round-trip deleted local CI plots (and inline gen images).
  New `graftHeavyFields()` restores locally-held `run.images` / `variant.image` /
  `att.url` onto incoming synced copies (guarded by code/ts/name equality).

**Verified:** 19/19 headless (helpers, + menu, fence rendering, real sandboxed run
with stdout "sum: 55" + matplotlib plot rendered, auto-continuation interprets
result, roles, reload persistence incl. plot, zero console errors) — chat SSE stubbed,
`/api/run` proxied to the real backend. All regressions green: sync 11, share 22,
canvas 33, voice 20, GPTs 16, archive 14 (135 total). Live: `/api/run` 401-gated on
both domains, UI markers served, `/health` 200.

**Remaining gaps:** connectors (needs real OAuth per service — descoped by design),
Sora video (no video model). Everything else on the parity list is done.

---

## 2026-07-02 — Hosted share links (public read-only chats at /share/<id>)

**Request:** "Please build hosted share links next."

**Backend** (`web/main.py`, same shared SQLite as sync → links resolve on BOTH
domains): table `shares(id, user, convo_id, data, created)`.
- **`POST /api/share`** (valid PWM key) — snapshots the convo (images stripped
  client-side), mints an unguessable `secrets.token_urlsafe(12)` id; **re-sharing the
  same chat upserts the SAME link** (ChatGPT's "update link" semantics). 400 KB cap.
- **`GET /api/share/{id}`** — public JSON snapshot (no key). **`GET /share/{id}`** —
  serves the SPA. **`GET /api/shares`** / **`DELETE /api/share/{id}`** — owner-only
  list + revoke (403 on foreign key, 404 after delete).

**Frontend** (`web/index.html`):
- **Share button** now creates a real link and opens a ChatGPT-style dialog (URL
  field + Copy link + Delete link + "anyone with the link" note). Logged-out → key
  modal.
- **Read-only shared view**: `init()` routes `/share/<id>` to `initSharedView()` —
  fetches the snapshot, renders the full thread (markdown/KaTeX/code intact) with a
  logo+title+date banner, sidebar/topbar/composer/message-actions hidden, and a
  floating **"Continue this conversation"** pill that clones the chat into the
  visitor's own history (then syncs if they're logged in). `persist()`/sync are
  disabled in shared view (`sharedView` guard). Dead links show "This link is
  unavailable" and hide Continue.
- **Settings → "Shared links"** manager: lists links (title + Open + ✕ revoke).

**Deploy gotcha (self-inflicted):** a `pkill -f "uvicorn…8894"` matched the *invoking
shell's own command line* and killed it mid-deploy (exit 144) — files never copied,
old code kept serving. Redone with self-safe patterns (`--port 889[4]` char-class
trick). 8201 supervisor respawn took ~15 s this time — poll before concluding failure.

**Verified:** headless 22/22 — dialog/URL, same-link upsert, public snapshot API, SPA
shared view (markdown rendered, chrome hidden), Continue→import→sidebar, Settings
list, foreign-key delete 403, owner revoke → API 404 + "unavailable" page, zero
console errors. All regressions green (sync 11, canvas 33, voice 20, GPTs 16,
archive 14). Live on both domains: share-gate 401, share page 200, dead snapshot 404,
UI markers served.

**Remaining gaps:** code interpreter, connectors, Sora.

---

## 2026-07-02 — Server-side sync (cross-device history via /api/sync)

**Request:** "Please build server-side sync next" — the last big parity gap.

**Backend** (`web/main.py`): **`POST /api/sync`** — per-item, newest-wins merge keyed
by `sha256(PWM key)`. SQLite at `~/pwm/chatgpt-sync/sync.db` (WAL; overridable via
`CHATGPT_SYNC_DB`) — **both backends share the file**, so the two public domains sync
with each other as well as across devices. Table
`items(user, kind, id, ts, deleted, data)`; kinds: `convo`, `project`, `gpt`, `kv`
(`kv/memories`, `kv/ci`). Client pushes its items; server upserts where incoming
`ts` is newer and returns the user's full merged state. Deletions are **tombstones**
(`deleted=1`, data nulled) kept forever so a stale device can never resurrect them.
Requires a valid PWM key (401 otherwise; balance pre-check, not billed). Caps:
400 KB/item (oversize skipped, sync still succeeds), 8 MB/push, 1200 items.

**Frontend** (`web/index.html`): `collectSyncItems()` ships chats (images/data-URLs
stripped via `stripConvoForSync`), projects, GPTs, memories+enabled flag, custom
instructions, and pending tombstones. `syncNow()` = push+pull in one call;
`applySync()` adopts the merged state (skipped while `generating` so a streaming
reply is never clobbered), rebuilds the UI, and drops the active view back to landing
if the open chat was deleted elsewhere. Triggers: **2.5 s debounce after any persist**
(`persist`/`saveProjects`/`saveGpts`/`saveMemories` all schedule), on load (~800 ms),
on tab focus, every 90 s, and **on login** (`saveKey` pulls the account's state).
Sync-relevant mutations now bump an `uts` stamp (rename, archive/unarchive, ratings,
move-to-project, canvas edits/title, GPT/project edits) — `ts` still drives sidebar
order, `max(ts,uts)` drives merge. Tombstones recorded in `delConvo`,
`deleteAllChats`, `deleteProject`, `deleteGptFromUI` (`cg_tombstones`, cleared after
a successful push). Memories/CI use `cg_mem_ts`/`cg_ci_ts` for LWW.

**nginx:** both chatgpt vhosts had the default 1 M `client_max_body_size` (a latent
413 risk for image uploads too) — now `20M` on both; `nginx -t` + reload clean.

**Deploy gotcha discovered:** killing the 8201 uvicorn gets it **respawned by a
supervisor** (parented to init, correct env/cwd) — so a plain kill after copying
files IS the restart procedure; my manual relaunch just lost the bind race and left
strays (cleaned up). 8200 restarted via `sudo -n systemctl restart chatgpt-pwm`.

**Verified:** py_compile + node --check OK; curl: 401 no key, push/merge round-trip
200; headless **two-device test** (fresh contexts, same key, local backend with scratch
DB + fail-open billing): 11/11 — B receives A's chat/project/memory/custom
instructions, rename on B propagates to A, deletion on A reaches B, **stale-copy
resurrection blocked by tombstone**, different key fully isolated, zero console
errors. All regressions green (canvas 33, voice 20, GPTs 16, archive 14 — their test
stubs gained an /api/sync echo). Live: `/api/sync` routed + key-gated [401] on both
domains, sync UI markers served, `/health` 200.

**Remaining gaps** now: code interpreter, connectors, Sora, hosted share links
(sync's server store is the natural foundation for share links next).

---

## 2026-07-02 — Neural voices: server-side TTS (/api/tts via edge-tts)

**Request:** upgrade voice mode / read-aloud from the browser's basic
`speechSynthesis` to neural voices — needs a server-side TTS endpoint.

**Backend** (`web/main.py`, BOTH backends restarted): new **`POST /api/tts`**
`{text, voice}` → streams `audio/mpeg` from **edge-tts** (Microsoft neural voices —
free, no API key; `pip install --user --break-system-packages edge-tts`, v7.2.8, into
the same `~/.local` site-packages the services use). Same PWM-key gate as `/api/chat`
(401 without/invalid key when `PWM_KEY_REQUIRED=1`; balance pre-check; TTS itself is
not billed). Voice allowlist {Jenny, Guy, Aria en-US; Sonia en-GB} — unknown voice
falls back to Jenny; text capped at 6000 chars; empty text → 400; missing edge-tts →
503 (UI falls back cleanly).

**Frontend** (`web/index.html`): `ttsPlay()` fetches `/api/tts` → blob → `Audio`
playback; **`voiceSpeak()` (voice mode) and `readAloud()` now use neural first** and
fall back to `speechSynthesis` when the endpoint fails/404s/returns empty (or when the
user picks "Browser voice"). Shared `ttsPlain()` markdown-stripper, `stopTts()`
(stops audio + cancels synthesis; wired into voice-mode end), `ttsBusy()` used by
voice-mode mute logic. **Settings gains a "Voice" picker** (`cg_tts_voice`): 4 neural
voices + "Browser voice (basic)".

**Deploy note (8201):** the standalone dev uvicorn was parented to an old Claude
session; it's now relaunched detached (`setsid nohup … > uvicorn.log`) from
`chatgpt-web-dev` with its captured env (`PWM_KEY_REQUIRED=1`,
`PWM_PLATFORM_URL=http://172.17.0.1:8101`), so it survives session exits. 8200
restarted via `sudo -n systemctl restart chatgpt-pwm`.

**Verified:** local uvicorn — `/api/tts` 200 with real MPEG audio (33 KB for one
sentence), 400 empty text, unknown-voice fallback; headless Chromium
(`--autoplay-policy=no-user-gesture-required`) against the real endpoint: 12/12 —
neural playback starts/ends/cleans up, read-aloud button toggles play/stop, "browser"
pref skips neural, Settings picker hydrates, zero console errors. Regressions all
green (voice 20, canvas 33, GPTs 16, archive 14). Live on BOTH domains: `/health` 200,
`/api/tts` + `/api/chat` key gates 401 as designed, UI markers served. (Full live
audio needs a valid `sk-pwm-` key — generation itself proven locally on the same code.)

---

## 2026-07-02 — Canvas (side-by-side collaborative editor)

**Request:** "Please build Canvas next."

**Built** (`web/index.html` only): ChatGPT's Canvas — a split-view editor where the
model writes/revises documents and code in a right-hand panel while chat continues on
the left. Backend unchanged; the protocol is marker-based: `systemContext()` (when the
Canvas tool is on **or** the convo already has a canvas) instructs the model to wrap
the ENTIRE artifact in `[[canvas: title="…" lang="…"]] … [[/canvas]]`, commentary
outside. The client:

- **Streams live** — `splitCanvas()` splits partial replies during `streamReply()`;
  canvas body paints into the panel as it streams (title bar shows "writing…"), the
  chat bubble gets a compact **canvas card** (icon + title + "Click to open canvas")
  instead of the raw block. Raw markers never render in chat; text outside markers
  shows normally. (Gotcha fixed: on very fast streams the pending rAF paint is
  cancelled in `finally` — the panel now also opens on commit.)
- **Versions** — each model rewrite pushes `c.canvas.versions[]` (v1/v2… with ‹ ›
  nav). Manual edits update the current version in place (debounced persist).
- **Panel** — editable title (rename re-titles the chat card), Edit↔Preview toggle
  (preview = rendered markdown; code renders as a highlighted fence; editor = plain
  textarea, mono for code), Copy, Download (extension from lang: py/js/…; md for
  prose), Close (card reopens). Quick-action chips by kind — doc: Polish/Shorter/
  Longer/Simplify/Add emojis; code: Add comments/Fix bugs/Code review/Optimize — each
  sends a normal user turn; the system context carries the current canvas content, so
  the model replies with a full updated artifact → new version.
- **Entry** — "Canvas — Collaborate on writing and code" row in the **+** menu, plus a
  composer pill while armed; auto-disarms once a canvas is committed (the follow-up
  instruction persists via `c.canvas`). One canvas per conversation, stored on the
  convo (`cg_convos`), survives reload. Mobile: panel goes full-screen.

**Verified:** `node --check` OK; headless (SSE stub streaming canvas markers in 40-char
chunks): 33/33 — parser, + menu/pill, live stream→panel, card in chat, no raw markers,
v1→v2 commit, version nav, edit/save/preview, rename, close/reopen, reload
persistence, code-canvas chips/mono, zero console errors. Regressions green: GPTs
16/16, archive+shortcuts 14/14, voice 20/20. Deployed to both live dirs; live smoke on
both domains (menu row, pill, panel render) clean.

---

## 2026-07-02 — Voice conversation mode

**Request:** "Please build voice conversation mode next."

**Built** (`web/index.html` only — no backend changes): a client-side voice loop in
ChatGPT's full-screen voice UI. Since the backend is a text SSE stream (no realtime
audio model), the loop is: **listen** (Web Speech `SpeechRecognition`, non-continuous
so silence ends the turn) → **send** through the normal `/api/chat` stream (message
persists into the active chat like a typed turn, incl. GPT persona / custom
instructions / memory) → **speak** the reply (`speechSynthesis`, markdown stripped:
code blocks → "code block omitted", links → text/"link") → **listen** again.

- **Entry:** a waveform **Voice mode** button in the composer (shown when the input is
  empty and both speech APIs exist, next to the dictate mic). Gated on a PWM key like
  send. `#voice-overlay`: blue radial-gradient orb with per-state animation
  (listening=pulse, thinking=dim, speaking=bounce, idle=faded), status line
  (Listening…/Thinking…/Speaking…/Muted), live interim transcript, and two round
  controls — **mute** (aborts recognition; unmute resumes) and red **✕ end**
  (also Esc). Recognition is deliberately NOT active while speaking, so the TTS
  audio can't feed back into the mic.
- Exiting re-renders the thread, so the spoken conversation is visible in the chat.

**Verified:** `node --check` OK; headless Chromium with mocked
SpeechRecognition/speechSynthesis + a real SSE `/api/chat` stub — 20/20 checks
(button→overlay→listen, interim transcript, Thinking→Speaking transitions, reply
spoken, auto re-listen, both turns persisted to the convo, mute/unmute, Esc + ✕ end,
zero console errors). GPTs (16) + archive/shortcuts (14) regressions still green.
Deployed to both live dirs; live smoke on both domains: button renders, overlay opens
to Listening…, Esc closes, zero console errors.

**Notes / limits:** needs a browser with `SpeechRecognition` (Chrome/Edge; the button
hides elsewhere); en-US recognition; voice is the browser's default TTS voice — not
OpenAI's neural voices; no barge-in while speaking.

---

## 2026-07-02 — Parity push: GPTs, archive chats, keyboard shortcuts

**Request:** "Make sure this ChatGPT based on PWM is the same as ChatGPT from OpenAI"
— the recurring parity directive. Finished the in-flight GPTs work and closed two more
gaps.

- **GPTs (custom versions of ChatGPT)** — the sidebar "GPTs" placeholder is now real:
  a grid of GPT cards (3 seeded examples: Code Copilot, Writing Coach, Chef) plus
  **+ Create a GPT** → modal with name / description / instructions (edit + delete via
  the card's pencil). Clicking a card starts a chat with that GPT: a pill above the
  composer shows *"Chatting with \<name\>"* (✕ to exit), the convo stores `gptId`, and
  `systemContext()` injects the persona (`You are "<name>", a custom GPT. <instructions>`)
  ahead of custom instructions + memory. Stored in `cg_gpts` (+ `cg_gpts_seeded`).
  (Prior session left this half-built and uncommitted — this session added the missing
  modal HTML, all GPTs CSS, and the `seedGpts()` init call.)
- **Archive chats** — chat ⋯ menu gains **Archive**; archived chats leave the sidebar
  (flag `convo.archived`) and appear in Settings under **"Archived chats"** with
  Unarchive / Delete. Archiving the active chat returns to the landing screen.
- **Keyboard shortcuts** — ChatGPT's set: **Ctrl/⌘+Shift+O** new chat,
  **Ctrl/⌘+Shift+S** toggle sidebar, **Shift+Esc** focus composer,
  **Ctrl/⌘+Shift+⌫** delete current chat (confirm), **Ctrl/⌘+/** shortcuts overlay
  (Esc closes; ⌘ shown on Mac).

**Verified:** `node --check` OK; headless Chromium (local): 16/16 GPTs checks
(seed/create/edit/persist/context-bar/systemContext/ensureConvo), 14/14
archive+shortcuts checks, zero console errors (only the expected `/api/balance` 404 on
the backend-less test server). **Deployed to both live dirs**; live smoke on
chatgpt.comparegpt.io + chatgpt.platformai.org: GPT grid renders, shortcuts open,
zero console errors.

**Still not at full parity** (larger lifts): voice conversation mode, Canvas, code
interpreter, connectors, Sora (placeholder), server-side cross-device sync, shareable
chat links (share uses Web Share/clipboard, no hosted URL).

---

## 2026-07-01 — Parity push: Custom instructions, real Library, real Projects

**Request:** Keep closing the gap to OpenAI's ChatGPT. Turned two decorative
placeholders into real features and added the most-requested missing one.

- **Custom instructions ("Customize ChatGPT")** — Settings gains two fields (what
  ChatGPT should know about you / how it should respond), stored in localStorage and
  sent as a leading **system** message. Backend (`openai_subscription._build_payload`)
  now **appends** a client system message to `_default_instructions()` instead of
  replacing it, so tone/date/formatting survive. Deployed to **both** backends (systemd
  `chatgpt-pwm` :8200 + `chatgpt-pwm-dev` :8201, both restarted).
- **Real Library** — images made with *Create image* now persist in **IndexedDB**
  (localStorage nulls them for quota) and render as a grid (newest first, prompt as
  caption) in the Library view; click → lightbox with Download/Delete. Saved on stream
  completion.
- **Real Projects** — create projects, add/move/remove chats via the chat ⋯ menu, open
  a project to see its chats + start chats scoped to it (sidebar Projects = list, click
  = detail with rename/delete). Persisted in `cg_projects` + `convo.projectId`.

**Verified** (headless, per feature): custom-instructions system message injected +
backend append; Library persist→grid→lightbox; Projects create→assign→list→detail;
zero console errors. Commits `6b5bcf9`, `7943a1a`, `91ecb11`; deployed to both live dirs.

**Still not at full parity** (larger lifts, documented): voice mode, Canvas, code
interpreter, cross-chat memory, connectors (OpenAI Platform/GitHub/Canva/Finances),
Sora/GPTs (still placeholders), server-side cross-device sync.

---

## 2026-06-29 — ChatGPT-style "+" tools menu (photos/files · image · web search · deep research)

**Request:** Replicate OpenAI ChatGPT's composer **+** menu. (Decisions: omit the
connectors — OpenAI Platform/GitHub/Canva/Finances — since they'd need real OAuth
integrations; Deep research = high-reasoning + web search.)

**Built** (`web/index.html`): the **+** button now opens a ChatGPT-style popup with four
rows (icon + title + description) and a bottom **"Type to search plugins, files & skills"**
filter box:
- **Add photos & files** → existing file picker.
- **Create image · "Visualize anything"** → toggles `imageGen` (image_generation tool).
- **Web search · "Find real-time news and info"** → toggles `webSearch` (web_search tool).
- **Deep research · "Multi-step web research"** → new: forces the request to
  `gpt-5.5-thinking` (effort=high) **and** `web_search=true`, with a "Researching…" status.
- Each tool row shows a live **checkmark**; the composer pills (Search/Image + a new
  **Deep research** pill that appears when active) stay in sync via `syncToolUI()`. The
  three tools are mutually exclusive. The bottom box filters rows by label/keywords
  (`filterPlusMenu`), with a "No matches" state. Clicks inside the menu no longer bubble
  to the document close-handler, so the search box is usable and checkmarks persist.

**Verified:** `node --check` OK; headless (local + live) — 4 items render with
descriptions, toggles + checkmarks + pills sync, mutual exclusivity holds, filter works
(`news` → Web search; `zzz` → No matches), zero console errors. Deployed to both live
dirs; confirmed live on chatgpt.comparegpt.io and chatgpt.platformai.org.

---

## 2026-06-29 — Three login methods on ChatGPT (Google / token.comparegpt.io / physicsworldmodel.org)

**Request:** "Make chatgpt.comparegpt.io log in by token.comparegpt.io or
physicsworldmodel.org or google." (Also reported the site "not available" — verified it
was actually up: 200, valid cert, renders, zero console errors; likely a transient
Cloudflare/network blip.)

**Built:** the login modal now shows **three** SSO buttons — *Continue with Google*
(with the Google "G" mark), *…with token.comparegpt.io*, *…with physicsworldmodel.org*
— above the manual `sk-pwm-…` field. All three funnel through the portal's app-login
bridge via `ssoLogin(method)`, which appends `&method=google|portal|pwm`. The portal
login page reads `method` and emphasizes the matching option (Google for google/pwm).
This reuses the portal's existing Google auth rather than duplicating it on ChatGPT.
Paired portal change: `token` branch `feat/app-login-sso` (commit `6ad9eac`).

**Verified:** JS syntax OK; headless — all three buttons render and navigate to the
correct `…/api/auth/app-login?redirect_uri=<origin>/&method=…` URLs.

**Still not deployed** (same ordering: portal endpoint must go live first). Live site
keeps the previous working behavior until then.

---

## 2026-06-29 — Automatic SSO: portal-side app-login endpoint (cross-repo)

**Request:** "Build the portal-side endpoint too" — complete the automatic key handoff
that the portal-login buttons couldn't do alone.

**Built** (spec: `docs/superpowers/specs/2026-06-29-pwm-sso-login-design.md`, REVISION 2).
Unblocking insight: the platform exchange already mints **`sk-pwm-`** keys
(`exchange_internal.py: KEY_PREFIX="sk-pwm-"`) — exactly what ChatGPT-PWM billing
validates — so the portal can mint one for a logged-in user and hand it back.

- **`token/` portal** (separate repo): new `GET /api/auth/app-login` — `redirect_uri`
  exact-match allowlist (→400 otherwise); not-authed → `302 /login?next=…`; authed →
  mint `sk-pwm-` consumer key (label "chatgpt") → `302 <redirect_uri>#pwm_key=…`; mint
  failure → `#sso_error=mint_failed`. Config `app_login_allowed_redirects` = the two
  ChatGPT origins. `Login.vue` `finishLogin()` now honors `?next=` (full nav for
  backend/absolute URLs). 3 new pytest tests, all green; full suite shows only the 11
  pre-existing cookie-over-http failures (unchanged from origin/main); frontend builds.
- **`chatgpt-pwm/`**: `web/index.html` `ssoLogin()` points the token.comparegpt.io
  button at `/api/auth/app-login?redirect_uri=<origin>/`; existing `captureKeyFromUrl()`
  consumes the returned `#pwm_key=`. JS syntax OK; headless click → navigates to the
  correct app-login URL.

**Not deployed / not pushed.** Both changes sit on feature branches. **Deploy order
matters:** the portal endpoint must be live *before* the ChatGPT button repoint (else
the button 404s). Portal deploy is director-gated. Until then, the live ChatGPT login
keeps the previous working behavior (portal buttons → portal root + manual key paste).

---

## 2026-06-29 — Portal login buttons + "get a token first" chat gate

**Request:** Let ChatGPT-PWM users log in directly via `token.comparegpt.io` /
`physicsworldmodel.org`; and when a logged-out user tries to chat, send them to
`https://token.comparegpt.io/` to get a PWM token first.

**Design + investigation** (spec: `docs/superpowers/specs/2026-06-29-pwm-sso-login-design.md`).
Read the platform (`pwm_nonprofit_dev`) and portal (`token/`) source to ground the
flow. Key constraints discovered: the platform's `/api/v1/auth/sso/issue` allowlists a
**single** `redirect_uri` (`token.comparegpt.io/api/auth/pwm-sso`), and the portal's
session cookie is host-scoped to `token.comparegpt.io` (not `.comparegpt.io`). So a
**fully-automatic** key handoff can't be done from `chatgpt-pwm` alone — it needs a
portal-side app-callback (deferred, would touch production auth in another repo).

**What shipped** (self-contained, `web/index.html` only — satisfies the request):
- **Login modal:** two portal buttons — *Continue with token.comparegpt.io* and
  *Continue with physicsworldmodel.org* — above an "or paste your key" divider and the
  existing `sk-pwm-…` field. Buttons redirect to the portal with a forward-compat
  `?return=<chatgpt-url>`. Hidden in full **Settings** mode.
- **Chat gate:** pressing send with no stored key now redirects the current tab to
  `https://token.comparegpt.io/` (toast: "Get a PWM token first…") instead of just
  reopening the modal. (Other entry points unchanged; no auto-redirect on page load.)
- **Forward-compatible return handler:** on load, a key arriving as
  `#pwm_key=…`/`#key=…`/`?pwm_key=…` (must match `sk-pwm-`) is stored and scrubbed from
  the URL — so if the portal later adds an app-callback, login completes with no
  further change here.

**Deploy / verify**
- `node --check` → OK; headless Chromium against a temp server: both buttons render,
  return-handler captures + scrubs both hash and query forms, chat-gate redirect hits
  `token.comparegpt.io/?return=…`, portal buttons hidden in Settings, zero console errors.
- Deployed to **both** live dirs (`chatgpt-web` + `chatgpt-web-dev`); verified the two
  buttons render live on `chatgpt.comparegpt.io` and `chatgpt.platformai.org`.

---

## 2026-06-29 — PWM-token onboarding reminder in the login modal

**Request:** Resume the ChatGPT session, record history here, and keep PWM ChatGPT at
parity with the real OpenAI ChatGPT. New ask this session: when users enter ChatGPT of
PWM, remind them to go to **token.comparegpt.io** to get a PWM token first.

**Starting state**
- Service healthy: `chatgpt-pwm.service` active, `GET /` → 200 on `127.0.0.1:8200`
  (`WorkingDirectory=/home/spiritai/pwm/chatgpt-web`); canonical git source is
  `chatgpt-pwm/web/index.html`.
- UI already at strong parity (landing layout, model menu incl. "ChatGPT Thinking",
  search/image tools, reasoning display, vision/PDF/DOCX upload, mobile polish — see
  recent commits). The login modal placeholder is `sk-pwm-…`.

**What changed**
- **Login modal now onboards new users to the PWM token.** The "Log in to ChatGPT"
  description (shown whenever no key is set) reads:
  *"Don't have a PWM token? Get one at **token.comparegpt.io**. Then enter your access
  key below to start chatting."* — with `token.comparegpt.io` as a clickable link
  (opens in a new tab). Applied in two places so it survives a re-render:
  the static `#settings-desc` markup and the login branch of `openSettingsModal()`
  (the full **Settings** view keeps its own "Manage your account…" copy).

**Deploy / verify**
- `node --check` on the extracted inline script → syntax OK.
- **Discovered there are TWO live web backends** (see the "Deploy targets" reference
  block at the top of this file). The first deploy only updated `chatgpt-web` (port
  8200 → `chatgpt.comparegpt.io`); `chatgpt.platformai.org` kept showing the old copy
  because it's a *separate* uvicorn on port 8201 serving `chatgpt-web-dev`. Confirmed
  that dev copy was byte-identical to the new file except for the reminder edit, then
  synced `index.html` to **both** live dirs.
- Headless Chromium against **both** public domains: login modal shows the new copy and
  `#settings-desc a` resolves to `https://token.comparegpt.io`. Screenshots captured.
- Shipped as commit `5893770` (pushed to `origin/main`,
  integritynoble/ChatGPT_PWM); this deploy-targets note is a follow-up commit.

---

## 2026-06-26 — Web UI brought to real-ChatGPT parity

**Request:** "Resume the chatgpt session, refer to claude-pwm, record the history here,
and make the PWM ChatGPT the same as the real ChatGPT from OpenAI." Plus: use
`sk-pwm-…` as the PWM-key placeholder/reminder.

**Starting state**
- Web service live: `chatgpt-pwm.service` → `uvicorn main:app` on `127.0.0.1:8200`,
  fronted by nginx at **https://chatgpt.platformai.org** (Certbot TLS, SSE-friendly
  proxy: `proxy_buffering off`).
- systemd `WorkingDirectory=/home/spiritai/pwm/chatgpt-web` (the **live deploy copy**).
  Git-tracked canonical source is `chatgpt-pwm/web/`. The two `index.html` /
  `main.py` / `openai_subscription.py` were identical at session start.
- Backend generation confirmed working: streamed real **GPT-5.5** from the pooled
  **ChatGPT subscription** (OAuth in `~/.codex/auth.json`). Billing gated by a PWM key
  (`PWM_KEY_REQUIRED=1`) checked against the PWM platform at `127.0.0.1:8101`.
- UI was already a solid dark-mode replica (sidebar+history, model dropdown, streaming
  markdown, code copy, KaTeX, regenerate, PWM-key modal).

**What changed (this session)** — full rewrite of `web/index.html` (pure client-side
SPA; backend `main.py` / API contract unchanged). Closed the gap to chatgpt.com across
all four areas:

- *Chat UX:* real in-sidebar **search** (filters by title + message text), **edit a
  user message** (truncates the thread at that turn and re-streams), **rename / delete**
  chats via a per-item ⋯ menu, auto chat titles from the first message, floating
  **scroll-to-bottom** button, stop-generation button.
- *Account / auth:* bottom-left **account menu** (key state + live balance, Settings,
  theme toggle, Log out) and a top-right avatar that opens it; a real **Settings** modal
  (PWM key, appearance, default model, delete-all-chats). PWM-key placeholder is now
  **`sk-pwm-…`** (matches prod, which mints `sk-pwm-` keys).
- *Reasoning & richness:* animated **thinking** dots before the first token,
  **regenerate-with-model-picker** dropdown, per-message **timestamps**, graceful
  empty/error states ("No response.", toast on stream error).
- *Visual polish:* **light + dark + system theme** (CSS-variable palettes, follows
  `prefers-color-scheme`), and the iconic **landing layout** — greeting + composer +
  suggestion chips vertically centered on an empty chat, composer drops to the bottom
  once the conversation starts.

State persists in `localStorage` (`cg_convos`, `cg_model`, `cg_theme`, `cg_pwm_key`).

**Deploy mechanic (important):** `main.py` reads `index.html` fresh on every `GET /`,
so deploying the UI is just copying the file to the live dir — **no service restart**:

```bash
cp chatgpt-pwm/web/index.html /home/spiritai/pwm/chatgpt-web/index.html
```

(Backend/`main.py` changes still need `systemctl restart chatgpt-pwm`.)

**Verification**
- `node --check` on the extracted inline script → syntax OK.
- Live `GET /` serves the new markup (theme/edit/scroll/`sk-pwm` markers present);
  `<title>ChatGPT</title>` intact.
- Backend streaming path intact: live `/api/chat` returns the PWM-key gate as designed
  (`Invalid PWM key` for a fake key); raw subscription generation re-confirmed.
- Headless Chromium (Playwright) render: **zero console errors**; model menu opens,
  Settings modal opens, search filters to the right count + shows "No chats found",
  light/dark themes render, KaTeX + code-block copy render. Screenshots captured.

**Known limits / deviations**
- Auth is a PWM key (billed to PWM balance), not an OpenAI account login — by design.
- Attachments / image input are stubbed (toast); voice not implemented.
- Chat titles are derived client-side from the first message (no model-generated title).
- History is per-browser `localStorage` (no server-side sync across devices).
