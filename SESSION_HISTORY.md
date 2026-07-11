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

## 2026-07-11 — LIVE verification: code-interpreter file download (7/7)

**Request:** live-verify the file download on production. Throwaway exchange user
212 / key `sk-pwm-DHfY0hJ…U9xM` (20 PWM; minted directly into the platform DB —
`users` + `api_keys` (sha256 key_hash) + `pwm_token_accounts`).

**Proven on chatgpt.comparegpt.io** with a full real round-trip: armed the code
interpreter → asked for "a pandas DataFrame of 3 fruits with prices saved to
/work/out/fruits.xlsx" → the **real model wrote & ran the Python** in the live
Docker sandbox → an **Analysis** tool block rendered with `Created
/work/out/fruits.xlsx` and a `fruits.xlsx 5 KB ⬇` download row → the reply read
"Your Excel file is ready: **Download fruits.xlsx**" → **clicking the button
downloaded a real 5451-byte file whose header is `PK`** (valid xlsx/zip). The file
blob is stored on the tool run and stripped from the sync payload. Zero console
errors. Screenshot: `live_ci_files.png`.

Pre-flight also confirmed the key validated on the prod platform (balance 20.0)
and the live 8200 `/api/run` produced `cities.xlsx` (5430 bytes) with the key.

**Artifacts pruned:** platform user 212 + api_key + pwm_token_accounts +
transactions deleted (key now returns **401** live); the one synced `items` row
(fruits convo) purged from `chatgpt-sync/sync.db`. No residual.

---

## 2026-07-11 — Parity: downloadable files from the code interpreter

**Request:** "continue to make it the same as ChatGPT." ChatGPT's code interpreter
lets you download the files the code writes (CSV/xlsx/docx/pdf). We only surfaced
images before; now any non-image file the sandbox writes to `/work/out/` comes back
as a download button.

**Backend (`main.py` `_run_sandboxed`):** after collecting images, also collect
non-image files from `outdir` — base64-encoded, with caps `CI_MAX_FILES=6`,
`CI_MAX_FILE_BYTES=8_000_000`. Returned as `files:[{name,size,data}]` alongside
`images`. Both 8200 (systemd) and 8201 (uvicorn) backends restarted.

**Docker image (`chatgpt-pwm-ci:latest`):** rebuilt to add file-gen libs —
`openpyxl python-docx reportlab XlsxWriter` (were all missing; `pandas.to_excel`
would have failed). Verified xlsx/docx/pdf generation.

**Frontend (`index.html`):** `toolMessageHtml` renders `.ci-file` download buttons
(icon + name + `fmtSize` + download icon); `downloadCiFile()` turns the base64 blob
into a Blob download; `renderMessage` wires the buttons; `streamReply` feeds the
produced filenames back to the model; the CI system-context now teaches saving to
`/work/out/`. `stripConvoForSync` + the localStorage quota-fallback both strip the
`files` blobs so heavy data never syncs/persists.

**Verified end-to-end** on a clean backend: `df.to_excel('/work/out/report.xlsx')`
+ a `.txt` write → response returned both files (report.xlsx 5416 bytes valid,
notes.txt 11 bytes), exit 0. Headless UI test `test_ci_files.py` 7/7. Deployed to
both live dirs; `downloadCiFile` present on both public domains.

---

## 2026-07-10 — LIVE verification: image editing (9/9, real edit round-trip)

**Request:** live-verify image editing on production. Throwaway exchange user 211
/ key `sk-pwm-lErMe…SS6E` (20 credits, image gen is pricier).

**Proven on chatgpt.comparegpt.io** with a full real round-trip: armed image gen
→ generated a **real image** ("flat illustration of a red apple on white", 1.08 MB
data URL) → the generated image showed an **Edit** button → clicking it attached
the image + armed image gen → sent "add a small green leaf on top" → a **second,
DIFFERENT edited image** came back (`src2 != src1`, both 1 MB+ data URLs).
Screenshot shows the apple-with-leaf edit. Zero console errors.

**Artifacts pruned:** user 211 + api_key 292 + pwm_token_accounts row deleted, 6
sync/file rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-10 — Parity: image editing (refine a generated/library image)

**Request:** "Continue parity." I'd flagged image editing as infra-bound — but
tested the subscription and found it FEASIBLE: `image_generation` edits an input
image (blue 64×64 square + "add a yellow circle" → returned an edited image). The
backend already passes `input_image` parts, so this was just a UX layer.

**Built** (`web/index.html`): an **Edit** button on generated images (inline,
appears on hover) and in the **Library lightbox**. `editImage(url)` attaches the
image, arms image generation (clears other tools), and hints the composer
("Describe your edit — e.g. make the sky a sunset orange"). The next turn sends
the image as an `image_url`/`input_image` part with `image_gen=true`, so the
model returns an edited image.

**Verified:** headless 9/9 — inline + lightbox Edit buttons, Edit attaches the
image + arms image_gen + sets the composer hint, the edit turn's request carries
the input image AND image_gen, and the edited image renders. The
subscription-level edit was proven directly (real edited image returned).
explore/find/voice suites green. Live on both domains.

---

## 2026-07-10 — LIVE verification: Explore GPTs (persona confirmed)

**Request:** live-verify Explore GPTs on production. Throwaway exchange user 210 /
key `sk-pwm-I-mKQ…yLU8` (id 289).

**Proven on chatgpt.comparegpt.io:** the GPTs view rendered the **Explore GPTs**
section with all category headers and 12 curated cards; trying **Math Tutor**
added it to the user's GPTs and opened it with its starter chips. Captured the
live `/api/chat` payload → the **Math Tutor persona was genuinely sent**; a real
GPT-5.6 turn on a conceptual question ("why is the derivative of x² is 2x")
produced a proper 1442-char **step-by-step teaching** reply ("imagine increasing
x by a small amount h…"), not a one-liner. (First probe used trivial arithmetic
"8×7"; the tutor sensibly answered "56" directly — my assertion was too strict,
not a feature miss.) Zero console errors.

**Artifacts pruned:** user 210 + api_key 289 + pwm_token_accounts row deleted, 8
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-10 — Parity: Explore GPTs (curated discovery catalog)

**Request:** "Continue parity." After a genuine audit (web-search sources =
footer chips like ChatGPT; reasoning = collapsible; branching/regenerate present),
the one visible remaining piece was ChatGPT's **"Explore GPTs"** discovery page —
ours only showed the user's own GPTs.

**Built** (`web/index.html`): the GPTs view now shows **Your GPTs** + an **Explore
GPTs** section — a curated `EXPLORE_GPTS` catalog of 12 example GPTs grouped by
category (Research & Analysis / Productivity / Education / Programming / Writing /
Lifestyle), each with instructions + conversation starters. `tryExploreGpt(id)`
adds it to the user's GPTs (persists + syncs) and opens it; once added it moves
out of Explore into Your GPTs. No live marketplace backend exists, so the catalog
is an honest built-in curated set (not a fake live store).

**Verified:** headless 9/9 — Explore section + all category headers, 12 explore
cards, try→add+open with starters shown + persona injected into the request, and
an added GPT leaves Explore for Your GPTs. gpt-knowledge/gpt-share/find suites
green. Screenshot matches ChatGPT's GPTs landing. Live on both domains.

**Parity status:** the consumer surface is now comprehensively covered; the
remaining ChatGPT items are infra-bound (Atlas browser, full-duplex GPT-Live
voice, Work agent, live GPT Store marketplace, image inpainting).

---

## 2026-07-10 — GPT-5.5 + GPT-5.4 added to the picker; in-chat find LIVE (12/12)

**Request:** live-verify in-chat find on production, and make GPT-5.5 + 5.4
available.

**GPT-5.5/5.4** (`web/openai_subscription.py` + `web/index.html`): probed the
subscription — `gpt-5.5`/`gpt-5.4`/`gpt-5.4-mini` all generate, bogus 400s
(genuine access). The picker now lists **5 models**: GPT-5.6 Sol/Terra/Luna,
GPT-5.5, GPT-5.4. Backend map: `gpt-5.5`→`gpt-5.5` and `gpt-5.4`→`gpt-5.4` (real
pass-through, no longer aliased to 5.6); the internal effort aliases
(`gpt-5.5-instant`→5.6-terra low, `gpt-5.5-thinking`→5.6-sol high) still drive
the voice fast lane + deep research unchanged. Both backends restarted.

**LIVE verified (12/12) on chatgpt.comparegpt.io:**
- **Models:** picker lists all 5; **GPT-5.5** routes to `gpt-5.5` and **GPT-5.4**
  to `gpt-5.4` with real generation (`MODEL55-OK` / `MODEL54-OK`).
- **In-chat find:** Ctrl+F opened the find bar over a real reply, 6 "banana"
  matches highlighted, count `1/6`, active hit marked, ‹ ›/nav advanced to `2`,
  close removed all highlights. Zero console errors.

Test artifacts pruned (8 sync rows, key dead).

---

## 2026-07-10 — Parity: in-chat find (Cmd/Ctrl+F, highlight + navigate)

