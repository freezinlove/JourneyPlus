## 1. Persistence and backfill

- [x] 1.1 Add StatusMatch watch/page models and StatusEvent closure provenance fields
- [x] 1.2 Add migration 0006 with constraints, cascades, and backfill from existing activity/FAQ source items
- [x] 1.3 Add watch-list repository helpers and verify the current database backfills eight watches and sixteen page targets

## 2. Incremental Gmail discovery

- [x] 2.1 Split Gmail ID enumeration from full-message parsing and skip full retrieval for successfully persisted message IDs
- [x] 2.2 Deduplicate extracted project hosts against the live watch list and onboard only absent hosts
- [x] 2.3 Preserve retry behavior for unseen/failed mail and ensure removed watches are not recreated from historical messages

## 3. StatusMatch monitoring and semantic rebuild

- [x] 3.1 Implement safe activity/FAQ fetching, hash-gated page state updates, and independent per-page errors
- [x] 3.2 Implement deterministic whole-offer closure classification with active-flow and partial-closure protections
- [x] 3.3 Implement latest-two-page snapshot processing and replacement-mode fact consolidation with material-signature reuse
- [x] 3.4 Archive confirmed closed events with provenance, remove only live watch rows, and preserve all historical records

## 4. Automation integration

- [x] 4.1 Run persisted StatusMatch monitoring independently in daily automation even when Gmail collection fails
- [x] 4.2 Expose monitoring counts/errors in automation summaries without breaking existing source reporting

## 5. Automated verification

- [x] 5.1 Add migration/backfill and watch invariant tests
- [x] 5.2 Add Gmail unseen-message, duplicate-host, removed-watch, and retry tests
- [x] 5.3 Add unchanged, one-page-change, snapshot-replacement, fact-reuse, fetch-error, and history-preservation tests
- [x] 5.4 Add closure fixtures for whole waitlist/ended states and active partial-closure boundaries
- [x] 5.5 Run the full test suite and OpenSpec validation

## 6. Live validation

- [x] 6.1 Back up and migrate the local PostgreSQL database, then audit the eight-watch/sixteen-page backfill
- [x] 6.2 Verify the two current Gmail messages are skipped without full-body retrieval and duplicate links do not fetch pages
- [x] 6.3 Fetch and visually inspect all eight active activity/FAQ pairs and confirm classification against their original pages
- [x] 6.4 Recheck public closed/waitlist and partial-closure boundary pages, compare raw visible content with classifier results, and document the audit outcome
