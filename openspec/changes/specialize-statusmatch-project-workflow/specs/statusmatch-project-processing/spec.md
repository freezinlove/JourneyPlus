## ADDED Requirements

### Requirement: Managed StatusMatch projects use a dedicated project workflow
The system SHALL process a managed StatusMatch watch as one project whose semantic input is the current activity page plus the current FAQ page, and SHALL NOT send either managed page through the generic document classification, candidate retrieval, relationship analysis, or per-document workflow.

#### Scenario: First active two-page snapshot
- **WHEN** a new watch has valid current activity and FAQ documents and deterministic closure assessment says the project is active
- **THEN** the system executes one project fact extraction and at most one brief generation for the combined snapshot

#### Scenario: Managed pages are pending in the generic source
- **WHEN** generic pending-document selection encounters `status_services_mail` documents whose external identity starts with `statusmatch-page:`
- **THEN** those documents are excluded from the generic workflow without deleting their historical runs or versions

### Requirement: StatusMatch event identity is deterministic
The system SHALL bind one current event to each live watch without candidate retrieval or relationship AI, SHALL keep all current pages and updates of that watch on the bound event, and SHALL treat a newly created watch as a new event generation.

#### Scenario: New watch without an event
- **WHEN** an active two-page watch has no current event
- **THEN** the project workflow creates one event keyed by that watch generation and binds both current pages as evidence

#### Scenario: Existing watch update
- **WHEN** either current page changes for a watch that already has a current event
- **THEN** the project workflow updates that event without considering any other StatusMatch or non-StatusMatch event

#### Scenario: Different StatusMatch hosts
- **WHEN** two live watches have different project hosts even if their content or target tier names are similar
- **THEN** the system never invokes relationship AI or merges their events

#### Scenario: Reonboarded archived host
- **WHEN** an archived host is later onboarded as a genuinely new watch
- **THEN** the new watch creates a new event generation rather than reusing the archived event

### Requirement: Project extraction produces identity and complete current facts
The system SHALL make one structured project extraction request containing the current HOME and FAQ materials and SHALL require a project identity plus a complete current fact snapshot rather than a change-only patch.

#### Scenario: Initial extraction
- **WHEN** the project has no current FactSet
- **THEN** the extraction output supplies program, summary, target status, complete supported facts, routes, and narrative mappings for the current two-page snapshot

#### Scenario: Updated extraction
- **WHEN** the project already has a current FactSet and either page has a new current version
- **THEN** the request includes the previous current FactSet as context but the output still represents the complete new current snapshot

#### Scenario: Removed obsolete fact
- **WHEN** a fact from the previous snapshot is absent from both current pages
- **THEN** the new complete snapshot leaves that fact unknown rather than retaining the obsolete value

### Requirement: Model evidence uses trusted page aliases
The system SHALL expose only the aliases HOME and FAQ for model-authored evidence and SHALL resolve those aliases to the current document version ID and canonical source URL before persisting a FactSet.

#### Scenario: Valid alias evidence
- **WHEN** the model cites HOME or FAQ with a non-empty locator
- **THEN** the persisted evidence contains the corresponding current document ID and canonical URL

#### Scenario: Invalid evidence alias
- **WHEN** model output cites an unknown alias or an invalid evidence shape
- **THEN** schema validation rejects the attempt and the bounded correction retry does not persist partial facts

### Requirement: Deterministic and narrative mappings are combined
The system SHALL parse supported FAQ HTML mapping tables deterministically, SHALL ask the model only for mappings explicitly stated outside those parsed table rows, and SHALL merge both channels into the final FactSet with evidence and deduplication.

#### Scenario: Mapping table only
- **WHEN** the FAQ contains a supported mapping table and no additional prose mapping
- **THEN** the final FactSet contains the deterministic table mappings without requiring the model to reproduce table rows

#### Scenario: Narrative mapping only
- **WHEN** current project text states a mapping but no supported table expresses it
- **THEN** the final FactSet may contain a narrative mapping bound to HOME or FAQ evidence

#### Scenario: Table and supplementary narrative
- **WHEN** a project contains a mapping table plus a distinct prose mapping or condition outside the table
- **THEN** the final FactSet retains the deterministic rows and the non-duplicate narrative result

### Requirement: StatusMatch semantic changes are recorded structurally
The system SHALL compare each validated complete FactSet with the prior current FactSet while ignoring evidence-version churn and SHALL persist a ChangeSet tied to the project event and current two-page snapshot.

#### Scenario: Initial snapshot
- **WHEN** the project produces its first FactSet
- **THEN** the system records an initial snapshot ChangeSet

#### Scenario: Material facts changed
- **WHEN** a scalar fact, application route, or status mapping materially differs
- **THEN** the system creates a new FactSet and records structured before/after additions, removals, or modifications

#### Scenario: Presentation-only page change
- **WHEN** a new page version produces the same material FactSet signature
- **THEN** the system reuses the existing FactSet and brief and records that page content changed without a semantic fact change

### Requirement: Brief generation occurs only after the project snapshot is complete
The system SHALL generate the Chinese brief from the validated project FactSet only after both current pages have been considered and SHALL reuse the existing brief when the material FactSet is reused.

#### Scenario: First project brief
- **WHEN** the first complete FactSet is persisted
- **THEN** exactly one brief-generation request is made for the project

#### Scenario: Facts unchanged on update
- **WHEN** project extraction returns a materially identical FactSet
- **THEN** no new brief record or brief model request is created

#### Scenario: Facts changed on update
- **WHEN** project extraction produces a materially different FactSet
- **THEN** one new brief is generated from the new current FactSet

### Requirement: Dedicated processing participates in daily automation
The system SHALL process pending complete StatusMatch project snapshots after monitoring and source collection but before generic document processing, using the shared model-call budget and independent project-level result reporting.

#### Scenario: Newly discovered Gmail project
- **WHEN** Gmail collection onboards a new active host during a daily cycle
- **THEN** the same cycle processes its complete project snapshot through the dedicated workflow

#### Scenario: Existing page update
- **WHEN** monitoring creates a new current version for one watched page
- **THEN** the same cycle processes the latest two-page snapshot once

#### Scenario: No project change
- **WHEN** the watch page IDs and processing configuration match a successful prior project job
- **THEN** the daily cycle makes no project or brief model call for that watch

### Requirement: Real-page output is manually auditable
The implementation SHALL provide a repeatable command or service entry point that processes selected real StatusMatch hosts and reports the two current page IDs, model-call count, event identity, FactSet version, mapping count, ChangeSet, brief, and errors without exposing secrets.

#### Scenario: Real public page audit
- **WHEN** an operator runs the audit for a selected active host
- **THEN** the output is sufficient to compare the stored result with the visible activity and FAQ pages and confirm that classification and relationship AI were not used