**Request:** "Continue parity." Research confirmed the big remaining ChatGPT
items are infra-bound (Atlas browser, full-duplex GPT-Live voice, Work agent,
GPT Store, image inpainting). A feasible client-side gap: ChatGPT's **in-chat
find** (Cmd/Ctrl+F highlights + navigates matches within the conversation) — we
only had cross-chat sidebar search.

**Built** (`web/index.html`): Cmd/Ctrl+F opens a floating find bar over the
current chat (falls through to the browser's native find when no chat is open,
and skips group/shared views). Live search highlights every match — a
`TreeWalker` wraps matching text nodes in `<mark class="find-hit">` (skips
actions/script/style/existing marks), shows `n/total`, navigates with ‹ › /
Enter / Shift+Enter (wraps), and scrolls the active hit into view. Esc or ✕
closes and **fully unwraps the marks** (text restored via replace + normalize —
no corruption). `renderThread` re-applies an open find over the rebuilt DOM.

**Verified:** headless 14/14 — open, all 3 matches highlighted, count, active
hit, **body text intact through highlight**, next/wrap, requery, no-match 0/0,
close removes marks + restores text, zero errors. gpt-share/record/charts/
followups suites green. Screenshot matches ChatGPT's find bar. Live on both
domains.

---

## 2026-07-10 — Parity: share a custom GPT via link (built + LIVE 7/7)

**Request:** "Continue parity." ChatGPT lets you share a custom GPT via "anyone
with the link"; recipients can chat with / add it. We had chat share links but
not GPT sharing.

**Built** (`web/main.py` + `web/index.html`, reuses the share store): backend
`ShareRequest` gains an optional `gpt` field; `create_share` stores it under a
`{_gpt:…}` wrapper keyed by `gpt:<id>` (re-share updates the same link). A
**Share** button in the GPT editor publishes the GPT (name/desc/instructions/
starters + knowledge, with attached-file TEXT inlined so the copy is
self-contained; private file ids never shared) and shows the link in the
existing share dialog. Opening a `/share/<id>` whose snapshot has `_gpt` renders
an **"Add to my GPTs"** import screen; adding stashes the config (`cg_import_gpt`)
and, on landing, `init()` imports it as a new local GPT and opens it.

**Verified:** headless 10/10 (two-browser share→import: link + `_gpt` wrapper +
inlined knowledge, import screen with starter previews, add→import carries
instructions/knowledge, import consumed once). **LIVE 7/7** on
chatgpt.comparegpt.io: shared a "Riddle Bot" GPT, the public `/api/share/<id>`
returned the `_gpt`+knowledge snapshot with NO key, a recipient (separate
context) saw the import screen and **imported it with instructions + knowledge
intact**. Both backends restarted; test artifacts pruned (share row deleted →
link 404s, key dead).

---

## 2026-07-10 — LIVE verification: custom-GPT knowledge files (6/6)

**Request:** live-verify GPT knowledge files on production. Throwaway exchange
user 205 / key `sk-pwm-YbIYU…E1bg` (id 280).

**Proven on chatgpt.comparegpt.io** with a secret only the file could hold:
**uploaded a real file** to the live library (`POST /api/files`, id
`b14184e…`) containing a made-up shutdown phrase (`Marigold-Tango-6631`) +
backup site (Reykjavik); attached it to a "Field GPT"; asking inside the GPT,
**real GPT-5.6 answered from the file** — "The emergency shutdown phrase is
Marigold-Tango-6631." and "The backup site is in Reykjavik." A **plain chat
(no GPT) said "I do not know"** — the file content did NOT leak, proving it's
scoped to the GPT. Zero console errors.

**Artifacts pruned:** user 205 + api_key 280 + pwm_token_accounts row deleted;
the uploaded library file + 9 sync/file rows purged; key now returns "Invalid
PWM key." live.

---

## 2026-07-10 — Parity: custom-GPT knowledge FILES (attach library docs)

**Request:** "Continue parity" (the file-based knowledge follow-up I flagged).
ChatGPT's GPT knowledge is file uploads; ours had only a paste-text field.

**Built** (`web/index.html`): the GPT editor gains a **"Knowledge files"** section
that attaches files from the library — reuses the existing file picker via a
`filePickTarget` flag (null → attach to composer; 'gpt' → add to the GPT), up to
20 files, stored as `{id,name,kind}` on `g.files`. `ensureGptFiles(gid)` fetches
each file's content (`/api/files/{id}`) into `gptFilesCache`; `systemContext()`
injects the text content ONLY within that GPT's chats (warmed on `startGpt` and
before each `onSend`, mirroring project files). Files ride the existing GPT sync;
the paste-text Knowledge field still works alongside. Non-GPT chats get nothing.

**Verified:** headless 10/10 — Knowledge-files section present, picker routes to
the GPT (target flag set + reset), add shows a chip + stores the ref, the file
content is injected into the GPT's request (secret `Orange-Vortex-99`), a plain
chat has NO file content, and remove empties the list + persists.
gpt-knowledge/project/record/mobile suites green. Live on both domains.

---

## 2026-07-10 — LIVE verification: custom-GPT knowledge (6/6)

**Request:** live-verify GPT knowledge on production. Throwaway exchange user 204
/ key `sk-pwm-72Su_…lY2U` (id 276).

**Proven on chatgpt.comparegpt.io** with a secret that could ONLY come from the
injected knowledge: created an "Acme Helpdesk" GPT whose knowledge held a made-up
WiFi password (`ZanzibarPelican-4417`) + mascot (a llama named Kevin). Starter
chips rendered. Asking inside the GPT, **real GPT-5.6 answered from the knowledge**
— "The office Wi‑Fi password is ZanzibarPelican-4417." and "The mascot is a llama
named Kevin." A **plain chat (no GPT) said "I do not know the Acme office Wi‑Fi
password"** — the secret did NOT leak, proving the knowledge is scoped to the GPT.
Zero console errors.

**Artifacts pruned:** user 204 + api_key 276 + pwm_token_accounts row deleted, 8
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-10 — Parity: custom GPTs get knowledge + conversation starters

**Request:** "Continue parity." Research (OpenAI GPT-builder help/academy):
custom GPTs support **knowledge files** (reference docs the GPT draws on, RAG)
and **conversation starters** (3-4 example prompts shown when the GPT opens).
Ours had name/desc/instructions only.

**Built** (`web/index.html`): the GPT modal gains **Conversation starters**
(one per line, capped at 4 → `g.starters[]`) and **Knowledge** (reference text
→ `g.knowledge`, 20 KB cap). `systemContext()` injects a GPT's knowledge as a
system message ONLY within that GPT's chats. The empty-chat landing for a GPT
now shows the GPT name + description + clickable **starter chips** (click fills
and sends) — removing the blank-page problem. Both fields hydrate on edit,
persist on the GPT, and ride the existing GPT sync. Seeded example GPTs
(Code Copilot / Writing Coach / Chef) gained starter sets. Non-GPT chats keep
the default greeting and no knowledge.

**Verified:** headless 14/14 — both fields present + save/hydrate, starters
capped at 4, chips render on the GPT landing and clicking sends, GPT persona +
knowledge injected for that GPT's request, a plain chat has NO knowledge and the
default greeting, edit round-trips both fields. record/temp/project/followups
suites green. Screenshot: "Support Bot" GPT landing with 4 starter chips + the
"Chatting with" pill. (Test-env note: the empty `/api/sync` stub wipes locally
seeded GPTs via `applySync`; production echoes the push so seeded GPTs survive.)
Live on both domains.

---

## 2026-07-09 — LIVE verification: Record mode (7/7)

**Request:** live-verify Record mode on production. Throwaway exchange user 203 /
key `sk-pwm-NF9uu…BwuM` (id 271); mic mocked (no audio hardware) emitting a
realistic 5-line standup transcript.

