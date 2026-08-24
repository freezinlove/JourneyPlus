## 1. Contracts and persistence

- [x] 1.1 Add strict StatusMatch project identity, aliased evidence, project fact extraction, project processing summary, and ChangeSet contracts
- [x] 1.2 Add the StatusMatch ChangeSet model and event/snapshot indexes
- [x] 1.3 Add and test the database migration for project ChangeSets

## 2. Dedicated project facts

- [x] 2.1 Implement deterministic watch event creation and binding without classification, candidates, or relationship analysis
- [x] 2.2 Implement the combined HOME+FAQ project prompt, bounded retries, and evidence-alias resolution
- [x] 2.3 Merge deterministic HTML table mappings with non-table narrative mappings and reuse shared fact validation guards
- [x] 2.4 Persist or reuse complete FactSets, update project identity/lifecycle, and retain current two-page evidence
- [x] 2.5 Implement deterministic scalar, route, and mapping diffs and persist initial, changed, and semantic-no-change ChangeSets

## 3. Workflow orchestration

- [x] 3.1 Add project-level idempotency and pending-watch processing with one fact extraction per current two-page snapshot
- [x] 3.2 Exclude managed StatusMatch page documents from generic pending-document processing
- [x] 3.3 Run dedicated StatusMatch projects after monitoring and collection in daily automation using the shared model-call budget
- [x] 3.4 Expose project processing counts, calls, errors, and outputs in automation summaries

## 4. Tests

- [x] 4.1 Test first onboarding creates one event, one FactSet, one brief, and exactly two model calls with no classification or relationship run
- [x] 4.2 Test an updated page keeps the event, uses the latest two-page snapshot, and records a structured ChangeSet
- [x] 4.3 Test materially identical updates reuse FactSet and brief while recording semantic no-change
- [x] 4.4 Test table-only, narrative-only, and mixed mapping extraction with valid alias evidence and deduplication
- [x] 4.5 Test invalid aliases, missing pages, closure, failed fetches, different hosts, and reonboarded watch generations
- [x] 4.6 Test generic articles and Gmail discovery remain operational while managed pages never enter V1Workflow

## 5. Migration and real-page audit

- [x] 5.1 Back up and migrate the local PostgreSQL database, then verify existing eight watches and sixteen current page targets remain intact
- [x] 5.2 Run the full automated test suite and strict OpenSpec validation
- [x] 5.3 Add a repeatable selected-host audit command that reports page IDs, project calls, event, facts, mappings, ChangeSet, brief, and errors
- [x] 5.4 Run the dedicated workflow against selected real StatusMatch links and manually compare visible original pages with the stored FactSet and brief
- [x] 5.5 Audit that no StatusMatch classification/relationship AI ran, initial/current brief generation is singular, and no duplicate events were created
