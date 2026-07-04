# Voice mode barge-in — design (2026-07-04)

## Goal
Let the user interrupt the AI in voice conversation mode — while it is **speaking**
or still **thinking** — by simply talking (or tapping the orb). The interrupted
words become the start of the next message.

## Decisions (user-confirmed)
- Interrupt scope: while speaking AND while generating. Interrupting mid-generation
  aborts the stream; the partial reply stays in the chat (same as pressing Stop).
- Trigger: voice + tap. Voice barge-in keeps recognition running while the AI
  talks (Chrome echo cancellation suppresses most self-pickup); tapping the orb is
  the reliable manual fallback.

## Mechanism
`web/index.html` only; no backend changes.

- **Barge listener** (`voiceBargeListen`): during the thinking/speaking phases a
  background `SpeechRecognition` runs (`voiceBargeRec`, one at a time). An interim
  transcript with ≥3 chars of real content triggers the interrupt (`voiceBargeNow`)
  and the same recognizer keeps collecting as the normal turn listener; on end its
  transcript is sent via `voiceSend`. If it ends untriggered (noise/silence) it
  restarts while the busy phase lasts (`voiceBusyPhase()` = generating ||
  voiceSpeaking || queued clips).
- **Interrupt** (`voiceBargeNow`): sets `voiceBarged`, clears the sentence queue,
  `stopTts()`, aborts the in-flight generation via the existing `abortCtl`, and
  flips the UI to Listening. `voiceSend` checks `voiceBarged` after `streamReply`
  returns so the old turn's tail is never spoken. (The abort fires at trigger time;
  the new send only fires at end-of-speech, seconds later, so the aborted turn's
  bookkeeping always finishes first.)
- **Tap**: the orb gets an onclick; during a busy phase it calls `voiceBargeNow`
  and promotes the current barge recognizer to the turn listener (`_triggered`).
- **Echo safeguard**: sub-threshold interim text (<3 chars) never interrupts; the
  false-positive residue is covered by the tap fallback and by the fact that an
  untriggered recognizer simply restarts.
- Mute and close abort the barge recognizer like the normal one. The speaking
  status line becomes "Speaking… (talk to interrupt)".

## Testing
Headless Playwright suites in the established pattern (mock SpeechRecognition is
drivable from the test): barge while speaking (playback stops, interrupting words
sent as next message, new reply spoken); barge while thinking (stream aborted,
second chat request carries the new words); tap-to-interrupt; echo guard (2-char
noise does not interrupt); plus re-running the four existing voice suites.