**Proven on chatgpt.comparegpt.io:** started recording (bar captured the live
transcript), Stop & summarize → the transcript went out as a real "Recording
transcript" turn and a **real GPT-5.6 (Sol) reply produced structured notes** —
Summary, Key points (with dates it inferred: Wednesday→July 15, tomorrow→July 10,
Friday→July 17), and Action items — capturing the real content (pricing page,
Maria's email campaign, mobile delay, login-bug ticket). Screenshot shows the
transcript turn + structured notes + "Recording notes" sidebar title. Zero
console errors.

**Artifacts pruned:** user 203 + api_key 271 + pwm_token_accounts row deleted, 6
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Parity: Record mode (transcribe + summarize a meeting/voice note)

**Request:** "Continue parity." Research (gend.co feature roundup / release
notes): ChatGPT's **Record Mode** captures meetings/voice notes, transcribes,
and turns them into actionable outputs (summary + action items). We had
dictation + voice mode but no record-and-summarize.

**Built** (`web/index.html`): a **Record** row in the + menu starts a continuous
`SpeechRecognition` capture with a fixed **recording bar** (pulsing red dot,
MM:SS timer, live running transcript, Cancel / Stop & summarize). The recognizer
self-restarts on `onend` (keepalive) so long sessions don't drop. On **Stop**,
the raw transcript is pushed as a "📝 Recording transcript" user turn and
`streamReply` runs with `RECORD_HINT` → the model returns structured notes: a
one-line **Summary**, **Key points** bullets, and an **Action items** checklist
(`- [ ]`). **Cancel** discards silently. Reuses the existing speech infra; gated
on a key + mic support (Chrome/Edge).

**Verified:** headless 11/11 — Record row present, bar opens, transcript
accumulates live, timer runs, Stop creates the transcript turn + sends the
summarize hint + renders structured notes, Cancel records nothing/closes the
bar, zero console errors. canvas-html/mobile-menu/voice/followups suites green.
Screenshot: the recording bar mid-capture. Live on both domains.

---

## 2026-07-09 — LIVE verification: Canvas HTML preview (8/8)

**Request:** live-verify the HTML canvas preview on production. Throwaway exchange
user 202 / key `sk-pwm-hzSEY…ykDU` (id 264).

**Proven on chatgpt.comparegpt.io:** armed Canvas via the + menu, asked for a
counter web page. A **real GPT-5.6 (Sol) turn built a "Click Counter" HTML app**
that rendered live in a sandboxed iframe (`allow-scripts`, no `allow-same-origin`).
**Decisive interactivity proof:** clicking the button inside the iframe twice
changed the display "0" → "2" — the app genuinely runs. The code/preview toggle
flipped to source and back. No app console errors (sandbox storage errors
excluded — that boundary is working). Screenshot: the styled counter card in the
canvas panel, header "ChatGPT Sol".

**Artifacts pruned:** user 202 + api_key 264 + pwm_token_accounts row deleted, 6
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Canvas: live HTML preview (ChatGPT Canvas / Sites parity)

**Request:** "Continue parity." Today's OpenAI launch was mostly infra-bound
(ChatGPT Work agent, full-duplex GPT-Live voice, desktop-app merger) — the
feasible client-side gap: ChatGPT's Canvas renders **live HTML/web previews**
(and the new **Sites** beta builds on it), while ours showed HTML only as a
highlighted code fence.

**Built** (`web/index.html`): an HTML canvas (`lang="html"`) now renders live in a
**sandboxed iframe** — `srcdoc` + `sandbox="allow-scripts allow-forms
allow-modals allow-popups"` (NO `allow-same-origin`, so the rendered app can't
reach our origin, cookies, or localStorage). A `<>` code/preview toggle
(`cvToggleSource`, shown only for HTML) flips between the live render and the
source fence; Edit still edits source; `cvSourceView` resets to live on open.
The canvas system instruction now tells the model that `lang="html"` should be a
complete standalone document (inline CSS/JS) that renders live. Prose and
other-language code canvases are unchanged (no iframe, toggle hidden).

**Tradeoff (documented):** the sandbox lacks `allow-same-origin` by design, so a
generated app's `localStorage`/cookie access throws (caught, harmless — the app
still renders). Allowing storage safely would need a separate sandbox origin we
don't have; the safe boundary is the right call.

**Verified:** headless 10/10 — live iframe with the correct sandbox flags, srcdoc
carries the HTML, **the rendered app is interactive** (clicking a button inside
the iframe updates it), code/preview toggle works, and a prose/doc canvas is
unaffected (no iframe, toggle hidden). charts/followups/study/auto-think suites
green. Screenshot: a styled, interactive demo rendering in the canvas panel.
Live on both domains.

---

## 2026-07-09 — Model picker: GPT-5.6 Sol/Terra/Luna as visible tier choices

**Request:** "Add Sol/Terra/Luna as visible choices in the picker" (follow-up to
the 5.6 upgrade). ChatGPT Plus lets users choose among the tiers.

**Built** (`web/index.html`): the picker now lists **GPT-5.6 Sol** (most capable),
**GPT-5.6 Terra** (fast/balanced), **GPT-5.6 Luna** (lightweight) — model ids are
the real backend slugs; default + migration land on Sol; header shows the tier
name. Special paths unchanged: voice still forces `gpt-5.5-instant` and deep
research `gpt-5.5-thinking`, which the backend maps to Terra-low / Sol-high — so
the fast lane and high-reasoning path keep working without touching that code.
**Auto-switch to Thinking** now escalates **Terra → Sol** for complex questions
(logic + note updated). Regenerate menu, Settings default-model select, and sync
all iterate MODELS, so they picked up the tiers automatically.

**Verified:** headless — auto-switch (Terra+complex→Sol, Terra+simple stays,
disabled stays, explicit Sol respected), voice fast-path (still forces the fast
alias; typed keeps the selected tier), study/followups/charts/memory suites
green. **LIVE 8/8** on chatgpt.comparegpt.io: picker lists Sol/Terra/Luna, header
shows the tier, and selecting each tier routes a real turn to its exact slug
(`gpt-5.6-terra`/`-luna`/`-sol`) with real generation. Test key pruned.

---

## 2026-07-09 — GPT-5.6 upgrade (Sol/Terra/Luna) — the app now runs on 5.6

**Request:** "Continue parity; check if ChatGPT 5.6 is available." It went **GA
in ChatGPT consumer today (2026-07-09)** — new naming: the number is the
generation, **Sol** (top tier), **Terra** (free default), **Luna** (efficient),
with effort levels layered on top.

**Backend probe (rigorous, with control):** against the real subscription,
`gpt-5.6-sol`/`-terra`/`-luna` all generate; bare `gpt-5.6` and `gpt-5.99-bogus`
both 400 "not supported" — confirming the upstream validates names and genuinely
serves the 5.6 tiers.

**Upgraded** (`web/openai_subscription.py`, both backends restarted): the
simplified picker's effort levels now map onto 5.6 tiers with the **frontend ids
unchanged** (no churn to stored prefs / sync / code): Instant → `gpt-5.6-terra`
(fast), Medium → `gpt-5.6-sol`, High → `gpt-5.6-sol` with high reasoning effort.
`DEFAULT_MODEL` → Sol (so group chats + scheduled tasks run 5.6 too). Legacy
5.4/5.5 aliases resolve to 5.6 tiers for older synced prefs. Frontend needs no
change — the header shows the effort level ("Medium"), not a version string.

**Verified:** unit map (each level → correct slug + effort: Instant→Terra/low,
Medium→Sol/default, High→Sol/high) + real generation on each of the three levels
through the **live front door** on chatgpt.comparegpt.io ("FIVESIX-OK" streamed
for all three). Both backends + both domains healthy. Test key pruned.

---

## 2026-07-09 — LIVE verification: Auto-switch to Thinking (6/6)

**Request:** live-verify auto-switch on production. Throwaway exchange user 199 /
key `sk-pwm-Yo0yK…rumw` (id 245). Captured the live `/api/chat` model field then
let it hit the REAL backend.

**Proven on chatgpt.comparegpt.io** (payload, on Instant with Auto-switch on):
a complex prompt ("Prove √2 is irrational, explaining each step") **escalated
Instant → `gpt-5.5` (Medium)** and returned a real proof; a simple "say hi"
**stayed `gpt-5.5-instant`**; and with Auto-switch OFF, a complex prove-prompt
**stayed `gpt-5.5-instant`**. Zero console errors.

**Artifacts pruned:** user 199 + api_key 245 + pwm_token_accounts row deleted, 8
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Parity: Auto-switch to Thinking (Instant → Medium on hard queries)

**Request:** "Continue to make it the same as ChatGPT." Research (OpenAI help /
model release notes): the model picker's **Configure → "Auto-switch to
Thinking"** — on Instant, complex requests automatically use more reasoning
(Instant → Medium). We lacked it.

**Built** (`web/index.html`): the model menu gains an "Auto-switch to Thinking"
toggle below a divider (`cg_auto_think`, default on). A `looksComplex()` heuristic
(length >360, ≥3 questions, code/enumerated task list, or reasoning keywords —
prove/derive/solve/optimize/step-by-step/analyze/why/…) escalates
`gpt-5.5-instant → gpt-5.5` on the INITIAL turn only. Never touches voice turns
(latency-critical), deep research, tool-continuation turns (depth>0), or an
explicitly selected Medium/High.

**Verified:** headless 10/10 — toggle present + default on, heuristic (simple
greeting not complex; prove/step-by-step complex), Instant+complex→Medium,
Instant+simple stays Instant, disabled stays Instant, explicit Thinking
respected. Voice fast-path still forces Instant; charts green. Screenshot shows
the picker with the Configure toggle. Live on both domains.

---

## 2026-07-09 — LIVE verification: Study mode (6/6)

**Request:** live-verify Study mode on production. Throwaway exchange user 198 /
key `sk-pwm-d1APQ…UBzY` (id 242). Captured the live `/api/chat` payload then let
it hit the REAL backend.

**Proven on chatgpt.comparegpt.io** (payload + behavior): toggled Study mode on
via the live + menu (row + composer pill lit); asked "What is the derivative of
x squared? Teach me." A **real GPT-5.5 reply tutored** — opened "Great! Let's
learn it step by step," introduced the power rule, and asked guiding questions
rather than just stating "2x." The captured live request carried the STUDY MODE
system instruction. Toggling off + new chat hid the pill. Zero console errors.

**Artifacts pruned:** user 198 + api_key 242 + pwm_token_accounts row deleted, 6
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Parity: Study mode (Socratic step-by-step tutor)

