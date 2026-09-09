## ADDED Requirements

### Requirement: Independent knowledge production
AIWorkflow SHALL own collection, document processing, identity and fact extraction, validation, and publication without depending on Agent execution or conversation state. Necessary intermediate records SHALL have explicit producers and consumers.

#### Scenario: Agent unavailable
- **WHEN** the Agent model or harness is stopped
- **THEN** normal AIWorkflow entry points can process sources and publish knowledge, and knowledge pages remain usable

### Requirement: Traceable validated facts
AIWorkflow SHALL bind published facts to source versions and identifiable evidence, distinguishing unknown, conflicting, and inapplicable values. A collection success SHALL NOT imply successful knowledge publication.

#### Scenario: Missing fee evidence
- **WHEN** source material does not establish the fee of an application option
- **THEN** the published option expresses the fee as unknown rather than free and retains its evidence references

#### Scenario: Invalid extraction
- **WHEN** extraction or validation fails
- **THEN** the processing outcome records the failure without replacing valid published knowledge

### Requirement: Coherent version publication
AIWorkflow SHALL prepare and validate required facts and artifacts before switching the published version in a short transaction. Network and model calls SHALL occur outside that transaction. Repeated unchanged inputs SHALL be handled idempotently.

#### Scenario: Source updated
- **WHEN** changed source material successfully passes validation
- **THEN** a coherent new version becomes current while earlier brief references retain their original meaning

#### Scenario: Artifact preparation fails
- **WHEN** required brief or graph data preparation fails
- **THEN** the incomplete version is not exposed as ready and the previous valid version remains identifiable

### Requirement: Brief and full graph ownership
Versioned briefs and the full matching graph SHALL be knowledge-side products derived from the same formal facts. Graph caches SHALL be version-bound projections, and Agent path queries SHALL share the deterministic query semantics.

#### Scenario: Open knowledge products without a model
- **WHEN** a user opens a published brief or the full matching graph with the Agent model disabled
- **THEN** both products are available without new Agent model calls, and graph facts agree with queries against the same version

### Requirement: Clean bootstrap from real sources
After rebuilding the schema, AIWorkflow SHALL regenerate knowledge through normal production entry points using reread mail, refreshed StatusMatch official material, and the latest LoyaltyLobby articles selected on the rebuild day. Bootstrap SHALL NOT import prior evaluation facts as newly produced knowledge.

#### Scenario: Execute the bootstrap manifest
- **WHEN** the approved-scope bootstrap manifest is executed
- **THEN** each published item is traceable to a freshly processed real source and its production outcome, with Workflow model usage recorded separately from Agent acceptance
