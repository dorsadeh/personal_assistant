# Live Dashboard — Design Spec

## Goal

A phone-first web dashboard where Dor & Tal review and check off everything in
their notebook, in the approved "A · Magnets" design (Bauhaus fridge-door:
gallery-white ground, cobalt accent, sun/poppy magnet marks, heavy grotesque
wordmark). Mockup reference: claude.ai artifact `0caeb58a` (design A) and its
source (committed alongside this spec as `docs/mockups/dashboard-design-a.html`).

## Decisions (2026-08-08)

- **Hosting: Vercel** (Dor has an account, hobby tier). The dashboard talks to
  **GitHub as the data hub** — it never contacts the PC:
  `PC (bot) ──push──▶ sadeh-family-notebook ◀──read/write── Vercel`.
- **Interactive v1**: tapping a checkbox marks the item done — a commit to the
  notebook repo via GitHub's contents API, attributed
  (`dashboard: Tal checked off "buy bread and butter"`).
- **Auth**: single shared family password (env var) → signed httpOnly cookie
  (30 days). Login page in design A. No accounts, no OAuth — 2 users.
- **Secrets on Vercel**: fine-grained GitHub PAT scoped to ONLY
  `sadeh-family-notebook` (contents read/write), `FAMILY_PASSWORD`,
  `SESSION_SECRET`. Never in the repo.
- GitHub-as-database judged appropriate at family scale (tiny textual data,
  low write rate, free history/backup/auth); documented boundaries: no
  queries/transactions, same-line edits need SHA-retry, ~300ms API reads.

## Architecture

- **Next.js (App Router) in `dashboard/`** of the personal_assistant repo;
  deployed on Vercel with root directory `dashboard/`.
- **Reads**: server-side fetch of notebook files via GitHub contents API
  (`todos.md`, `lists/*.md`, `travel/*.md`, recent commits for the activity
  feed). Markdown parsed with a small tolerant parser (checkbox lines,
  headings, notes, attribution `(Name, Mon YYYY)` / `(Name)` suffixes).
  `revalidate` ~30s + on-demand after any write.
- **Writes (check-off)**: server action — GET file (capture `sha`), toggle the
  item's `- [ ]`/`- [x]`, PUT with `sha` precondition; on 409 conflict
  re-fetch and retry (up to 3); commit message
  `dashboard: <Name> checked off "<item>"` (name chosen at login — "I'm Dor" /
  "I'm Tal" toggle stored in the session).
- **Todos check-off also moves the item to `## Done`** per the notebook's
  conventions (never delete). List/trip items just flip to `- [x]` in place.
- **Bot-side prerequisite (Task 1)**: `git_sync` gains `pull --rebase` before
  push so dashboard commits and bot commits interleave cleanly; on rebase
  conflict: abort rebase, log, leave local state intact (bot remains source of
  truth on the PC; next sync retries).
- **PDF links**: proxied through a server route (GitHub raw contents with the
  PAT) so documents open from the dashboard without exposing the token.

## Out of scope (v1)
- Adding/editing items from the dashboard (capture stays in Telegram).
- Un-checking from the dashboard (rare; do it via the bot).
- Multi-notebook, accounts, push notifications.

## Verification
- Unit: markdown parse/serialize round-trip; toggle logic; done-section move.
- Integration (mocked GitHub API): read models; check-off happy path; 409
  retry path.
- Bot side: git_sync rebase tests (diverged remote → clean rebase + push;
  conflicting same-line edit → abort, local intact, no raise).
- Live: deploy preview → login → see real notebook → check "buy bread and
  butter" → commit appears in GitHub, todos.md shows item under Done, bot's
  next sync rebases cleanly; PDF opens; wrong password rejected.
