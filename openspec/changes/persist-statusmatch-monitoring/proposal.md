## Why

StatusMatch pages are currently rediscovered through Gmail and can be fetched and processed repeatedly even when nothing changed. JourneyPlus needs a durable project-level watch list so public pages can be monitored independently from email, unchanged content can be skipped, and genuinely closed offers can leave the active candidate pool without losing historical evidence.

## What Changes

- Add a persistent StatusMatch watch list keyed by normalized `*.statusmatch.com` host, with exactly one activity-page target and one FAQ-page target per monitored project.
- Seed the list from the eight currently active StatusMatch projects and allow genuinely new Gmail links to add projects after an initial activity/FAQ fetch.
- Make Gmail discovery incremental: list candidate message IDs, download and parse only unseen or previously failed messages, and ignore StatusMatch links whose host is already monitored.
- Monitor both stored targets periodically, creating document versions only for changed content and avoiding downstream semantic processing when neither page changed.
- When either page changes, rebuild the project's current interpretation from the latest activity and FAQ snapshots; reuse the existing facts and brief when the material fact signature is unchanged.
- Detect only whole-offer closure/waitlist states using conservative, evidence-backed rules. On confirmed closure, archive the event and remove its watch-list row while preserving sources, document versions, facts, briefs, and evidence history.
- Treat partial region, route, tier, or source-program closures as ordinary content changes rather than whole-project closure; treat fetch failures, bot challenges, and cross-host redirects as reviewable errors rather than closure.

## Capabilities

### New Capabilities

- `statusmatch-persistent-monitoring`: Persistent two-page StatusMatch project monitoring, change detection, snapshot-based semantic rebuilds, and conservative closure archival.
- `gmail-incremental-statusmatch-discovery`: Incremental Gmail message ingestion and deduplicated onboarding of previously unknown StatusMatch projects.

### Modified Capabilities

None.

## Impact

- Adds database schema and migration work for StatusMatch watch state and per-page monitoring state.
- Changes Gmail discovery, ingestion orchestration, StatusMatch page fetching, event archival, and scheduled automation behavior.
- Adds deterministic lifecycle classification and regression fixtures based on observed public StatusMatch page shapes.
- Requires migration/backfill verification against the current PostgreSQL data and read-only live validation against the two current Gmail messages and the eight active public projects.
