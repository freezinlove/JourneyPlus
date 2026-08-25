## 1. Persistence and contracts

- [x] 1.1 Add persistent article-route and versioned supplement models with constraints and provenance fields.
- [x] 1.2 Add an Alembic migration and migration coverage for upgrade, downgrade, and revision length.
- [x] 1.3 Add strict highlight extraction and composed-brief contracts, including bounded exact article evidence excerpts.

## 2. Deterministic routing and official preparation

- [x] 2.1 Implement the shared third-party eligibility/link predicate using raw HTML and existing StatusMatch URL canonicalization.
- [x] 2.2 Persist idempotent routes for every eligible document-version/host pair and cover multi-host and duplicate-link cases.
- [x] 2.3 Ensure absent/incomplete watches are fetched as HOME+FAQ while complete ACTIVE watches are not refreshed due to article discovery.
- [x] 2.4 Mark first-seen closed projects terminal for that route and preserve recoverable waiting/error states for transient failures.
- [x] 2.5 Exclude eligible linked articles from generic pending/count/processing while leaving Gmail, managed pages, and unlinked articles unchanged.

## 3. Supplemental highlight workflow

- [x] 3.1 Implement one-call article-versus-official extraction with compact project context and no classification or relationship output.
- [x] 3.2 Validate highlight bounds, duplicates, exact article evidence containment, and bounded correction attempts.
- [x] 3.3 Deterministically attach routes to the exact host event and persist successful highlight or no-novel versions.
- [x] 3.4 Add provider/prompt/schema/official-version idempotency and independent per-route failure recovery.
- [x] 3.5 Recompare after an official version change while retaining old supplement versions for audit.

## 4. Composition and orchestration

- [x] 4.1 Implement the read-only composed StatusMatch brief with official content, current supplemental highlights, route states, and provenance.
- [x] 4.2 Integrate discover/prepare, official project processing, supplemental processing, generic processing, and lifecycle in the specified daily order with separate summaries.
- [x] 4.3 Apply the same narrow ordering and document scope to public initialization and keep model/document budgets bounded.
- [x] 4.4 Add CLI and internal review API surfaces for processing, composed brief retrieval, and third-party audit output.

## 5. Automated verification

- [x] 5.1 Test unknown, existing, closed, incomplete, multi-host, archived-generation, and transient-failure route behavior.
- [x] 5.2 Test useful, duplicate-only, invalid-evidence, zero-highlight, retry, idempotent, and official-update supplement behavior.
- [x] 5.3 Test that linked articles produce no generic classification/relationship/event/brief and that ordinary articles still run the generic workflow.
- [x] 5.4 Test composed reads, graph isolation, daily automation, initialization, CLI/API, and migration behavior.
- [x] 5.5 Run the focused suite, full suite, static checks, and OpenSpec validation without creating a Git commit.

## 6. Real acceptance and manual audit

- [x] 6.1 Ingest the real LoyaltyLobby Kenya Airways / Accor article from allowed Feed content and prove its exact StatusMatch link route.
- [x] 6.2 Fetch and process the real linked HOME+FAQ project end to end, recording official artifacts and model calls.
- [x] 6.3 Manually inspect the visible original article, HOME, FAQ, stored Feed text, official facts/brief, and every retained or rejected highlight.
- [x] 6.4 Record whether the composed brief is accurate, non-duplicative, evidence-backed, and isolated from the generic and membership-graph paths.
