## ADDED Requirements

### Requirement: Deterministic third-party StatusMatch routing
The system SHALL identify a third-party StatusMatch article only when a non-Gmail, non-managed-page document contains at least one canonical project-specific `*.statusmatch.com` link, SHALL persist one route per document version and project host, and SHALL exclude that document from the generic document workflow by the same deterministic predicate.

#### Scenario: Third-party article contains an exact project link
- **WHEN** a LoyaltyLobby or other public-source document contains a canonicalizable link to `kenya-airways.statusmatch.com`
- **THEN** the system creates a route for that host and the document does not receive generic classification, candidate retrieval, relationship analysis, generic event creation, or a generic brief

#### Scenario: Ordinary article has no project link
- **WHEN** a public-source document contains no valid project-specific StatusMatch link
- **THEN** the system does not create a StatusMatch article route and leaves the existing generic pending and processing behavior unchanged

#### Scenario: Discovery mail and managed pages are not supplements
- **WHEN** a Gmail discovery document or a managed `statusmatch-page:` HOME/FAQ document contains a StatusMatch URL
- **THEN** the system does not treat that document as a third-party article supplement

#### Scenario: One article links multiple projects
- **WHEN** one eligible article version contains links to two distinct valid project hosts
- **THEN** the system persists two independent routes and does not infer a relationship between the projects

### Requirement: Official project readiness precedes article processing
The system SHALL ensure the linked project has an ACTIVE watch, current HOME and FAQ documents, a current official FactSet, and a current official Brief before extracting article highlights.

#### Scenario: Linked project is absent from the watchlist
- **WHEN** a newly routed article links a host not present in the persistent watchlist
- **THEN** the system creates the watch, fetches both canonical HOME and FAQ pages, runs the dedicated official StatusMatch workflow, and only then processes the article route

#### Scenario: Linked project already has complete current official output
- **WHEN** a newly routed article links an ACTIVE watch with current HOME, FAQ, FactSet, and Brief
- **THEN** the system reuses those official outputs and does not refresh or reprocess the official pages merely because the article was discovered

#### Scenario: Official page preparation is temporarily incomplete
- **WHEN** HOME/FAQ fetch or official project processing fails
- **THEN** the route remains recoverable and excluded from the generic workflow until a later attempt can complete the official project

#### Scenario: Newly discovered official project is already closed
- **WHEN** the canonical HOME+FAQ snapshot satisfies the deterministic closure rule during first preparation
- **THEN** the watch is archived/removed according to the existing lifecycle rule, the route is marked as official-closed, and the same article does not recreate and refetch that closed watch every cycle

### Requirement: Deterministic attachment without relationship AI
The system SHALL attach each ready article route to the current unarchived event of its exact project host and SHALL NOT use classification AI, candidate retrieval, relationship AI, cross-host merging, or generic event creation for that attachment.

#### Scenario: Existing host has a current event
- **WHEN** a routed article becomes ready for an ACTIVE watch
- **THEN** its event association equals that watch's `current_event_id` and no alternate event candidates are evaluated

#### Scenario: Historical route and a later project generation coexist
- **WHEN** an old route belongs to an archived event and the same host is later onboarded as a new watch/event
- **THEN** the old route remains attached to its historical event and is not silently migrated to the new generation

### Requirement: Novel evidence-backed highlights only
The system SHALL compare the article with both the current official FactSet and official Brief in one structured AI stage and SHALL persist only useful article claims that are explicit in the article and not already covered by either official artifact.

#### Scenario: Article contains an additional practical point
- **WHEN** an article explicitly states a useful qualification, interpretation, or caution absent from the official FactSet and Brief
- **THEN** the result contains a concise highlight, a short verbatim article excerpt locatable in the stored article body, and a reason explaining its novelty relative to official content

#### Scenario: Article only repeats official information
- **WHEN** every useful article statement is already represented in the current official FactSet or Brief
- **THEN** the system persists a successful no-novel-highlights result and does not call the model again for the same inputs

#### Scenario: Model returns ungrounded evidence
- **WHEN** a returned article excerpt cannot be located in the stored normalized article content or the output violates the strict contract
- **THEN** the system rejects it, performs at most the configured bounded correction attempt, and persists no successful supplement unless validation passes

#### Scenario: Article contains a third-party opinion or unsupported inference
- **WHEN** a statement is not explicitly supported by the article text or has no practical informational value
- **THEN** the system omits it from the supplemental highlights

### Requirement: Official and supplemental provenance remain separated
The system SHALL store third-party routes and versioned supplements separately from official FactSets and Briefs and SHALL compose them only in the StatusMatch project read model.

#### Scenario: Supplemental highlights are created
- **WHEN** article highlight extraction succeeds
- **THEN** the official FactSet, official Brief, StatusMatch mapping graph input, and official change set remain unchanged while the composed project brief exposes the supplemental highlights with article and comparison provenance

#### Scenario: Official facts later change
- **WHEN** the event receives a new current official FactSet or Brief
- **THEN** the article is eligible for one new comparison against that official version and the composed brief displays only supplements matching the current official version while retaining older supplement records for audit

#### Scenario: Activity is archived after supplements exist
- **WHEN** normal StatusMatch monitoring archives the event and removes its live watch
- **THEN** historical article routes and supplements remain queryable with the archived event and are excluded from the active project graph

### Requirement: Idempotent bounded processing and observability
The system SHALL use an idempotency input containing the article route/version, current official FactSet and Brief, provider configuration, prompt version, and schema version, and SHALL expose separate routing, official-preparation, supplement, model-call, failure, and pending counts.

#### Scenario: Identical article and official inputs are processed twice
- **WHEN** automation or an operator reruns processing without changing any input version
- **THEN** the prior successful supplement or no-novel result is reused with zero additional model calls

#### Scenario: One route fails while another is valid
- **WHEN** multiple pending routes are processed and one AI operation fails
- **THEN** the successful route commits independently, the failed route remains auditable and retryable, and neither falls back to the generic workflow

### Requirement: Automation and initialization preserve the narrow branch
The system SHALL run third-party discovery and official preparation after source collection, official StatusMatch processing before supplemental processing, supplemental processing before generic documents, and lifecycle processing last; scoped initialization SHALL apply the same ordering to the batch documents.

#### Scenario: Daily collection discovers a new linked article
- **WHEN** a daily source run ingests a third-party article for a previously unknown host
- **THEN** the same cycle can prepare the official project, generate its official output, process the supplement, and report each stage separately within the configured budgets

#### Scenario: Initialization includes linked and ordinary articles
- **WHEN** a public initialization window contains both kinds of documents
- **THEN** linked documents follow only the StatusMatch article branch and ordinary documents follow only the generic branch

### Requirement: Real-page acceptance and manual content audit
The implementation SHALL provide an auditable end-to-end acceptance result for the supplied LoyaltyLobby Kenya Airways / Accor article using stored Feed content and the real linked StatusMatch HOME+FAQ pages, plus a manual visible comparison with the original pages.

#### Scenario: LoyaltyLobby Kenya Airways article acceptance
- **WHEN** the real article at `https://loyaltylobby.com/2026/08/03/kenya-airways-skyteam-elite-plus-platinum-match-for-all-accor-gold-platinum-diamond/` is accepted
- **THEN** the audit identifies the exact project host, proves the generic classification/relationship path was not invoked, shows the official event and artifacts used, lists each retained or rejected supplemental point with evidence, and records a human judgment of whether the final composed brief is accurate and non-duplicative
