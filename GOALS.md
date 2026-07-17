# chatgpt-pwm Goals: Reaching ChatGPT Parity

> **Mission:** Give PWM users a ChatGPT experience indistinguishable from OpenAI's — on the same underlying models, at predictable PWM cost, on an open stack.

Last updated: 2026-07-17

---

## Contents

1. [Tier 1 — Core Features](#tier-1--core-features-mostly-done)
2. [Tier 2 — Experience Quality](#tier-2--experience-quality)
3. [Tier 3 — Nice-to-Have](#tier-3--nice-to-have)
4. [Weekly Health Dashboard](#weekly-health-dashboard)
5. [Monthly Goals: Aug / Sep / Oct 2026](#monthly-goals)
6. [Competitive Positioning](#competitive-positioning)
7. [Drilldowns](#drilldowns)
8. [Risks & Mitigations](#risks--mitigations)
9. [Decision Gates](#decision-gates)
10. [Measurement Toolkit](#measurement-toolkit)

---

## Tier 1 — Core Features (mostly done)

Every feature here has a **status** (✅ Done / ⚠️ Gap / 🚫 Blocked), a one-line
**verification** (the test that proves it), and a **gap** (what's missing).

### 1.1 Chat UI & Streaming

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| SSE streaming with live markdown | ✅ | `live_sweep.py` item 1 (normal chat) | — |
| KaTeX math (inline + display) | ✅ | `test_math.py` 7/7; `test_stream_math.py` 4/4 | — |
| GFM task-list checkboxes | ✅ | `test_tasklist.py` 6/6 | — |
| Syntax-highlighted code fences | ✅ | 54/54 headless on both domains (2026-07-03) | — |
| Escape stops generation | ✅ | `test_esc_stop.py` 5/5 | — |
| ↑ in empty composer edits last message | ✅ | `test_uparrow_edit.py` 5/5 | — |
| Select-text-to-quote | ✅ | `test_quote.py` 7/7 | — |
| Branch in new chat | ✅ | `test_branch.py` 9/9 | — |
| Regenerate with model picker | ✅ | Full headless + live regression | — |
| Thumbs-down feedback dialog | ✅ | `test_feedback.py` 11/11 | — |
| Reply links open in new tab | ✅ | `test_links_archive.py` 8/8 | — |
| Continue generating | ✅ | `test_continue.py` 8/8 (stub) | Cannot be force-triggered — upstream rejects `max_output_tokens`; button fires only on natural truncation |

**Pass/fail gate:** `live_sweep.py` 10/10 on both public domains.

---

### 1.2 Model Picker

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| GPT-5.6 Sol / Terra / Luna | ✅ | LIVE 8/8 (real generation per tier) | — |
| GPT-5.5, GPT-5.4 | ✅ | LIVE 12/12 (MODEL55-OK / MODEL54-OK) | — |
| Auto-switch to Thinking | ✅ | `test_auto_think.py` 10/10; LIVE 6/6 | Heuristic-based; may over- or under-escalate — no ground-truth eval yet |
| Reasoning duration ("Thought for N s") | ✅ | `test_think_time.py` 7/7; LIVE 5 s label | — |

**Pass/fail gate:** picker lists all 5 models; each routes a real turn to its exact slug.

---

### 1.3 Canvas

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Doc canvas (Polish / Shorter / Longer / Simplify / Add emojis) | ✅ | `test_canvas_chips.py` 5/5 | — |
| Code canvas (Add comments / Fix bugs / Code review / Optimize / Add logs) | ✅ | `test_canvas_chips.py` 5/5 | — |
| HTML canvas with live sandboxed iframe | ✅ | `test_canvas_html.py` 10/10; LIVE interactive counter | iframe lacks `allow-same-origin` → generated apps can't use localStorage |
| Version history / edit mode | ✅ | 33/33 canvas suite (2026-07-03) | — |

**Pass/fail gate:** an HTML canvas prompt produces an interactable rendered page; code/doc chips fire correctly.

---

### 1.4 Voice

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Full-screen voice conversation loop | ✅ | LIVE 9/9 (real GPT-5.5 + real TTS) | — |
| Neural TTS (edge-tts, Web Audio) | ✅ | LIVE (9.2 KB audio, 1.54 s clip) | Autoplay on mobile verified at the audio-graph level; actual speaker output can't be heard from server |
| Barge-in (voice + orb tap) | ✅ | LIVE 9/9 (two-turn barge) | Chrome AEC may allow echo pickup on some devices |
| Voice fast lane (gpt-5.5-instant, low effort) | ✅ | Fast-path test: force instant+no-tool-bloat | — |
| Prefetch pipeline (no sentence-boundary gaps) | ✅ | Gap test: [5 ms] vs [820 ms] before | — |
| Read-aloud for any reply | ✅ | Voice suites A–E | — |
| Dictation into composer | ✅ | 54/54 headless (2026-07-03) | — |
| Full-duplex GPT-Live voice | 🚫 | Not built | Requires OpenAI's Realtime API — infra-bound, no ETA |

**Pass/fail gate:** end-to-end voice loop (listen → generate → speak → barge-in) with no dead air between sentences, verified on production with a real GPT-5.5 turn.

---

### 1.5 File Upload & Library

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Inline upload (images, PDF, DOCX, text) | ✅ | 18/18 files suite | — |
| Persistent file library (cross-device) | ✅ | Server-side persistence across reload | Max 100 files / 8 MB per file / 60 MB total per user |
| Add from library in composer | ✅ | Picker overlay test | — |
| Per-project files (up to 40) | ✅ | 11/11 project-files suite | — |
| Image library (generated images) | ✅ | 54/54 headless (2026-07-03) | — |

**Pass/fail gate:** upload a file, reload, attach it from the library in a new chat — model sees the content.

---

### 1.6 Projects

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Project creation / grouping | ✅ | 54/54 headless | — |
| Per-project files (up to 40, shared context) | ✅ | 11/11 project-files suite; systemContext injection | — |
| Per-project custom instructions | ✅ | LIVE 8/8 (project overrides global CI; pirate English vs French) | — |

**Pass/fail gate:** a chat inside a project uses the project's instructions; a chat outside uses global CI; project files appear in context.

---

### 1.7 Custom GPTs

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Create / edit GPT (name, desc, instructions) | ✅ | 16/16 gpts suite | — |
| Conversation starters + knowledge text | ✅ | 14/14 (2026-07-10) | — |
| Knowledge file attachments (from library) | ✅ | LIVE 6/6 (secret only from file) | — |
| Custom profile picture | ✅ | `test_gpt_icon.py` 12/12; LIVE sync round-trip | — |
| @-mention a GPT inline | ✅ | LIVE 7/7 (pirate persona confirmed live) | — |
| Share a GPT via link | ✅ | LIVE 7/7 (two-browser share → import) | — |
| Explore GPTs catalog (12 curated) | ✅ | LIVE 6/6 (Math Tutor persona confirmed live) | No live marketplace — curated built-in only |
| Live GPT Store marketplace | 🚫 | Not built | Requires OpenAI's GPT Store backend |

**Pass/fail gate:** create a GPT with a secret in its knowledge, ask the secret inside the GPT, confirm it's answered; ask in a plain chat, confirm it's NOT.

---

### 1.8 Memory & Personalization

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Memory across chats (save / forget) | ✅ | 54/54 headless | — |
| Time-aware memory (date-stamps, past plans) | ✅ | 22/22 tasks suite | — |
| Memory sources indicator (book icon) | ✅ | LIVE 6/6; `captureSources` 13/13 | — |
| Structured custom instructions (nickname / occupation / tone) | ✅ | LIVE 10/10 (nickname + one-sentence style confirmed live) | — |
| Temporary chat (no memory, keeps CI) | ✅ | LIVE 9/9 (memory absent, CI applied) | — |

**Pass/fail gate:** seed a memory, start a new chat, confirm the model uses it; start a temporary chat, confirm it does NOT.

---

### 1.9 Sync & Cross-Device

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Cross-device sync (chats, projects, GPTs, memory, CI) | ✅ | Cross-domain integration (same SQLite inode) | — |
| Both public domains in sync | ✅ | 2026-07-11 deploy verification (byte-identical, both backends healthy) | Must restart `chatgpt-pwm-dev.service` (NOT `pkill`) for backend changes on 8201 |

**Pass/fail gate:** create a convo on chatgpt.comparegpt.io, reload on chatgpt.platformai.org — same convo appears.

---

### 1.10 Share Links

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Publish read-only share link | ✅ | LIVE 15/15 (mint → view → revoke) | — |
| Share from sidebar (not just header) | ✅ | `test_sidebar_share.py` 5/5 | — |
| "Continue this conversation" for viewers | ✅ | 15/15 headless | — |
| Memory sources stripped from shares | ✅ | No `srcs` in share payload | — |

**Pass/fail gate:** share a chat, open link in a private window — renders full thread, no composer, "Continue" pill present; revoke → 404.

---

### 1.11 Web Search

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Real-time web search | ✅ | LIVE (population of Tokyo, 2 inline citations) | — |
| Inline numbered citations (¹) at correct offsets | ✅ | `test_citations.py` 10/10 (including favicon + domain tooltip) | — |
| Source card list with favicons | ✅ | LIVE; favicon from `<host>/favicon.ico`, onerror fallback | — |
| Deep research (multi-step, high reasoning) | ✅ | 54/54 headless (2026-07-03) | — |

**Pass/fail gate:** ask "current gold price" → at least one inline citation ¹ links to a real source; favicon renders.

---

### 1.12 Code Interpreter

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Python sandbox (Docker, numpy/pandas/matplotlib/scipy/sympy) | ✅ | LIVE 7/7 (`fruits.xlsx` downloaded, 5451 bytes, valid PK header) | No network access inside sandbox (by design) |
| Inline chart output | ✅ | `test_ci_files.py` 7/7 | — |
| File download (xlsx, docx, pdf, csv, txt) | ✅ | LIVE (fruits.xlsx + notes.txt, both blobs validated) | Max 6 files / 8 MB per file per run |
| File blobs stripped from sync | ✅ | `stripConvoForSync` removes blobs | — |

**Pass/fail gate:** ask "make a pandas DataFrame of 3 fruits saved to /work/out/fruits.csv" → Download button appears → file contains real CSV data.

---

### 1.13 Image Generation

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Generate an image from prompt | ✅ | LIVE 9/9 (real apple image, 1.08 MB data URL) | — |
| Edit a generated image | ✅ | LIVE 9/9 (apple → apple-with-leaf, distinct src) | — |
| Download generated image | ✅ | `test_img_download.py` 6/6 | — |
| Click to enlarge (inline + uploaded) | ✅ | `test_img_viewer.py` 10/10 | — |
| Image library | ✅ | 54/54 headless | — |
| Image inpainting (brush to mask) | 🚫 | Not built | Requires Responses API brush/mask support — infra-bound |

**Pass/fail gate:** generate an image → Download saves a PNG → clicking opens the lightbox with Edit and Download buttons.

---

### 1.14 Organization & Search

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Sidebar chat search with highlighted snippets | ✅ | `test_search_snippet.py` 7/7 | — |
| Ctrl/⌘+K opens search | ✅ | `test_cmdk.py` 5/5 | — |
| In-chat find (Ctrl+F, highlight + navigate) | ✅ | LIVE 12/12 (6 "banana" matches highlighted) | — |
| Pinned chats | ✅ | 15/15 parity-refresh suite | — |
| Table of contents (5+ responses) | ✅ | 15/15 parity-refresh suite | — |
| Archive / Archive all | ✅ | `test_links_archive.py` 8/8 | — |
| Smart auto-title (3–6 word AI summary) | ✅ | LIVE (`test_autotitle.py` 5/5) | Uses an extra luna API call per first turn |

**Pass/fail gate:** search a word that appears only in message body (not title) → snippet with bold match appears; click → chat opens at that message.

---

### 1.15 Group Chats

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Create group + invite link | ✅ | LIVE two-browser 10/10 | — |
| Up to 20 members, server-side polling (2.5 s) | ✅ | LIVE Alice + Bob flow | — |
| @ChatGPT AI reply (claim lock across both backends) | ✅ | LIVE (real "42" response to both) | — |
| Join/leave system messages | ✅ | LIVE 10/10 | — |

**Pass/fail gate:** two users in a group → `@ChatGPT what is 2+2` → both see "4" within 5 seconds; one leaves → the other sees the system line.

---

### 1.16 Scheduled Tasks

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| Once / daily / weekly scheduler | ✅ | LIVE e2e (TASK-RAN-OK, landed in sync store) | — |
| Results appear as a chat on next sync pull | ✅ | Run toast in `applySync` | — |
| Auto-pause on invalid key / zero balance | ✅ | 22/22 tasks suite | — |

**Pass/fail gate:** create a once task scheduled 1 minute from now → it fires → the result appears as a sidebar chat within 2 minutes.

---

### 1.17 Connectors

| Sub-feature | Status | Verification | Gap |
|---|---|---|---|
| GitHub connector (repos, files, issues, code search) | ✅ | 22/22 connectors suite; live Yahoo Finance | — |
| Finances connector (live quote + history) | ✅ | LIVE (AAPL 308.63 from Yahoo) | — |
| Tokens never stored server-side / never synced | ✅ | Token-not-synced test | — |

**Pass/fail gate:** enable Finances, ask "current AAPL price" → a Finances tool block renders with a real quote.

---

## Tier 2 — Experience Quality

These are measurable targets that separate a *good* product from a *great* one.
Every target has a number or a pass/fail test.

### 2.1 Latency

| Metric | Target | Current status | How to measure |
|---|---|---|---|
| First-token latency P99 (Sol, typed chat) | **< 3.0 s** | ~1.7 s observed in one mobile test; upstream slowdowns cause outliers | Run `latency_sweep.py` (50 turns, measure SSE first-token delta) |
| First-token latency P99 (Terra, voice fast lane) | **< 1.2 s** | ~1 s observed; `gpt-5.5-instant` with low effort | Same sweep, voice=true |
| First-token latency P99 (Luna, auto-title) | **< 0.8 s** | Not measured | Auto-title timer logged in `maybeAutoTitle` |
| TTS time-to-first-word (end of speech → first audio) | **< 2.0 s** | Not measured end-to-end on real device | Web Audio `AudioContext.currentTime` delta |
| Sentence-boundary dead air | **< 50 ms** | 5 ms in the gap test | Gap test (800 ms stub) |
| Sync round-trip (push + pull) | **< 500 ms** | Not measured | Timer around `syncNow()` |

**Why these numbers:** ChatGPT's first-token latency in a lightly loaded period is ~1–2 s. Our P99 target gives headroom for upstream variance while still feeling instant.

### 2.2 Uptime & Reliability

| Metric | Target | Current status | How to measure |
|---|---|---|---|
| Service uptime (both public domains) | **≥ 99.5%** (~3.6 h downtime/month) | Unknown; two brief unreachable windows observed (2026-06-29, 2026-07-05) | External uptime monitor (e.g. UptimeRobot, 1 min poll) on `/health` |
| In-stream error rate (no-content / error events) | **< 0.5%** of turns | Unknown | Count `logger.warning` "no content" events in `main.py` server logs |
| Auto-retry success rate (first retry recovers) | **≥ 95%** | Not measured | Server log: `[RETRY]` prefix added when retry fires |
| 8201 backend in sync with 8200 after any restart | **100%** | One incident found (2026-07-11 — stale 8201 for hours) | Run `deploy_verify.py` after every backend change |

**Why these numbers:** 99.5% is AWS RDS SLA territory — achievable for a two-backend FastAPI app backed by a single host with systemd watchdog. The 0.5% error rate matches OpenAI's own SLA guidance for API consumers.

### 2.3 Mobile UX

| Metric | Target | Current status | How to measure |
|---|---|---|---|
| Lighthouse Performance (mobile, 390×844) | **≥ 90** | Not measured | `lighthouse --form-factor=mobile` on chatgpt.comparegpt.io |
| Lighthouse Accessibility | **≥ 95** | a11y suite 11/11; skip link, ARIA roles, focus traps | Same Lighthouse run |
| No horizontal scroll at 390 px | **0 px overflow** | `audit_overflow.py` confirmed at 390 px and 1280 px | `audit_overflow.py` |
| + menu fully visible on mobile (bottom sheet) | **Pass** | LIVE 12/12 (2026-07-09, 390×844) | `test_mobile_menu.py` |
| First contentful paint on mobile (cold load) | **< 2.0 s** (3G) | Not measured | Lighthouse or WebPageTest |

**Why these numbers:** ChatGPT's own mobile Lighthouse score is ~88–93 on LCP. We're a single-file SPA so cold-load FCP is dominated by the `index.html` size and render budget.

### 2.4 Code Interpreter Quality

| Metric | Target | Current status | How to measure |
|---|---|---|---|
| Successful sandbox execution rate | **≥ 90%** of `[[run]]` turns | Not measured | Count `exit_code==0` in sandbox logs |
| Correct file output for common requests | **Pass for 5 standard tasks** | LIVE: fruits.xlsx, notes.txt, cities.xlsx all valid | `ci_quality_suite.py` (pandas CSV, matplotlib PNG, docx, xlsx, PDF) |
| Sandbox cold-start time | **< 3.0 s** | Not measured | Time from `/api/run` POST to first stdout byte |
| Max output file size | 8 MB per file, 6 files/run | Implemented | Unit cap check in `_run_sandboxed` |
| Missing libraries cause a user-facing error, not a silent crash | **Pass** | Dockerfile adds openpyxl/python-docx/reportlab/XlsxWriter | Try `import pdfplumber` → friendly ImportError message in stdout |

### 2.5 Real-Time Search Accuracy

| Metric | Target | Current status | How to measure |
|---|---|---|---|
| Factual accuracy on news questions (last 7 days) | **≥ 90%** (9/10 correct on a golden eval set) | Not measured | `search_eval.py` (10 hand-labelled Q&A pairs updated weekly) |
| Citations present on search replies | **≥ 1 inline citation per web-search reply** | `test_citations.py` 10/10; LIVE 2 inline citations | Citation presence check in `live_sweep.py` |
| Source favicons load (not broken fallback) | **≥ 80%** of sources have a real favicon | Not measured | `audit_citations.py` checks `img.complete && naturalWidth > 0` |
| No raw `[[cite:` markers in rendered text | **0 leaks** | 10/10; live verified | Citation leak check in headless sweep |

### 2.6 Memory Recall

| Metric | Target | Current status | How to measure |
|---|---|---|---|
| Saved facts recalled correctly in a new chat | **5/5 on a fixed recall eval** | Not measured | `memory_recall_eval.py`: save 5 diverse facts, new chat, probe each |
| Forgotten facts NOT recalled after deletion | **0/5 leak** | Memory forget confirmed in sources-indicator test | Same eval after deleting each fact |
| Time-aware interpretation (past plans as past) | **Pass: reply uses past tense for elapsed plans** | LIVE (dates inferred correctly in Record-mode summary) | Add an "I planned to X last year" memory; confirm past-tense reply |

---

## Tier 3 — Nice-to-Have

These are valuable but not on the critical path to "same as ChatGPT."

| Feature | Priority | Effort | Blocker |
|---|---|---|---|
| **Group chats — polish** (read receipts, typing indicators per-user, file sharing in groups) | Medium | M | None |
| **Scheduled tasks — recurring output formatting** (better daily/weekly report layout) | Medium | S | None |
| **Deep research — citation quality** (deduplicate sources, rank by credibility) | Medium | M | None |
| **Sora video generation** | Low | XL | Separate `sora.com` product; not in ChatGPT proper. Re-evaluate if OpenAI re-integrates. |
| **Custom connectors** (user-defined webhook or MCP endpoints) | Medium | L | Design needed (auth model for user-supplied tokens) |
| **Native mobile app** (iOS / Android PWA shell or React Native) | Low | XL | PWA with `manifest.json` + service worker is the incremental path |
| **Full-duplex voice (GPT-Live)** | Low | XL | Requires OpenAI Realtime API — infra-bound; not available via subscription OAuth |
| **Email from chat** | Low | M | Requires OAuth token for user's email provider |
| **Finance account linking dashboard** | Low | XL | Requires Plaid/Yodlee integration — out of scope for PWM |
| **ChatGPT Work agent** | Low | XL | Requires OpenAI's agentic infra — infra-bound |
| **Atlas browser integration** | 🚫 Blocked | — | OpenAI-internal tool; not accessible via subscription |
| **Image inpainting (brush to mask)** | Low | M | Responses API brush/mask — check availability quarterly |
| **Live GPT Store marketplace** | Low | XL | Requires backend GPT Store infra |

---

## Weekly Health Dashboard

Run every Monday. All checks are automated; fix any red before shipping new features.

```
chatgpt-pwm Health Check — Week of YYYY-MM-DD
═══════════════════════════════════════════════
Live sweep (both domains)           [ ] 10/10  chatgpt.comparegpt.io
                                    [ ] 10/10  chatgpt.platformai.org
Deploy sync check                   [ ] byte-identical index.html across repo + both live dirs
                                    [ ] 8200 and 8201 backends on same git HEAD
Latency probe (5 turns, Sol)        [ ] P50 < 2.0 s  P99 < 3.0 s
Latency probe (5 turns, voice)      [ ] P50 < 0.8 s  P99 < 1.2 s
Uptime (7-day rolling)              [ ] ≥ 99.5%  (UptimeRobot or equivalent)
Error rate (no-content warnings)    [ ] < 0.5%  (grep server logs)
Mobile overflow check (390 px)      [ ] 0 px horizontal overflow
Citation sanity (web search turn)   [ ] ≥ 1 inline citation; no raw markers
CI sanity (pandas CSV)              [ ] fruits.csv download contains valid CSV
Memory recall (5-fact probe)        [ ] 5/5 recalled; 0/5 leak after forget
Group chat AI reply (live)          [ ] @ChatGPT responds within 5 s to both members
Scheduled task fire (1 min)         [ ] Task result appears as sidebar chat
```

**Escalation rule:** any red item blocks new feature work until resolved.

---

## Monthly Goals

### August 2026

**Theme: Measure everything you don't know yet.**

1. Instrument `main.py` to emit structured logs for every turn: `{turn_id, model, first_token_ms, total_ms, error, web_search, image_gen, ci_run}`. Ship to a local SQLite log file (`~/pwm/chatgpt-logs/turns.db`).
2. Write `latency_dashboard.py` that reads `turns.db` and prints P50 / P95 / P99 per model tier. Target: have a week of data by Aug 15.
3. Set up UptimeRobot (free tier) to monitor `/health` on both domains at 1-min intervals. Share the status page URL.
4. Ship `ci_quality_suite.py` — 5 standard tasks (CSV, matplotlib chart, DOCX paragraph, XLSX with formula, PDF via reportlab); pass/fail on each.
5. Ship `search_eval.py` — 10 hand-labelled questions (5 sports scores, 3 tech news, 2 finance). Run weekly. Target ≥ 9/10 on the first run.
6. Run `lighthouse --form-factor=mobile` on chatgpt.comparegpt.io. If score < 90, file the top 3 Lighthouse recommendations as issues.
7. Reduce `index.html` size if Lighthouse FCP > 2 s: lazy-load highlight.js language packs (only load the grammar for the language in view).

**August pass/fail gate:** latency P99 < 3 s confirmed in prod data; Lighthouse ≥ 85 (target is 90, 85 is the floor); CI suite 5/5; search eval ≥ 9/10.

---

### September 2026

**Theme: Close the quality gaps, not the feature gaps.**

1. **Auto-switch to Thinking eval:** run 20 prompts (10 complex, 10 simple) and measure escalation accuracy. If false-positive rate > 20% or false-negative rate > 30%, tune `looksComplex()` thresholds.
2. **Memory recall eval:** ship `memory_recall_eval.py` with 20 diverse facts (names, dates, preferences, skills); target ≥ 18/20 recall after one sync cycle.
3. **Voice latency target:** measure TTS time-to-first-word on a real device (not headless). If > 2 s, profile `ttsFetchAudio` vs `decodeAudioData` and cache common short phrases.
4. **Lighthouse ≥ 90:** if not hit in August, fix the top blockers (likely: render-blocking scripts, image sizing, unused CSS in the single-file SPA).
5. **Error rate < 0.5%:** analyze `turns.db` for no-content warnings; if rate > 0.5%, implement upstream health-check before billing the user's balance.
6. **Favicon accuracy ≥ 80%:** if below target, switch to a favicon service (e.g. `https://www.google.com/s2/favicons?domain=<host>`) for better coverage.
7. **Deploy checklist enforced:** add a pre-deploy script that confirms 8200 and 8201 are both running the same `main.py` commit before accepting a push.

**September pass/fail gate:** Lighthouse ≥ 90; error rate < 0.5% confirmed over a 2-week window; memory recall ≥ 18/20; voice TTS < 2 s on a real device.

---

### October 2026

**Theme: Sustainable operations + one new capability.**

1. **Uptime SLA 99.5%:** review 3 months of UptimeRobot data. If any 30-day window is below 99.5%, identify the root cause (upstream outage vs our backend vs billing platform) and add a retry or fallback.
2. **Billing transparency:** add a per-turn cost estimate (PWM credits) displayed in the message footer (collapsed by default, expandable). Data is already in `turns.db`.
3. **Connector expansion (GitHub code search):** the GitHub `search_code` action requires a PAT. Add a one-time setup guide in Settings → Connectors (link to GitHub token creation with the exact scopes needed). Goal: ≥ 50% of GitHub connector users have code search enabled.
4. **Mobile PWA:** add `manifest.json` + service worker caching for the SPA shell (not API responses). Test "Add to Home Screen" on iOS Safari and Android Chrome. No native app — just install-to-homescreen.
5. **One new capability** (to be decided September 30, based on user feedback and September eval data). Candidates: custom connectors (user-defined webhooks), improved deep-research UI (step-by-step progress), or scheduled task formatting.
6. **Stress test group chats:** 5 simultaneous users in one group, all messaging at once. Target: AI claim lock fires exactly once; no 409 or 403 leaks to clients.

**October pass/fail gate:** 99.5% uptime confirmed; mobile PWA installable on iOS + Android; group chat stress test passes.

---

## Competitive Positioning

### vs. OpenAI ChatGPT

| Dimension | OpenAI ChatGPT | chatgpt-pwm | Verdict |
|---|---|---|---|
| **Models** | GPT-5.6 Sol/Terra/Luna, GPT-5.5, GPT-5.4 | Same (via pooled subscription OAuth) | **Tied** |
| **Core features** | The full ChatGPT surface | Everything except GPT-Live voice, GPT Store marketplace, image inpainting, Finance dashboard, Atlas browser, Work agent | **~95% parity** |
| **Cost model** | Per-message consumption from ChatGPT plan | PWM balance (flat-rate metered); no per-token API charge | **PWM advantage** — predictable cost for high-volume users |
| **Infrastructure** | Proprietary, closed stack | Open (FastAPI + SQLite + Docker); self-hostable | **PWM advantage** for operators |
| **Data privacy** | OpenAI data policy | PWM controls the sync DB; memory/CI never leave the user's own backend | **PWM advantage** for privacy-sensitive deployments |
| **Voice quality** | Full-duplex GPT-Live (Realtime API) | Half-duplex with barge-in + Web Audio (no Realtime API access) | **OpenAI advantage** |
| **Image inpainting** | Yes (brush mask in image gen) | Not built (Responses API feature, check quarterly) | **OpenAI advantage** |
| **Sora video** | Separate sora.com (not in ChatGPT proper) | Not in sidebar (correct parity) | **Tied** |
| **Mobile** | Native iOS + Android app | Responsive web (PWA installable, no native app) | **OpenAI advantage** — native push notifications, camera integration |
| **Login** | Google / email / Apple | Google / PWM account / wallet (SIWE) | **Tied for most users** |
| **Self-hosting** | Not possible | Run `uvicorn main:app` with your own ChatGPT auth | **PWM advantage** |

### The PWM pitch in one sentence

> Same GPT-5.6 models as OpenAI, at a predictable PWM cost, on an open stack you can inspect and self-host — with no per-token API bill.

### What we will never match (and shouldn't try)

- **GPT-Live voice:** requires the Realtime API — full-duplex, <500 ms latency. Our barge-in + Web Audio approach is good but not identical.
- **Native mobile app:** push notifications, camera/mic OS integration, App Store distribution. PWA is the right tradeoff for now.
- **OpenAI's model R&D cadence:** we ride the models; we don't train them. This is a feature, not a bug — but it means our model advantage is always exactly equal to OpenAI's, never ahead.

---

## Drilldowns

### D1 — Code Interpreter

**What we have:** a Docker sandbox (`chatgpt-pwm-ci:latest` from `python:3.11-slim`) that runs model-generated Python in an unprivileged `unshare` namespace. No network. Outputs: stdout, stderr, matplotlib PNG charts, and any file written to `/work/out/` (base64-encoded, returned as `files:[{name,size,data}]`).

**Libraries installed:** numpy, pandas, matplotlib, scipy, sympy, openpyxl, python-docx, reportlab, XlsxWriter.

**Caps:** 6 files/run, 8 MB/file, 60 s timeout (implicit Docker cap).

**Known limitations:**
- `unshare` (user namespace isolation) is blocked on this GCP host kernel. Sandbox runs as the Docker container's default user — not unprivileged. Production risk is low (no network, read-only host mounts) but worth hardening.
- `import pdfplumber`, `import PIL`, `import requests` fail silently unless added to the Docker image. The model may generate code that fails. Add a catch-all `ImportError` handler in the sandbox entrypoint that prints a user-readable message.
- Cold-start time (Docker `run`) is not measured. If > 3 s, investigate `docker create` + `docker start` pre-warming.

**Next steps:**
1. Measure sandbox cold-start: add a `sandbox_start_ms` field to the response JSON.
2. Add `pillow` and `pdfplumber` to the Docker image (common model requests).
3. Add `ci_quality_suite.py` covering: CSV, matplotlib PNG, DOCX paragraph, XLSX formula, PDF.
4. Investigate `--userns-remap` on the GCP host as a path to real unprivileged sandboxing.

---

### D2 — Real-Time Search

**What we have:** the ChatGPT Responses API's `web_search_call` tool, proxied through `openai_subscription.py`. Each search turn:
1. The model decides to search and fires a `web_search_call` event.
2. The subscription fetches results and streams `url_citation` annotation events with `start_index`/`end_index` offsets into the output text.
3. Our backend forwards `source` events with `{url, title, start, end}`.
4. The frontend splices `[[cite:N|url]]` markers into the raw output at the `end` offsets (back-to-front), then renders inline `¹` superscripts with domain tooltips and a Sources card list.

**Accuracy signal:** we have no ground-truth eval. The model decides which queries to search and how to incorporate results — accuracy is as good as GPT-5.6's web-search reasoning.

**Known limitations:**
- The `web_search_call.searching` event carries **no query string** (confirmed: 8 events, 0 queries). We cannot show "Searching: <q>" like ChatGPT does.
- Favicons come from `<host>/favicon.ico` directly. ~20% of sites serve a 404 or a `text/html` at that path. The `onerror` fallback to the globe SVG is correct but hurts polish.
- No deduplication of citations: if two sentences cite the same URL, both get separate inline marks.

**Next steps:**
1. Ship `search_eval.py` (10 Q&A pairs, hand-labelled, run weekly).
2. Switch favicon fetches to `https://www.google.com/s2/favicons?domain=<host>&sz=32` for better coverage (measure before/after).
3. Deduplicate citations: if the same URL appears ≥2 times in a reply, collapse to one number.
4. When the search event carries a `query` field in a future API version, surface "Searching: <q>" in the streaming UI.

---

### D3 — Mobile UX

**What we have:** a responsive single-file SPA with:
- Sidebar starts off-canvas; hamburger opens it flush-left with backdrop.
- `+ menu` renders as a full-width bottom sheet (max 70dvh) on ≤ 768 px viewports.
- Model picker opens in-viewport.
- No horizontal overflow at 390 px (confirmed by `audit_overflow.py`).
- Login modal fits 4 SSO buttons at 390 px.
- Voice button visible on mobile.

**What's not tested / measured:**
- Lighthouse Performance + Accessibility scores (not yet run).
- First Contentful Paint on a real 3G connection.
- iOS Safari-specific: Web Audio autoplay on a real iPhone (headless Chrome does not enforce autoplay policy — the TTS fix was validated mechanically, not on a real device).
- "Add to Home Screen" PWA install flow.
- Keyboard behavior when the software keyboard covers the composer.

**Next steps:**
1. Run Lighthouse mobile and publish the score. Fix the top 3 blockers.
2. Test on a real iOS device: voice mode TTS playback, barge-in, + menu bottom sheet, keyboard-above-composer layout.
3. Add `manifest.json` + service worker for PWA installability (October goal).
4. Address the iOS Safari autoplay risk: gate `voiceStart()` on a user gesture in the UI (button tap) and document that programmatic play is blocked without a gesture.
5. If Lighthouse FCP > 2 s, lazy-load highlight.js language grammars (only load the grammar when a code fence of that language is rendered).

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Pooled ChatGPT subscription rate-limited** (429, usage_limit_reached) — blocks all generation | Medium (observed ~37 min window on 2026-07-11) | High | Log rate-limit events with estimated reset time; surface to users as "ChatGPT is busy, try again in ~N min" with the actual reset countdown |
| **Upstream model change** (OpenAI renames/retires a model slug) | Medium | High | Weekly probe: `probe_models.py` tests each slug; alert on first 400. Backend map in `openai_subscription.py` — one-line alias change to recover |
| **8201 backend drifts from 8200** after a backend change | High (happened 2026-07-11 — stale for hours) | Medium | Add deploy script that restarts BOTH services and diffs their running-process mtime before declaring success |
| **Single-host SQLite contention** under concurrent users | Low (2 uvicorn workers, claim locks for tasks/groups) | Medium | Monitor `sqlite3_busy_timeout` errors in server logs. If write contention > 1%, migrate to WAL mode (`PRAGMA journal_mode=WAL`) |
| **Memory blows past localStorage quota** (IndexedDB images + large convos) | Medium | Low | `stripConvoForSync` strips file blobs; `stripLargeContent` caps message text. If quota warning appears, add a user-visible "your storage is almost full" toast |
| **Docker sandbox not unprivileged** (`unshare` blocked on GCP kernel) | Confirmed | Low-Medium | No network access; read-only mounts reduce blast radius. Investigate `--userns-remap` or move CI to a host where `unshare` is allowed |
| **iOS Safari Web Audio autoplay on real device** | Unknown (not tested) | High for voice UX | Test on real iPhone before Oct. If blocked, gate voice start on a fresh user gesture every session |
| **ChatGPT subscription OAuth token expiry** | Low (auto-refreshed) | High | Add a `401` handler in `openai_subscription.py` that triggers a token refresh and retries once before surfacing to the user |

---

## Decision Gates

These are binary checkpoints. If the answer is "no," stop and fix before proceeding.

| Gate | Question | Pass condition | When to evaluate |
|---|---|---|---|
| **G1 — Live sweep** | Are all 10 features working on both production domains? | `live_sweep.py` 10/10 on chatgpt.comparegpt.io AND chatgpt.platformai.org | Before every deploy |
| **G2 — Deploy sync** | Are both backends running the same code? | `deploy_verify.py`: sha256 of `index.html` + `main.py` byte-identical across repo + both live dirs + both backends were restarted after the last backend change | After every backend deploy |
| **G3 — Latency** | Is P99 first-token latency under 3 s? | `latency_sweep.py` 50-turn run on Sol, P99 < 3.0 s | Monthly (from September) |
| **G4 — Error rate** | Is the no-content / error-event rate under 0.5%? | `grep "no content\|in-stream error" server.log | wc -l` / total turns < 0.5% | Monthly (from September) |
| **G5 — Mobile** | Does the app score ≥ 90 on mobile Lighthouse? | `lighthouse https://chatgpt.comparegpt.io --form-factor=mobile` → Performance ≥ 90 | Monthly (from August) |
| **G6 — Search accuracy** | Do we answer 9/10 recent factual questions correctly? | `search_eval.py` ≥ 9/10 on the weekly golden set | Weekly (from August) |
| **G7 — CI quality** | Do all 5 standard code-interpreter tasks succeed? | `ci_quality_suite.py` 5/5 | Weekly (from August) |

---

## Measurement Toolkit

Scripts to write (in `web/tests/` or `web/tools/`):

| Script | Purpose | Owner metric |
|---|---|---|
| `live_sweep.py` | 10-feature live regression sweep on both domains | G1 |
| `deploy_verify.py` | SHA256 + process-mtime check across repo / live dirs / running backends | G2 |
| `latency_sweep.py` | 50 real turns, record `first_token_ms` per tier; print P50/P95/P99 | G3 |
| `ci_quality_suite.py` | 5 standard CI tasks; pass/fail per task; validate output file format | G7 |
| `search_eval.py` | 10 hand-labelled Q&A pairs; grade accuracy; track week-over-week | G6 |
| `memory_recall_eval.py` | Save 20 facts, new chat, probe each; measure recall + leak rate | 2.6 |
| `audit_overflow.py` | *(exists)* Check 0 px horizontal overflow at 390 px and 1280 px | 2.3 |
| `audit_citations.py` | For 5 web-search turns: count citations, check favicons load, no raw markers | 2.5 |

**Structured server logging** (in `main.py`, `_stream_with_billing`):

```python
logger.info(json.dumps({
    "turn_id": turn_id,
    "model": model,
    "first_token_ms": first_token_ms,
    "total_ms": total_ms,
    "error": error_flag,
    "web_search": web_search,
    "image_gen": image_gen,
    "ci_run": ci_run,
    "tokens": tokens,
}))
```

This feeds `latency_dashboard.py` and the error-rate check.

**External monitoring:**
- UptimeRobot (free) → 1-min poll on `https://chatgpt.comparegpt.io/health` and `https://chatgpt.platformai.org/health` → email alert on downtime.
- Weekly Lighthouse CI run (GitHub Actions or manual): `npx lighthouse https://chatgpt.comparegpt.io --output=json --form-factor=mobile --chrome-flags="--headless"`.

---

*Every goal here has a number or a pass/fail test. If you can't measure it, it's not a goal — it's a wish.*