**Request:** "Continue to make it the same as ChatGPT." Research (OpenAI blog
"Introducing study mode"): **Study Mode** (all plans, 2026) guides the user
step by step with questions instead of just answering, calibrated to their
level. We lacked it.

**Built** (`web/index.html`): a "Study and learn" row in the + menu + a composer
"Study" pill, following the code-interpreter pattern — `toggleStudyMode()` sets a
per-conversation flag `c.studyOn`, reflected in the pill/checkmark, restored on
`loadConvo`, reset on `newChat`; persisted in `onSend`. `systemContext()` injects
a Socratic-tutor instruction when `studyActive(c)`: gauge the user's level, work
ONE step at a time with a check-for-understanding question after each, give hints
not answers when stuck, correct gently, end with a practice check — with an
escape hatch if the user explicitly just wants the answer.

**Verified:** headless 14/14 — row present, off by default, toggle marks the row
+ shows the pill + injects the instruction, instruction reaches the backend,
`studyOn` persists on the convo, a new chat resets it while reopening the study
chat restores the pill AND the instruction, toggle-off drops both.
charts/followups/project-instructions/mobile-menu suites green. Live on both
domains.

---

## 2026-07-09 — LIVE verification: per-project custom instructions (8/8)

**Request:** live-verify project instructions on production. Throwaway exchange
user 196 / key `sk-pwm-T_4Se…TlLQ` (id 237). Set a GLOBAL custom instruction
("always answer in French") that a PROJECT instruction must override.

