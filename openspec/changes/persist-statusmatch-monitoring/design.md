## Context

The `status_services_mail` adapter currently downloads every matching Gmail message during discovery and emits the public activity/FAQ pages for every extracted project on every run. `IngestionService` prevents duplicate document rows after a fetch, but it cannot prevent the network request, and the ordinary document workflow treats each changed page independently while fact consolidation retains all historical evidence. That behavior is useful for feeds, but it does not model a StatusMatch project as a durable two-page resource whose current state is the latest homepage plus latest FAQ.

The current database already contains eight active project hosts and both page source items for each host. Gmail contains two matching messages, including a duplicated Club Avolta link. Public validation also shows why closure detection must be scoped: a Lufthansa landing page redirects to a project-host waitlist page and offers only future-interest registration, while Etihad and Royal Jordanian pages mention ended sub-offers but retain an active project application flow.

## Goals / Non-Goals

**Goals:**

- Persist the active StatusMatch project set and its required activity/FAQ targets independently from Gmail message discovery.
- Avoid downloading full content for successfully processed Gmail messages.
- Avoid fetching public pages merely because a new message repeats a monitored host.
- Fetch active project pages periodically, persist only changed versions, and run semantic work only when needed.
- Rebuild current project facts from the latest two-page snapshot while retaining immutable historical evidence.
- Archive only confidently closed whole offers and remove them from future monitoring.
- Keep page monitoring operational when Gmail is unavailable.

**Non-Goals:**

- Section-level HTML diffs or partial model prompts.
- Reopening a removed project without either a new Gmail message or a separate future discovery source.
- Treating an HTTP error, bot challenge, or any occurrence of the word `await` as closure.
- Deleting historical source, document, event, fact, brief, or evidence records.
- Integrating LoyaltyLobby in this change.

## Decisions

### Persist one project row and two page rows

Add `statusmatch_watches` keyed by normalized host and `statusmatch_watch_pages` keyed by `(watch_id, page_kind)`. The project row stores the current event association and check/change/error timestamps. Each page row stores its canonical URL and current document version. Deleting a watch cascades only to its two page rows; source and semantic history have no cascading dependency on the watch.

This is preferred to encoding monitoring state inside `SourceItem.raw_metadata`, because the latter cannot enforce one homepage plus one FAQ, is awkward to query, and confuses immutable discovery history with mutable operational state.

### Backfill from durable public page source items

Migration/backfill selects distinct valid project hosts from existing `status_services_mail` page source items and creates a watch only when both activity and FAQ targets exist. It associates an event only when current evidence identifies one unambiguously. The eight current projects therefore seed without another network or model call.

### Separate Gmail enumeration, unseen-message parsing, and page monitoring

The Gmail client still lists IDs using the dedicated label and recipient query. Before `get_message(format=full)`, discovery compares those IDs with successfully stored Gmail `SourceItem`/`DocumentVersion` records. Only unseen or failed messages are downloaded. Extracted links are normalized to the project host; an existing watch is a no-op, while an absent host creates a pending watch and performs its initial two-page fetch.

The monitor is a separate service invoked by daily automation even if Gmail collection fails. This is preferred to keeping page refreshes as items emitted by the Gmail adapter, because that couples public lifecycle tracking to OAuth availability and guarantees repeat rediscovery.

### Use hash gates before semantic processing

Each watch-page fetch goes through existing normalization and raw/normalized hashing. If the current parser version matches an existing raw or normalized hash for the page, the page check timestamp advances but no document version or downstream job is created. If a page changes, only that page gets a new `DocumentVersion`; the semantic rebuild receives the latest activity and FAQ versions together.

This implements a simpler and auditable alternative to section-level diffs: network monitoring is full-page, persistence is per changed page, and semantic interpretation is a two-snapshot rebuild.

### Add snapshot replacement mode for StatusMatch fact consolidation

For a monitored project, the service resolves one event and links changed current documents as evidence, but fact consolidation is called with an explicit material override containing only the latest activity and FAQ versions. In snapshot replacement mode the candidate fact set replaces the current semantic values rather than reconciling against obsolete values. The existing material signature comparison remains the final gate: if the material facts are semantically identical, the current `FactSetRecord` and brief are reused.

Historical `EventEvidence`, `EventRevision`, `FactSetRecord`, and `BriefRecord` rows remain unchanged and queryable. This is preferred to deleting old evidence or allowing the ordinary accumulating reconciler to turn legitimate updates into permanent conflicts.

### Classify closure conservatively and deterministically

Closure classification operates on visible normalized text, final URL, page kind, and active-application signals before semantic processing. A whole project is closed only when strong whole-offer language or a project-host `waitlist.php` landing state is present and no active application form/continue/apply-now path remains. Phrases scoped to a region, route, tier, source program, or applicant category do not close the project when the landing page still exposes an active application flow.

HTTP 4xx/5xx responses, challenge pages, invalid HTML, and redirects outside the same project host are recorded as monitoring failures. They never archive an event automatically.

### Remove closed projects from the live list, preserve history

On confirmed closure, set `StatusEvent.archived_at`, record an archive reason and the closure evidence version, then delete the watch. Candidate retrieval already excludes archived events. Old Gmail messages are not downloaded again, so they cannot recreate the watch. A genuinely new future message for the same host sees no live watch, performs a fresh two-page fetch, and creates or links a new non-archived event while the historical event remains archived.

## Risks / Trade-offs

- [A redesigned page uses unfamiliar closure copy] → Require strong whole-offer scope plus absence of an application path; otherwise retain monitoring and flag the page state for review.
- [A project closes and later reopens without a new email] → Accepted limitation for this version; after deletion, reopening requires a new Gmail message or future external discovery source.
- [Homepage and FAQ disagree] → Active homepage application signals prevent automatic whole-project closure based only on a partial FAQ sentence; ambiguous cases remain monitored.
- [Changed presentation creates normalized churn without factual change] → Persist the changed page version, rebuild once, and reuse the existing fact/brief through the material signature gate.
- [Gmail failure hides new projects] → Existing watches are monitored in an independent stage and continue to advance.
- [Backfill associates the wrong event] → Associate only unambiguous evidence-derived events; leave ambiguous watches unattached until the next semantic rebuild.

## Migration Plan

1. Back up the local PostgreSQL database.
2. Create the two monitoring tables and nullable StatusEvent archival provenance columns.
3. Backfill valid StatusMatch hosts and their activity/FAQ targets from existing page source items without fetching or model calls.
4. Deploy incremental Gmail collection and independent monitoring services.
5. Run read-only/live validation against the current two Gmail messages and all eight current projects, then run the full automated suite.

Downgrade drops only operational watch tables and archival provenance columns. Historical source and semantic records remain intact.

## Open Questions

None for this change. Reopening without a new discovery message is intentionally deferred.
