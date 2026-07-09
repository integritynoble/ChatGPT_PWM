# Memory sources indicator — design (2026-07-08)

## Goal
Mirror ChatGPT's 2026 "memory sources" feature: show what personalization
context shaped a reply — via a book icon under the response — with controls to
delete a memory that's outdated. Sources never appear in shared chats.

## Approach (user-approved)
Snapshot per reply: when a request is built, record exactly which
personalization context it carries; store it on the assistant variant as
`srcs`. Faithful even after memories are later edited or deleted; syncs with
the conversation.

## Mechanism (`web/index.html` only)
- **Capture** — `captureSources(c, lite)` mirrors `systemContext`'s inclusion
  rules: `gpt` (custom-GPT name), `ci` (custom instructions present),
  `mem` (`[{id,text}]` snapshot of enabled saved memories), `files` (project
  file names; skipped on voice turns, matching the lite context). Returns null
  when nothing personalizes the request → no icon. `streamReply` captures it
  alongside the system context and attaches it to the reply variant on
  successful completion.
- **UI** — a book icon (`act-src`) in the assistant action row, visible only
  when the shown variant has `srcs` and not in shared view. Click → "Sources"
  popover: GPT persona, Custom instructions (Edit in Settings), Saved memories
  (each with ✕ Forget if the memory still exists — deletes by stable id — or a
  "no longer saved" note), Project files.
- **Privacy** — share snapshots strip `srcs` from every variant before POSTing
  to `/api/share` (sync keeps them; they're the user's own devices).

## Testing
Headless: personalized reply (memories + custom instructions) → book icon
lists both, ✕ deletes the memory from the saved list; un-personalized reply →
no icon; share payload contains no `srcs`. Existing suites re-run green.