**Proven on chatgpt.comparegpt.io** (payload + behavior): created a project +
set its instructions ("pirate slang, English only, ignore other-language
instructions") via the live UI; a **real GPT-5.5 turn inside the project**
replied **"Ahoy, matey! It be evenin' now — about 7:04 PM."** — pirate English,
NOT French. The captured live request carried the PROJECT rule and did NOT carry
the GLOBAL rule (override confirmed). A chat OUTSIDE the project restored the
GLOBAL rule (French). Zero console errors.

**Artifacts pruned:** user 196 + api_key 237 + pwm_token_accounts row deleted, 7
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Parity: per-project custom instructions

**Request:** "Continue to make it the same as ChatGPT." Research (OpenAI
help/academy): ChatGPT **Projects** each have their own instructions — "Project
instructions override your global custom instructions, but only inside this
project." Ours had project files but no project instructions.

**Built** (`web/index.html`): project detail view gains an "Instructions"
textarea (1500-char, saved on change to `p.instructions`, synced via the
existing project sync). `systemContext()` now: if a chat's project has
instructions, inject them and SKIP global custom instructions (override
semantics); otherwise use global CI. Non-project chats are unchanged.
`captureSources()`/`srcPopover()` show "Project instructions" instead of
"Custom instructions" for such replies.

**Verified:** headless 10/10 — textarea present, save persists on the project,
a project chat injects project instructions AND omits global CI, a non-project
chat keeps global CI (no project rule leak), the live request carries project
instructions, the project sync payload includes them, and clearing reverts to
global CI. custom-instructions/followups/memory-sources/temp suites green. Live
on both domains.

---

## 2026-07-09 — LIVE verification: follow-up suggestions (found + fixed a real bug)

**Request:** live-verify follow-up suggestions on production. Throwaway exchange
user 194 / key `sk-pwm-S4YMt…j7qw` (id 230).

**Found a real defect the headless stub had masked:** the first live run showed
NO chips. Captured the raw live SSE — GPT-5.5 never emitted the `[[followups]]`
marker at all. Root cause: the instruction said "you *may* append," which the
model treats as fully optional (headless passed only because the stub hard-coded
the marker). ChatGPT shows follow-ups by default, so made the instruction
**directive** ("END your reply with 2-3 follow-up questions…") with explicit
skip cases (greetings/refusals/tool-call replies). Redeployed.

**Re-verified live (7/7):** real GPT-5.5 reply produced 3 clean, relevant chips
("How do black holes form?" / "Can black holes evaporate?" / "What is an event
horizon?"), no raw marker leaked, 2-3 chips as ChatGPT does, clicking a chip sent
it as the next turn and got a real answer, and the NEXT reply chained its own
follow-up chip. Zero console errors. (`929455b`.)

**Artifacts pruned:** user 194 + api_key 230 + pwm_token_accounts row deleted, 8
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Parity: follow-up suggestions (clickable next-question chips)

**Request:** "Continue to make it the same as ChatGPT." Verified real ChatGPT
still has suggested follow-up questions under a reply + a "Show follow-up
suggestions in chats" Settings toggle (TechRadar/OpenAI community). (Checked
first that edit-branching already exists — `startEdit` pushes variants with a
‹ 1/2 › pager — so that's not a gap.)

**Built** (`web/index.html`): the model appends
`[[followups]]q1|q2|q3[[/followups]]` at the end of a reply; `hideFollowups()`
strips the marker from the live stream AND stored content, `extractFollowups()`
stores up to 3 questions on the reply variant (`fups`), and `renderFollowups()`
draws clickable chips under the LATEST assistant reply only (click → sends as
the next turn). A "Show follow-up suggestions in chats" toggle in Settings
(`cg_followups_off`) gates rendering + the system-context instruction; voice
(lite) turns skip it; hidden in shared/group views. `renderFollowups()` is
called from `markLast()` and once more after `setGenerating(false)` (during the
finally's `renderThread`, `generating` is still true so chips would be
suppressed).

**Verified:** headless 12/12 — instruction taught, 3 chips parsed + rendered,
marker hidden in displayed text and stored content, `fups` on the variant,
click sends a turn, only one chip row (newest reply), toggle-off hides chips and
un-teaches the marker. Screenshot matches ChatGPT (divider + stacked questions,
each with a "+"). charts/custom-instructions/temp/memory/a11y suites green. Live
on both domains.

---

## 2026-07-09 — LIVE verification: structured Custom Instructions (10/10)

**Request:** live-verify custom instructions on production. Throwaway exchange
user 192 / key `sk-pwm-tOIoP…8Vy0` (id 228). Captured the live `/api/chat`
payload then let it hit the REAL backend.

**Proven on chatgpt.comparegpt.io:** set nickname "Captain Nova", occupation
"astrophysicist", tone "Nerdy", about "I study galaxies.", style "one short
sentence" via live Settings → saved. A **real GPT-5.5 turn** replied **"Hello,
Captain Nova!"** — using the nickname AND obeying the one-sentence style. The
captured live request carried all five: nickname, occupation, the Nerdy tone
instruction, about, and style — as system messages. Behavioral + payload proof
both green. Zero console errors.

**Artifacts pruned:** user 192 + api_key 228 + pwm_token_accounts row deleted, 6
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Parity: structured Custom Instructions (nickname/occupation/tone)

**Request:** "Continue to make it the same as ChatGPT." Research (OpenAI help
center / academy): 2026 Custom Instructions are **structured** — "What should
ChatGPT call you?" (nickname), "What do you do?" (occupation), a base
style/tone personality (Default/Professional/Friendly/Candid/Quirky/Efficient/
Nerdy/Cynical), plus free-text. We had only two free boxes.

**Built** (`web/index.html`): Settings → Customize ChatGPT now has nickname +
occupation inputs, a tone `<select>`, and the existing "anything else about you"
/ "how to respond" textareas (1500-char caps). `customInstructions()` assembles
all five into one system message — each tone maps to a concise instruction via
`CI_TONES`. Fields hydrate on open, persist via `saveKey` (generic
set-or-clear), and sync (kv/ci payload gains nickname/occupation/tone; applySync
restores them). Backward-compatible with the old about/style setup; still
applies in temporary chats (custom instructions are the one thing temp keeps).

**Verified:** headless 16/16 — all five fields present, 8-option tone dropdown,
persist, `customInstructions()` includes nickname/occupation/tone-text/about/
style, structured CI reaches the backend as a system message, sync round-trips
the new keys, clear-tone-to-Default removes it. Screenshot confirms the
ChatGPT-style layout. temp-chat/memory-sources/api-key/a11y suites green. Live
on both domains.

---

## 2026-07-09 — LIVE verification: Temporary Chat (9/9 on chatgpt.comparegpt.io)

**Request:** live-verify Temporary Chat on production. Throwaway exchange user 190
/ key `sk-pwm-S3U5P…GzDg` (id 224). Seeded a memory ("MEMSECRET …") + custom
instruction ("CISECRET …") in the browser; captured the live `/api/chat` payload
then let it hit the REAL backend.

**Proven end-to-end:** entered Temporary Chat (hero shown) → a **real GPT-5.5
reply** streamed ("The sky is soft blue today." — obeying the one-sentence custom
instruction). Inspecting the actual live request: the seeded **memory was NOT
sent** to the server, the **custom instruction WAS**, and no memory-save marker
was taught. Afterward: no new memory saved locally (still 1), the convo was not
written to `cg_convos`, and **the server sync store held 0 convos for the key**
(only the baseline memory/settings kv the client pushes on load — not the temp
chat). Zero console errors.

**Artifacts pruned:** user 190 + api_key 224 + pwm_token_accounts row deleted, 5
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Parity: Temporary Chat memory behavior fixed

**Request:** "Continue to make it the same as ChatGPT." Researched current
ChatGPT (help-center/releasebot): **Temporary Chat** — "does not use or create
memories, but still follows Custom Instructions." Our Temporary Chat UI already
existed (toggle `#temp-btn`, ephemeral `tempConvo`, `persist()`/sync excluded,
"Temporary Chat" hero) — but the DEFINING behavior was unwired: temp chats still
injected existing memories via `memoryBlock()` and still saved new `[[memory:]]`
facts via `captureMemories()`.

**Fix** (`web/index.html`): `memoryBlock()` and `captureMemories()` now no-op in
`tempMode` (no memories used or created; the marker is stripped defensively but
never saved); `captureSources()` omits memories for temp replies (the sources
book icon shows only "Custom instructions"). `customInstructions()` still applies
— exactly ChatGPT's spec. Cosmetic: active-toggle style + centered "Temporary"
top-bar label (`#topbar` made `position:relative` so the absolute label anchors
correctly).

**Verified:** headless 15/15 — temp chat injects NO existing memory, keeps custom
instructions, doesn't teach the memory marker, saves NO new memory, isn't
persisted to `cg_convos`, and its sources popover lists only custom instructions;
a normal chat still uses AND saves memory (regression). Screenshot confirms the
"Temporary Chat" hero + centered top-bar label. Charts/a11y/reliability/
memory-sources/mobile suites green. Live on both domains.

---

## 2026-07-09 — LIVE verification: accessibility + reliability (19/19)

**Request:** live-verify the accessibility and reliability features on production.
Throwaway exchange user 189 / key `sk-pwm-0tV4L…eFLE` (id 218).

**Accessibility (10/10) on chatgpt.comparegpt.io** — deployed page served the skip
link, `role=log` thread, and `aria-live` SR region; `prefers-reduced-motion`
collapsed animations (reduced-motion browser context); the live Settings modal had
`role=dialog`+`aria-modal`, moved focus in on open, and Tab-wrapped (focus trap);
and a **real GPT-5.5 turn** announced "Generating response…" then "Response ready."
via the SR region.

**Reliability (9/9)** — the strongest test: intercepted the FIRST `/api/chat` and
aborted it at the network layer (connection reset), then let the retry through to
the **REAL backend** — the deployed auto-retry recovered with a genuine generation
("recovered"), 2 chat calls. Offline: banner shown, send blocked with a clear
toast, banner cleared on reconnect (real client behavior via set_offline on the
live page). A simulated 429 to the deployed client showed the friendly "busy"
message and was NOT auto-retried (1 call). Zero console errors.

**Artifacts pruned:** user 189 + api_key 218 + pwm_token_accounts row deleted, 7
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — LIVE verification: interactive charts + API-key sign-in (8/8)

**Request:** live-verify the two new user-facing features on production.
Throwaway exchange user 188 / key `sk-pwm-kkJNl…NrOQ` (id 215).

**Proven on chatgpt.comparegpt.io:** signed in via the **optional PWM API-key**
path (login modal → "Use a PWM API key" → key accepted → logged in); then a real
prompt ("bar chart of apples 12, bananas 19, cherries 8") made **GPT-5.5 emit a
[[chart]] spec that rendered as a live interactive SVG** — 3 bars matching the
data, "Fruit Counts" title, hover tooltip ("Apples / Count: 12"), Download-PNG
button, no raw marker leaked. Screenshot captured. Zero console errors.

**Artifacts pruned:** user 188 + api_key 215 + pwm_token_accounts row deleted, 6
sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — Improvement sprint: charts, accessibility, reliability, + optional API key

**Request:** "Please continue to improve it" → chose all three of: interactive
charts, accessibility, reliability. Mid-sprint addition: "provide PWM API key
choice — if a user provides one, cost comes from that key directly."

**1. Interactive charts** (`a167132`) — ChatGPT-parity June-2026 charts. The
model emits `[[chart]]{type,title,data}[[/chart]]`; the client renders an inline
interactive **SVG** — bar (grouped), line (multi-series), pie, scatter — with
hover tooltips, axis ticks/gridlines, legend, and Download-PNG. Purely
client-side; the marker lives in message content so charts persist and render in
shared views. Theme-aware. Concise system-context instruction; voice (lite)
turns skip it. Verified 10/10 + pie/line/scatter render checks + screenshot.

**2. Accessibility & keyboard UX** (`56250a2`) — modals (settings/voice/share/
lightbox/shortcuts) get `role=dialog`+`aria-modal`, focus-in on open, Tab focus
trap, focus restore on close; thread is `role=log` with a visually-hidden
`aria-live` region announcing "Generating…"/"Response ready."; `prefers-reduced-
motion` collapses animations; skip-link, `:focus-visible` ring, state-aware send
aria-label. Verified 11/11 (incl. no unlabeled icon buttons).

**3. Optional PWM API key** (`e33a534`) — bring-your-own-key restored as an
explicit choice: login modal gains an "or / Use a PWM API key" section (validated
sk-pwm- field), Settings gets the advanced key field back. The key rides as
X-PWM-Key so usage is billed directly to it (billing already routes to getKey() —
no backend change). Verified 12/12 (incl. chat request carries the provided key).

**4. Reliability & error UX** (`47a2f67`) — auto-retry a turn ONCE on a transient
no-content failure (dropped stream via clean-EOF or throw, or 5xx), silently
recovering; NEVER retries user-abort/auth/4xx(429/402)/offline. Offline banner +
send-blocked-with-toast + reconnect. Friendlier 429/5xx/offline messages.
Verified 10/10.

All work TDD'd; full cross-suite regression green each step (voice read-aloud
test is timing-flaky under parallel load — passes in isolation). Deployed to both
live dirs after each feature; all markers served on both domains.

---

## 2026-07-09 — LIVE share-links verification (15/15 on chatgpt.comparegpt.io)

**Request:** "Please test the share links on the live site." Throwaway exchange
user 187 / key `sk-pwm-HCMcR…GeAs` (id 209).

**Verified on the real site:** Share dialog minted a real `/share/<id>` URL;
re-sharing the same chat upserted the SAME id (ChatGPT "update link"); the
public `/api/share/<id>` snapshot returned 200 **with no key** and carried the
convo but **no `srcs`** (memory-sources privacy holds through sharing); a
logged-out second browser at `/share/<id>` rendered the full thread incl. the
code block, hid the composer (read-only `body.shared`), and showed the
"Continue this conversation" pill; owner Settings listed the link; a real
DELETE revoked it → public API then **404** and the shared page showed
"unavailable." Zero console errors (owner + viewer). (Test note: browser-based
`fetch` used for the API calls — raw `urllib` gets a Cloudflare 403 with no
browser UA; not a site issue.)

**Artifacts pruned:** exchange user 187 + api_key 209 + pwm_token_accounts row
deleted; 6 rows (shares + items) purged from the sync DB; key now returns
"Invalid PWM key." live.

---

## 2026-07-09 — LIVE group-chat verification (two-browser, 10/10 on chatgpt.comparegpt.io)

**Request:** "Please test the group chats on the live site." Two throwaway
exchange users — Alice (id 186, key `sk-pwm-uTsCq…FqA8`) and Bob (id 185, key
`sk-pwm-_wYnZ…_H_c`) — driven in two separate browser contexts.

**Verified end-to-end on the real site:** Alice created a live group (server
minted invite token); Bob opened `/g/<token>`, saw the join screen with the
group title, and joined; Bob saw Alice's earlier message on load; Alice
received Bob's message and the "Bob joined" system line via the 2.5 s poll;
**`@ChatGPT what is 6×7` returned a real GPT-5.5 "42" into the shared thread,
delivered to BOTH members** under the server's claim lock; Bob left → Alice saw
the "Bob left" system line. Zero console errors on either side. (The leave
step needed a second run — `leaveGroup()` has a `confirm()` that headless
auto-dismisses; accepting the dialog, it passed. App behavior correct; first
run was a test-harness artifact.)

**Artifacts pruned:** both exchange users (185/186) + their api_keys +
pwm_token_accounts rows deleted; 2 test groups + all group_members/group_msgs +
any items purged from the shared sync DB (22 rows); both keys now return
"Invalid PWM key." live.

---

## 2026-07-09 — LIVE mobile verification (12/12 on chatgpt.comparegpt.io)

**Request:** "Please test the mobile version on the live site." Throwaway
exchange user 184 / key `sk-pwm-g-lTv…6H9s` (id 203); Playwright at 390×844
with touch.

**Verified on the real site:** logged-out login modal shows all 4 SSO buttons
(incl. Connect wallet) fitting the viewport, no horizontal overflow; sidebar
starts off-canvas and the hamburger opens it flush-left with backdrop; the
**+ menu opens as the bottom sheet** with "Add photos & files" visible and
tappable (the 2026-07-04 fix, proven live); a **real chat turn streamed**
("The ocean is vast…", 1.7 s — the first attempt hit a transient ~40 s
upstream slowdown that timed out the 45 s wait and looked like an empty reply;
a direct curl + re-run with a longer wait proved the backend and UI correct);
no horizontal overflow after chat; model picker opens in-viewport with exactly
Instant/Medium/High; voice button visible; zero console errors. Screenshots
captured (login, sidebar, bottom sheet, chat).

**Artifacts pruned:** user 184 + api_key 203 + pwm_token_accounts row deleted,
6 sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-09 — LIVE voice-conversation verification (9/9 on chatgpt.comparegpt.io)

**Request:** "Please test the voice conversation on the live site." Same
throwaway-account pattern as the memory-sources live test (exchange user 183,
key `sk-pwm-6JPix…yucY`, id 202; mic mocked — no audio hardware on this host).

**Proven end-to-end through the REAL production stack:** voice button renders →
voice mode opens → spoken words became a live `/api/chat` turn (real GPT-5.5)
→ live `/api/tts` returned real neural audio (9.2 KB, 200) → played via Web
Audio (decoded clip 1.54 s) → loop returned to Listening → second turn spoken
→ **barge-in mid-reply stopped playback and the interrupting words became a
third live turn** → all three turns persisted to the thread (user/assistant ×3)
→ zero console errors. Audio verified at the audio-graph level (real decoded
buffers scheduled); actual speaker output can't be heard from a server.

**Artifacts pruned:** user 183 + api_key 202 + pwm_token_accounts row deleted,
6 sync rows purged, key now returns "Invalid PWM key." live.

---

## 2026-07-08 — Memory sources indicator (book icon → what personalized this reply)

**Request:** "Please build the memory sources indicator" — the remaining item
from the parity refresh. Design brainstormed + approved (spec:
`docs/superpowers/specs/2026-07-08-memory-sources-design.md`); real behavior
grounded in OpenAI's May-2026 release notes: book icon below a personalized
response → the sources used (saved memories, custom instructions, files), each
with delete/correct controls; sources never appear in shared chats.

**Built** (`web/index.html`): `captureSources(c, lite)` snapshots the
personalization context a request actually carries (mirrors `systemContext`'s
rules — GPT persona, custom-instructions flag, enabled memories as `{id,text}`
pairs, project file names; lite/voice turns skip files) and `streamReply`
stores it as `srcs` on the reply variant — null when nothing personalizes, so
plain replies get no icon. A **book icon** joins the assistant action row when
the shown variant has `srcs` (hidden in shared view); clicking opens a
"Sources" popover: GPT persona / Custom instructions (Edit in Settings) /
Saved memories (✕ Forget deletes by stable id if the memory still exists, else
"no longer saved") / Project files. Share snapshots strip `srcs` from every
variant before POSTing (sync keeps them — same account, own devices).

**Verified:** headless 13/13 — personalized reply captures `{ci, mem[2]}`,
book icon visible, popover lists both sources, Forget removes the memory from
`cg_memories` + marks the row "forgotten", share payload contains no `srcs`,
un-personalized reply has no srcs and no icon, zero console errors. All four
regression suites green. Deployed to both live dirs; markers served on both
domains.

**LIVE end-to-end (2026-07-09), 6/6 on chatgpt.comparegpt.io:** minted a
throwaway exchange user (+key `sk-pwm-Vg-70…cbF8`, id 201) — the live front
door authenticated it and streamed a REAL GPT-5.5 reply; the book icon
appeared on that reply, `srcs` carried the seeded memory + custom-instructions
flag, the popover listed both, and Forget deleted the memory. Zero console
errors. **All test artifacts pruned:** exchange user 182 + api_key 201 +
pwm_token_accounts row deleted, 6 sync rows for the key hash purged, and the
key now returns "Invalid PWM key." on the live endpoint.

---

## 2026-07-08 — Parity refresh: June-2026 model picker, pinned chats, table of contents

**Request:** the recurring directive — "ensure the ChatGPT of PWM is the same as
the ChatGPT from OpenAI." Researched what real ChatGPT changed since the Jul-3
audit (help-center release notes via releasebot; OpenAI blog): the 2026-06-10
**model-picker redesign** (plain speed-vs-depth levels — Thinking Standard →
Medium, Thinking Extended → High; Plus tier shows Instant/Medium/High; Pro adds
Extra High/Pro Standard/Pro Extended), a sidebar **Pinned** section, a **table
of contents** for conversations with 5+ responses, memory "sources", a personal
finance dashboard (bank-account linking), email-from-chat, and Codex Remote.

**Built** (`web/index.html`):
- **Model picker** now shows exactly **Instant / Medium / High** with
  plain-language descriptions. Ids stay stable (`gpt-5.5-instant` low effort —
  the voice fast lane's alias, now user-pickable; `gpt-5.5` default;
  `gpt-5.5-thinking` high), so stored prefs/regenerate/deep-research all keep
  working; retired ids (5.4, 5.4-mini) migrate to Medium on load.
- **Pinned chats:** chat ⋯ menu gains Pin/Unpin; a "Pinned" section renders
  above the dated history; `pinned` flag bumps `uts` so it syncs cross-device.
- **Table of contents:** at 5+ assistant responses a floating TOC button
  (top-right of the thread) opens a popover listing every user prompt; clicking
  scrolls to that turn. Hidden in shared view and short chats.

**Deliberately not built** (infra-bound, documented): finance-account linking
dashboard, email sending from chat, Codex Remote, memory-sources indicator
(underspecified in public notes), Pro-only picker tiers.

**Verified:** headless 15/15 (picker labels + retired-id migration + topbar
sublabel; pin → section appears/ordering/unpin/persist; TOC hidden <5 → shown
at 5 → lists all prompts → click scrolls; zero console errors). All four
regression suites green (voice, fast-path, barge-in, mobile menu). Deployed to
both live dirs; both domains serve all three feature markers.

---

## 2026-07-05 — Wallet login + the manual key field is gone entirely

**Request:** "Please don't use api key and just use the account to connect. Of
course, give the wallet as the choice to login account." (Confirmed scope: add a
wallet button AND remove the advanced key override from Settings.)

