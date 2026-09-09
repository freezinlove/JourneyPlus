## ADDED Requirements

### Requirement: Evidence-based architecture audit
Before destructive rebuilding, the project SHALL map modules, entry points, input/output contracts, consumers, and database objects against the target architecture. Each keep, change, or delete decision SHALL have current evidence and a stated role or replacement, without inheriting withdrawn historical findings.

#### Scenario: Review an early-named processing table
- **WHEN** the audit finds a table used by the current AIWorkflow
- **THEN** its actual purpose and dependencies determine its disposition rather than its name or age

### Requirement: Scoped stopped-write cleanup
Cleanup SHALL enumerate the affected project databases, records, and resources, resolve personal-data scope explicitly, and verify a recovery backup before deletion. All applicable write paths SHALL remain stopped during cleanup and code rebuilding. Source mailbox messages SHALL NOT be deleted.

#### Scenario: Personal-data scope unresolved
- **WHEN** a cleanup manifest lacks a decision for real holdings or conversations
- **THEN** deletion of those records does not proceed until their scope is explicitly resolved

#### Scenario: Execute an authorized cleanup
- **WHEN** the documented cleanup runs after recovery verification
- **THEN** only enumerated project resources are affected and schedulers or old writers cannot repopulate cleared data

### Requirement: Empty-schema rebuild without compatibility
The final database SHALL be created from the target schema without importing old knowledge or requiring legacy runtime compatibility. Superseded code, tables, routes, configuration, and project temporary databases SHALL exit after their dependencies are addressed. Necessary reusable algorithms, tests, and recovery evidence SHALL NOT be removed solely for being old.

#### Scenario: Start on a freshly created database
- **WHEN** the final startup procedure runs against the empty target schema
- **THEN** structural readiness and knowledge readiness are reported separately and AIWorkflow can populate it using the new production contract

### Requirement: One-time source cleanup semantics
LoyaltyLobby historical cleanup and removal of the specified GHA material SHALL be bounded to the one-time rebuild manifest. They SHALL NOT establish rolling ten-day retention, permanent source blacklists, or future collection prohibitions.

#### Scenario: Future source update
- **WHEN** normal source processing runs after the one-time cleanup
- **THEN** admission follows the normal source policy rather than an implicit permanent rule created by that cleanup

### Requirement: Dual-perspective acceptance through the delivered service
System acceptance SHALL use the final normal webpage, service configuration, database, and runtime chain. Human ModelPort acceptance SHALL precede Agent provider acceptance, and both SHALL record user-visible results and correlated internal evidence for diverse multi-turn scenarios. Isolated tests SHALL be supplemental evidence only.

#### Scenario: A direct tool test passes
- **WHEN** a tool succeeds in an isolated test or direct script
- **THEN** that success does not mark the corresponding normal webpage scenario as passed

#### Scenario: Provider acceptance begins
- **WHEN** human web-path and production-chain gates pass
- **THEN** an authorized economical non-Max provider model is tested through the same webpage and ModelPort path, with its results distinguished from human acceptance

### Requirement: Verifiable handover
Handover SHALL document the actual running version, normal startup, final schema, source-production evidence, acceptance outcomes, unresolved limitations, and temporary-resource disposition. Failed or untested scenarios SHALL NOT be presented as completed.

#### Scenario: Required scenario remains broken
- **WHEN** a required normal-service scenario fails or lacks evidence
- **THEN** the change is reported as incomplete for that requirement regardless of unit-test totals or planning artifact completion
