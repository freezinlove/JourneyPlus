## ADDED Requirements

### Requirement: Single local user stores graph-backed holdings
The system SHALL store the local user's current status holdings with normalized program and tier keys, display labels, and an optional validity date. A holding MUST resolve to an existing unified membership graph node, and one program SHALL have at most one current holding.

#### Scenario: Add a known holding
- **WHEN** the user selects a program and tier from the membership catalog
- **THEN** the holding is stored with the catalog's normalized keys and display labels

#### Scenario: Reject unknown free text
- **WHEN** a requested program or tier does not resolve to a catalog node
- **THEN** the system rejects the write and does not create a guessed holding

#### Scenario: Replace current tier in a program
- **WHEN** the local user changes the held tier for an already stored program
- **THEN** the program has one updated holding rather than two current tiers

### Requirement: Reachability starts from every holding and has no business depth limit
The system SHALL construct one deterministic reachable subgraph from all stored holding roots and SHALL continue through direct and applicable wildcard relations until each branch reaches a leaf, cycle, cross-reference, or explicit technical response budget. It MUST NOT enforce a one-step, two-step, or other business depth limit.

#### Scenario: Long acyclic chain
- **WHEN** a holding reaches an acyclic chain longer than the former default depth
- **THEN** every node and edge remains reachable in the product response without a depth-limit state

#### Scenario: Multiple roots converge
- **WHEN** two stored holdings eventually reach the same target node
- **THEN** both incoming paths are preserved and the shared descendant subgraph is expanded once

### Requirement: Cycles and cross references preserve edges without repeated expansion
The system SHALL preserve a relation whose target already exists in the current ancestor path as a cycle edge and stop recursion on that occurrence. It SHALL preserve a relation to a node expanded elsewhere as a cross reference and SHALL NOT duplicate that node's descendants.

#### Scenario: Cycle closes to an ancestor
- **WHEN** traversal encounters `A → B → C → A`
- **THEN** `C → A` is returned with a cycle state and traversal terminates on that occurrence

#### Scenario: Diamond graph
- **WHEN** `A → B → D` and `A → C → D` both exist
- **THEN** both paths to D are returned and one D occurrence is a cross reference rather than a duplicated descendant tree

### Requirement: Personalized graph includes only match contributions
The unified graph contribution layer SHALL exclude ordinary article opportunities explicitly classified as `OTHER`. Managed StatusMatch contributions and current grounded ordinary `STATUS_MATCH` contributions SHALL remain eligible.

#### Scenario: Card promotion has a mapping-shaped claim
- **WHEN** an ordinary card promotion is classified as `OTHER` even though its facts contain source-to-target tier text
- **THEN** it does not create a personalized membership edge

### Requirement: Match results remain one collection
The personalized read model SHALL return reachable mapping opportunities and current `STATUS_MATCH` opportunities without mapping edges in one result collection. Conditions, challenge text, region advisories, and conflicts SHALL remain inline facts and MUST NOT create direct/conditional/public-challenge result partitions.

#### Scenario: Standalone status challenge
- **WHEN** a current `STATUS_MATCH` challenge has a target status but no source status mapping
- **THEN** it appears in the same match result collection with a null path

### Requirement: Opportunity details resolve through provenance
For every graph relation contribution, the system SHALL resolve its provenance to the current official FactSet or ordinary ArticleOpportunity and expose routes, prices, challenge requirements, lifecycle, evidence, brief, and application links without creating a parallel opportunity record.

#### Scenario: Official graph edge detail
- **WHEN** the user opens an edge backed by a StatusMatch official contribution
- **THEN** the detail is assembled from the current StatusEvent FactSet and Brief identified by provenance

#### Scenario: Ordinary article edge detail
- **WHEN** the user opens an edge backed by an ordinary article contribution
- **THEN** the detail is assembled from the current ArticleOpportunity and ArticleBrief identified by provenance

### Requirement: Personalized reads make no model calls
Catalog lookup, holding writes, reachability traversal, region advisory derivation, opportunity assembly, and product page reads MUST be deterministic and MUST NOT invoke an AI provider.

#### Scenario: Repeated graph read
- **WHEN** the user reloads the personalized graph without changing database state
- **THEN** the response is stable and the model call count remains zero