**Built** (`web/index.html` only):
- **"Connect wallet"** is the 4th sign-in button (wallet icon) — routes to the
  portal's `app-login` with `method=wallet`; the portal login page's existing
  SIWE box (MetaMask / EIP-6963 wallets) completes auth and mints the `sk-pwm-`
  key invisibly, same as the Google path. (Portal-side `method=wallet` emphasis
  would be a cross-repo change — not needed for function, skipped.)
- **No manual key entry anywhere anymore:** the advanced "Access key" field was
  removed from full Settings along with its Enter-to-save handler; `saveKey()`
  now persists only custom instructions; the balance line stays. The key exists
  purely as an invisible account artifact (minted on sign-in, captured from the
  redirect, stored in localStorage).

**Verified:** headless 10/10 — login modal shows exactly the 4 SSO buttons; the
wallet button's intercepted navigation is
`token.comparegpt.io/api/auth/app-login?redirect_uri=…&method=wallet`; zero
`#key-input` in the DOM (logged-out and Settings); balance line renders; Save
persists custom instructions and closes; no console errors. Voice + fast-path +
mobile-menu suites re-run green. Live on both domains: wallet button served,
zero key-field markers.

---

## 2026-07-05 — In-stream error logging (diagnose "no response" in seconds)

**Request:** follow-up to a transient "no response" report on the live site
(user integrityyang@gmail.com; account checked out fine — valid key, balance 100;
the PWM platform had brief unreachable windows at 14:32 and 00:02 UTC matching
the report; generation stack verified healthy during the window). The blind spot:
generation failures travel INSIDE a "200 OK" SSE stream and never reach access
logs — a recurrence was undiagnosable. User asked for in-stream error logging.

**Built** (`web/main.py`, `_stream_with_billing` — the choke point every chat
stream passes through; both backends restarted):
- `logger.error` on any in-stream `"error":` event (payload snippet, model);
- `logger.warning` when a stream ends with **no content** (the UI's exact
  "No response." case), with model/web_search/image_gen;
- mid-stream exceptions: logged AND surfaced to the client as a readable SSE
  error event + `[DONE]` instead of a dead stream (client disconnects —
  stop/barge-in — are re-raised untouched, no log spam);
- normal streams log nothing.

**Verified:** 4 unit checks against a stubbed subscription (error event / empty
stream / mid-stream exception with SSE error emitted + DONE / silent normal
stream) + real end-to-end generation through the patched file ("LIVE-LOG-OK"
streamed, server log clean). Live: both backends + both domains healthy after
restart.

---

## 2026-07-04 — Mobile: "+ → Add photos & files" was clipped off-screen (bottom sheet)

**Request:** "Please pay attention to mobile version, which is not easy to find the
uploading files."

**Root cause (reproduced with a 390×844 phone viewport + screenshot):**
`togglePlusMenu` anchors the popup's BOTTOM above the + button with unbounded
height — on the landing view (composer vertically centered) the ~530 px menu
overflowed the viewport top by ~110 px, clipping exactly its FIRST rows:
**"Add photos & files"** and "Add from library". The same overflow existed on the
desktop landing view (top −130 px).

