## ADDED Requirements

### Requirement: One database with explicit ownership
The normal service SHALL use one shared database with explicit ownership for source/process records, membership catalog, formal knowledge, knowledge products, user data, and Agent conversations. Agent tools SHALL NOT write formal knowledge or invoke its production.

#### Scenario: Agent reads an activity
- **WHEN** an Agent tool requests an activity
- **THEN** it reads published knowledge through the stable query contract without collecting, extracting, or publishing source material

### Requirement: Single authoritative fact representation
The target schema SHALL contain one authoritative representation of each formal fact. Briefs, graph projections, and presentation cards SHALL reference that representation and SHALL NOT become independently mutable copies of business truth. Runtime legacy-schema reads, dual writes, and fallback queries SHALL be absent.

#### Scenario: Final service uses the target schema
- **WHEN** the rebuilt service starts or queries a fact
- **THEN** it uses only the target schema and reports a schema mismatch explicitly instead of falling back to an obsolete structure

### Requirement: Stable relationships and version references
Published activities, periods, options, mappings, prices, conditions, evidence, and briefs SHALL have verifiable identities and version relationships. Historical references SHALL remain stable across updates.

#### Scenario: Compare past and current briefs
- **WHEN** a user opens a cited older brief after an activity update
- **THEN** the cited brief still corresponds to its original fact version and the current version is distinguishable

### Requirement: Explicit result coverage and failure semantics
Queries SHALL distinguish pagination completion, graph traversal completion, condition uncertainty, and knowledge coverage. Empty matches, missing catalog entries, uncovered material, unpublished data, and query errors SHALL be distinguishable.

#### Scenario: Exhausted pages with uncertain eligibility
- **WHEN** all result pages have been read but some eligibility conditions remain unknown
- **THEN** the result reports complete pagination without claiming complete eligibility knowledge

#### Scenario: Empty or unavailable knowledge
- **WHEN** the database is empty, unavailable, or has no published material for the request
- **THEN** the service reports the actual readiness or coverage condition rather than asserting that no matching opportunity exists

### Requirement: User data distinct from model memory
Real holdings, hypothetical statements, model notes, and operation receipts SHALL remain distinct. User-data operations SHALL enforce explicit authorization, transactional consistency, idempotency, and observable outcomes.

#### Scenario: Hypothetical membership
- **WHEN** a conversation explores an assumed membership without authorizing a save
- **THEN** no real holding is created and subsequent context continues to identify the membership as hypothetical

#### Scenario: Retried user operation
- **WHEN** an authorized write is retried after a connection interruption
- **THEN** the operation does not duplicate its effects and the actual receipt can be recovered