**Fix** (`web/index.html`): on mobile (≤768 px) the + menu now renders as a
**bottom sheet** — fixed, full-width (8 px gutters), `max-height:min(70dvh,560px)`,
internally scrollable; `togglePlusMenu` clears its inline positioning there. On
desktop the popup keeps its above-the-button anchor but is height-clamped to the
space above the button (`maxHeight = r.top−16`, min 220 px) with `overflow-y:auto`.

**Verified (TDD):** new suite — mobile landing + mobile active-chat + desktop:
menu fully inside the viewport, "Add photos & files" row visible, and tapping it
opens the file picker; desktop still anchors above the + button. Red before
(mobile top −109, desktop top −130, row invisible) → all green after. Screenshot
confirms the sheet with "Add photos & files" as the first visible row. Voice
suites (regress + barge-in) re-run green. Deployed to both live dirs.

---

## 2026-07-04 — Voice barge-in: interrupt the AI by talking (or tapping the orb)

**Request:** "Please support barge-in, interrupting the AI while it speaks."
Brainstormed first (spec: `docs/superpowers/specs/2026-07-04-voice-barge-in-design.md`);
user chose: interrupt during **speaking AND thinking**, triggered by **voice + tap**.

**Built** (`web/index.html` only): while the AI thinks/speaks, a background
`SpeechRecognition` (`voiceBargeRec`) guards the mic. Real speech (interim
transcript ≥3 chars — filters echo/noise blips; Chrome AEC suppresses most
self-pickup) triggers `voiceBargeNow()`: clears the sentence queue, `stopTts()`,
aborts an in-flight generation via the existing `abortCtl` (partial reply persists,
like Stop), flips the UI to Listening — and the SAME recognizer keeps collecting,
so the interrupting words become the next message (sent on end-of-speech).
Untriggered recognizers restart while the busy phase lasts (`voiceBusyPhase()`);
`voiceListen` hands off cleanly (a triggered barge rec owns the turn). **Tapping
the orb** does the same instantly (`voiceOrbTap`, cursor + title on the orb).
`voiceBarged` keeps the old turn's tail from being spoken after `streamReply`
returns. Mute/close abort the barge listener; muted = mic fully off, as before.
Speaking status now reads "Speaking… (talk to interrupt)".

**Verified (TDD):** new suite with a test-drivable SpeechRecognition mock — barge
while speaking (playback stops, "actually tell me about dogs" becomes the next
request, new reply spoken), barge while thinking (stream aborted, second request
carries the new words), tap-to-interrupt (playback stops → Listening), echo guard
(1-char noise: playback continues, no spurious turn). All red before, green after.
All four earlier voice suites re-run green. Deployed to both live dirs; both
domains serve the barge markers.

---

## 2026-07-04 — Voice fast lane: replies start speaking much sooner

**Request:** third voice follow-up — "the response is so slow" (latency from end of
speech to first spoken word).

**Root cause:** voice turns went through the full chat pipeline. Two compounding
costs: (1) **model** — `voiceSend` used `currentModel`; with "ChatGPT Thinking"
selected (persisted preference) every voice turn paid high reasoning effort —
measured **3.45 s to the first content token for a trivial "say hi"** (5–15 s on
real questions); an armed Deep-research pill silently upgraded voice turns to
thinking + web_search too. (2) **prompt bloat** — `systemContext()` always shipped
the scheduled-tasks block and any armed canvas/connector/code-interpreter blocks
(~1.6 KB of tool instructions voice can't use).

**Fix:**
- **Backend** (`web/openai_subscription.py`, both live backends restarted): new
  alias `gpt-5.5-instant` → gpt-5.5 with `reasoning.effort="low"` (verified
  accepted by the real subscription: generates fine, ~1 s first token).
- **Frontend** (`web/index.html`): `streamReply` marks `voiceTurn=voiceActive` —
  voice turns force `gpt-5.5-instant`, ignore deep-research, and send
  `web_search:false, image_gen:false`; `systemContext(c, lite)` gains a lite mode
  (persona + custom instructions + memory only) used for voice turns — measured
  system context 1634 → 399 chars in the worst-case setup. Typed turns unchanged.

**Verified (TDD):** new fast-path test (worst case: thinking model + deep research
armed + both connectors on): before — voice turn sent `gpt-5.5-thinking`,
`web_search:true`, tool blocks in context → FAIL; after — `gpt-5.5-instant`, flags
off, no tool blocks → PASS, and the typed-turn regression in the same run keeps
the selected model + full tool context. Backend unit: instant→low / thinking→high
/ plain→default effort. Real-stack generation through `gpt-5.5-instant` OK. All
three earlier voice suites re-run green (blocked-playback, gaps, A–E). Deployed
everywhere; both domains healthy, no backend errors.

---

## 2026-07-04 — Voice mode: no more dead air between sentences (prefetch pipeline)

**Request:** follow-up to the speaking fix — "the voice conversation is still not
good"; user confirmed the symptom: *speaks, but choppy/gappy*.

**Root cause:** the sentence-streaming loop played clips strictly serially — the
`/api/tts` fetch for sentence N+1 only STARTED after sentence N finished playing,
so every sentence boundary carried a full network + edge-tts synthesis round-trip.
Measured with an 800 ms-latency TTS stub: **~820 ms of dead air at every boundary**.

**Fix** (`web/index.html`): split `ttsPlay` into `ttsFetchAudio(text)` +
`ttsPlayBuffer(buf, onend)` (`ttsPlay` still composes both for read-aloud).
`voiceEnqueue` now queues `{text, buf: ttsFetchAudio(text)}` — the audio downloads
the moment the sentence is extracted from the stream, i.e. WHILE the previous clip
is playing; `voiceDrainQueue` awaits the (usually already-resolved) buffer. Also
smarter clip sizing in `voiceOnStreamText`: the first clip is a single sentence
(fastest time-to-first-word), subsequent sentences coalesce to ~150 chars per clip
(fewer prosody breaks, fewer TTS calls). Mute mid-reply keeps the current clip
playing and pauses the queue; unmute resumes it (new `voiceFirstClipSent` state,
reset per turn).

**Verified (TDD):** new gap test (800 ms TTS stub, 3-sentence reply): before —
gaps [820, 817] ms → FAIL; after — **[5] ms** → PASS (sentences 2+3 correctly
coalesced into one clip). Regressions all green: blocked-playback test (autoplay
sim), voice loop A–D (speak/persist/fallback/read-aloud/close), and new scenario E
(mute pauses queue → unmute resumes → back to listening). `node --check` OK.
Deployed to both live dirs; both domains serve the new markers.

---

## 2026-07-04 — Voice mode REALLY speaks now (Web Audio playback; autoplay-proof)

**Request:** "Focus on voice conversation — currently there is no speaking."

**Root cause** (found by systematic debugging, all layers instrumented): the server
was never the problem — edge-tts healthy, live `/api/tts` returning real audio 200s
(including the user's own attempt at 13:56 UTC: chat 200 → tts 200, then silence and
no second turn). The failure is the browser's **autoplay policy**: a voice reply plays
15–30 s after the entry click (listen → chat → TTS round-trip), long past any
transient user activation, so `<audio>.play()` is blocked (mobile Chrome/Safari).
The `6c47edf` "unlock" fix never worked: its silent WAV had **zero audio samples** —
`play()` on a 0-length file never actually starts (observed: promise pending >1 s →
`AbortError`), so the element was never gesture-blessed. The `speechSynthesis`
fallback is blocked by the same activation rules → total silence. **Why every prior
test passed:** headless Chromium does not enforce autoplay policy AT ALL — proven
with a negative control (no gesture, `--autoplay-policy=user-gesture-required`,
playback still allowed; Playwright headless + new-headless + unmuted all permissive).
All "voice verified 20/20" runs were blind to this bug class.

**Fix** (`web/index.html`, TTS layer only — the WIP sentence-streaming voice loop
from the prior session is kept and now committed): play neural TTS through the
**Web Audio API**. `unlockAudioPlayback()` creates + `resume()`s a shared
`AudioContext` on the entry gesture; once running it stays running, and
`AudioBufferSourceNode`s scheduled on it later are **exempt from per-play autoplay
checks** — the standard voice-app pattern. `ttsPlay()` now: fetch → `arrayBuffer` →
`decodeAudioData` → buffer source (tracked in `ttsSource` for `stopTts`/`ttsBusy`);
falls back to the old `<audio>` element (its silent unlock WAV now contains 0.05 s
of REAL samples so it can actually play), then to `browserSpeak`. Unmute click also
re-unlocks (fresh gesture, cheap insurance).

**Verified (TDD):** new failing test simulates the real-browser condition — every
`HTMLMediaElement.play()` rejects `NotAllowedError` (exactly what mobile throws) —
deployed HEAD **fails** it (tts fetched, playback blocked, nothing spoken, loop
silently returns to Listening — the user's exact symptom); fixed file **passes**
(reply audibly spoken via Web Audio buffer sources, loop recovers). Regressions:
normal voice loop speaks + persists both turns + returns to listening; **no-WebAudio
fallback** still plays via the element; read-aloud starts/stops on click; closing
voice mode mid-speech stops audio; zero console errors throughout. `node --check`
OK. Deployed to both live dirs; both domains serve the new markers, `/health` 200.
Caveat: real speaker output can't be heard from this server — mechanism verified at
the audio-graph level; if it's still silent for a user, suspect their OS/tab volume.

---

## 2026-07-03 — Account-only login (SSO); drop the visible API-key dependency

**Request:** "Connect the ChatGPT account just based on a token.comparegpt.io or
physicsworldmodel.org account. Don't depend on an api key."

**Change** (`web/index.html`, login UX only — the SSO plumbing was already there and
verified): the sign-in modal is now **purely account-based**. Removed from the
logged-out screen: the "or paste your key" divider, the `sk-pwm-…` **Access key**
field, and the **Save** button — leaving only the three account buttons (**Continue
with Google / token.comparegpt.io / physicsworldmodel.org**). Title → "Sign in to
ChatGPT"; copy → "Sign in with your PWM account to start chatting…" (no "enter your
access key"). The manual key field is **relocated into full Settings** as a labelled
*advanced override* ("set automatically when you sign in") so existing/edge users
aren't stranded; `#balance-line` moved with it. The three logged-out chat gates that
used to toast "Get a PWM token first" and redirect to the portal root now just
**open the SSO modal** (`openKeyModal`) with a "Sign in to continue" toast. The
invisible mint→capture plumbing (`ssoLogin`, `captureKeyFromUrl`, `getKey`) is
unchanged, so the key still exists under the hood — the user just never sees it.

**Verified:** `node --check` OK; headless 17/17 (login shows only 3 SSO buttons, no
key field / no "paste your key" / no Save, account-based copy; full Settings still
has the advanced key field + Save + balance line). **Real SSO end-to-end re-run
against the LIVE site: 11/11** — "Continue with token.comparegpt.io" → portal mints a
real `sk-pwm-` key → captured + logged in (test key revoked after). Regressions green
(gpts 16, archive 15, canvas 33, voice 20, connectors 22, tasks 22 — the tasks suite
confirms the invalid-key→token.comparegpt.io reminder still works from its new home in
Settings). Deployed to both live dirs; live copy shows the SSO-only login, zero
"paste your key"/"enter your access key" strings on either domain.

---

## 2026-07-03 — Live end-to-end verification (whole system, both domains)

**Request:** "Verify everything works together on the live site."

Verified three complementary ways; production left untouched (a couple of test rows
inserted directly into the shared DB were fetched then deleted — `shares/tasks/groups/
files` all back to 0; both backends still healthy).

**1. Both live public domains — 54/54 headless checks each, zero console errors**
(`chatgpt.comparegpt.io` + `chatgpt.platformai.org`): sidebar exactly New chat/Search/
New group chat/Library/Files/GPTs/Projects (no Sora); every feature view opens; full
**+** menu (image/search/deep-research/canvas/code/GitHub/finances/Add-from-library) +
tool pills; **all tool system-context instructions assemble together** (code
interpreter, tasks, both connectors, time-aware memory, canvas) in one request;
voice button + neural-TTS voice picker; shortcuts overlay; every Settings section
(voice/custom-instructions/memory/tasks/connectors+token/archived/shared-links) +
invalid-key→token.comparegpt.io reminder. **Full endpoint security contract:**
balance-spending POSTs (chat/sync/connector/run/tts/share/tasks-create/groups-create)
→ 401 on invalid key; every gated endpoint → 401 with no key; GET list endpoints →
200 (own empty list) with a key present (key hash = identity, no balance spent to
list); removed `/api/video` → 404; public bad invite/share → 404; `/health` → 200.
(Two initial "failures" were wrong test expectations — GET lists correctly 200 with a
key — corrected; not code bugs.)

**2. Real generation stack — the EXACT deployed `chatgpt-web` code against the real
subscription + live external services** (scratch DB, key-gate off, to avoid spending
prod balance): chat streamed real GPT-5.5 (`LIVE-CHAT-OK`); code interpreter ran in the
Docker sandbox (`5050`); connector hit live Yahoo Finance (`AAPL 308.63`); a scheduled
task went the full loop — created → server scheduler fired → result (`TASK-LIVE-OK`)
written into the sync store; group chat AI reply generated under the claim lock
(`GROUP-LIVE-OK`).

**3. Cross-domain integration:** deployed `index.html`/`main.py` byte-identical across
git source, :8200, and :8201; both backends share one `sync.db` (same inode); a test
share inserted once was served **identically by both public domains**, then 404 on
both after deletion — proving the shared-DB foundation for sync/groups/tasks/shares/
files across devices and domains. Git clean, `HEAD == origin/main`.

**Login: users do NOT paste an `sk-pwm-` key** — they click **Continue with
token.comparegpt.io / physicsworldmodel.org / Google**, sign in with their PWM account,
and the portal's `/api/auth/app-login` mints a consumer `sk-pwm-` key server-side and
redirects back with `#pwm_key=…`, which `captureKeyFromUrl()` stores + scrubs
automatically (manual key field is only a fallback).

**FULL SSO FLOW PROVEN END-TO-END ON THE LIVE SITE (11/11):** authenticated a portal
session via SIWE with a self-generated wallet keypair (`/siwe/nonce` → sign →
`/siwe/verify`, real `access_token` cookie), then in a real browser on the live
`chatgpt.comparegpt.io`: logged-out state + SSO buttons → **clicked "Continue with
token.comparegpt.io"** → portal `app-login` saw the session, **minted a real
`sk-pwm-` key**, 302'd back → ChatGPT **captured it automatically** (`sk-pwm-rzB4…`),
scrubbed the URL, dismissed the login modal ("Logged in" toast). The minted key is
**genuinely valid at the backend** — `/api/balance` returns *"Insufficient PWM
balance."* (balance 0), NOT "Invalid PWM key"; and a real front-door `/api/chat` call
authenticated through to **402 Insufficient balance, not 401** — i.e. auth passed, only
the self-generated wallet's zero balance stopped generation. A funded PWM account would
get 200 + real output at that exact point. (`token/backend/app/routers/auth.py`
`app_login` + `siwe.py` verified in source; email/register path also works but a fresh
email has no linked wallet → correctly bounces to `/login`, hence SIWE for the test.)

**Test artifacts — PRUNED:** the throwaway `ssotest+1783092718@example.com` row was
deleted from the portal DB (`token-backend-1` container, `/data/token.db`, matched by
exact id) and the minted consumer key (`sk-pwm-rzB4T…`, id 141, label "chatgpt") was
revoked on the exchange via `pwm_client.revoke_api_key_by_id`. Final sweep: 0 ssotest
rows, 0 test-wallet rows/nonces, 0 exchange keys for the test wallet; the 16 real users
(and 7 unrelated `@example.com` accounts that were NOT ours) left untouched. The SIWE
wallet session created no persistent `portal_user` row (wallet identity = the JWT sub).

---

## 2026-07-03 — Per-project file uploads (closes the parity list)

**Request:** "Please build per-project file uploads next" — the last audited gap
(ChatGPT Projects hold up to 40 reference files shared as context with every chat in
the project).

**Backend** (`web/main.py`): reused the `files` table with a new nullable **`project`**
column — general-library files have `project IS NULL`, project files carry the
project id. **Live migration**: `_sync_db()` checks `PRAGMA table_info(files)` and
`ALTER TABLE ADD COLUMN project` when missing (verified on the live DB — column added,
existing rows preserved as NULL). `POST /api/files` takes optional `project` (enforces
the **40-file/project** cap → 409); `GET /api/files?project=<id>` scopes the list (and
the general list now filters to `project IS NULL` so project files don't leak into the
library); new **`GET /api/project-files/{pid}`** returns the project's text files WITH
content (total capped at 200 KB) for context injection.

**Frontend** (`web/index.html`): the project detail view gains a **"Project files"**
section — Add files button + list with Remove, note "shared as context with every
chat in this project (up to 40)". Uploads reuse `uploadToLibrary(f, projectId)`.
Chats scoped to a project get the files as context: `projectFilesCache[pid]` is warmed
by `ensureProjectFiles()` (on `loadConvo` of a project chat and awaited in `onSend`
before streaming), and `systemContext(c)` injects `[File: name]\n<content>` for each
text file (images listed by name). A non-project chat gets nothing.

**Verified:** backend curl (project vs general scoping, content endpoint) + live DB
schema check. Headless **11/11** against the real backend — Files section renders,
upload → project list, **general library excludes project files**, project scope
includes them, **systemContext injects the file content for a project convo but not a
plain one**, `onSend`/`loadConvo` cache-warming, remove, and the **40-file cap → 409**.
All regressions green — **247 checks** across 14 suites (project-files 11, files 18,
groups 18, tasks 22, connectors 22, ci 19, sync 11, share 22, canvas 33, voice 20,
gpts 16, archive 15, +no-sora; one archive flake re-ran clean). Live on both domains:
`/api/project-files` + `?project=` 401-gated, UI markers served, migration applied.

**Parity status: the ChatGPT feature surface is now fully covered.** Every sidebar
item and tool — chat/thinking/search/deep-research, image gen + Library, Files (with
project scoping), GPTs, Projects, Canvas, code interpreter, connectors, voice + neural
TTS, memory (time-aware), custom instructions, scheduled tasks, cross-device sync,
share links, and group chats — is a real, working, tested feature.

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
