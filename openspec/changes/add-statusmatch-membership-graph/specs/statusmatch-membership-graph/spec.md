## ADDED Requirements

### Requirement: Graph is derived from current managed StatusMatch facts
The system SHALL build the membership graph from the current FactSet of every ACTIVE managed StatusMatch watch and SHALL NOT invoke AI, mutate project facts, or include archived and superseded FactSets.

#### Scenario: Current active projects
- **WHEN** the graph is built while active watches have current FactSets
- **THEN** the snapshot identifies every contributing watch, event, and FactSet and uses only their current mappings

#### Scenario: Archived project
- **WHEN** a watch is archived or no longer ACTIVE
- **THEN** its mapping claims are absent from newly built graph snapshots

### Requirement: Mapping direction and evidence remain factual
The system SHALL represent each traversable relationship in the direction `source membership → target membership`, SHALL retain a claim tied to the originating mapping, event, FactSet, conditions, conflicts, and evidence, and SHALL never synthesize a reversed edge.

#### Scenario: Mapping with multiple source tiers
- **WHEN** one mapping lists several source tiers for one target tier
- **THEN** each source membership contributes a directional claim to that target and every claim can be traced back to the same mapping evidence

#### Scenario: Same node pair has multiple claims
- **WHEN** several mappings support the same canonical source and target nodes
- **THEN** the graph exposes one readable edge containing all distinct factual claims

### Requirement: Availability and uncertainty are explicit
The system SHALL make AVAILABLE and CONDITIONAL mappings traversable, SHALL exclude UNAVAILABLE mappings from reachable edges, and SHALL preserve conditional, conflicting, wildcard, and uncertain status in graph and tree outputs.

#### Scenario: Unavailable target tier
- **WHEN** a mapping explicitly marks a target unavailable and lists no source tiers
- **THEN** it is counted in the audit but cannot be reached as a graph child

#### Scenario: Conditional mapping
- **WHEN** a mapping is available only under a stated condition
- **THEN** the edge is traversable and exposes the condition without presenting it as unconditional

#### Scenario: Source tier is not specific
- **WHEN** a mapping identifies a source program or eligible member but does not identify a concrete tier
- **THEN** the graph retains an UNCERTAIN rule that may be shown for a concrete query only with an explicit uncertainty marker

### Requirement: Wildcard mappings apply to known matching categories
The system SHALL represent explicit all/any-program or all-tier mappings as wildcard rules and SHALL resolve them for known concrete membership nodes only when deterministic source-category metadata matches.

#### Scenario: All airline tiers are eligible
- **WHEN** an AIRLINE wildcard rule says all membership levels map to one target
- **THEN** a query rooted at a known airline tier includes that target with WILDCARD certainty and a reference to the original rule

#### Scenario: Category is unknown or different
- **WHEN** a concrete node has UNKNOWN category or a category different from a wildcard rule
- **THEN** the wildcard rule is not applied to that node

### Requirement: Program and tier aliases connect only explainable identities
The system SHALL canonicalize case, whitespace, punctuation, target-program prefixes, and sufficiently distinctive target aliases, SHALL retain original labels, and SHALL report rather than guess when two canonical programs are equally plausible.

#### Scenario: Target loyalty program appears with carrier prefix
- **WHEN** `Flying Blue` and `Air France Flying Blue` identify the same target loyalty program through an unambiguous target alias
- **THEN** their equal normalized tier names resolve to the same membership node

#### Scenario: Ambiguous alias
- **WHEN** a raw program label matches multiple target identities with equal specificity
- **THEN** the label remains separate and the ambiguity appears in the graph audit

### Requirement: A membership query returns a bounded rooted tree
The system SHALL return an ordered nested tree rooted at a requested concrete membership, expanding outgoing relationships one level at a time while enforcing configurable depth, node, and branch limits.

#### Scenario: Multi-hop chain
- **WHEN** a target membership from one edge is also the source of another edge
- **THEN** the second target appears as the next child level until a terminal or configured limit is reached

#### Scenario: Branch reaches an ancestor
- **WHEN** an outgoing edge would return to any node already on the current branch
- **THEN** the relationship is returned as a CYCLE leaf and is not recursively expanded

#### Scenario: Shared node was expanded on another branch
- **WHEN** a node has already been fully expanded elsewhere in the same query
- **THEN** the later occurrence is returned as a CROSS_REFERENCE leaf and its subtree is not duplicated

#### Scenario: Query limit is reached
- **WHEN** depth, node, or per-node branch limit is reached
- **THEN** the affected node reports the exact truncation reason and omitted count without silently dropping relationships

### Requirement: Graph audit separates fact fidelity from graph topology
The system SHALL produce an audit report that compares expected mapping claims with represented edge/rule claims and separately reports topology properties including self-loops, strongly connected components, cycles, cross-references, uncertainty, conflicts, and truncation.

#### Scenario: All available facts are represented once
- **WHEN** the graph is built from valid current FactSets
- **THEN** the fidelity audit reports no missing or invented claim IDs and identifies any duplicate claim IDs

#### Scenario: Real directed cycle exists
- **WHEN** factual mappings form a directed cycle across projects
- **THEN** the topology audit reports the component while rooted tree queries remain finite

### Requirement: Graph capability has read-only machine interfaces
The system SHALL expose the current graph audit and rooted tree query through a CLI and internal read-only API using strict JSON-compatible contracts.

#### Scenario: CLI tree query
- **WHEN** an operator supplies a source program, source tier, and optional limits
- **THEN** the command returns the resolved root, nested relationships, claim evidence, and traversal statistics without making model calls

#### Scenario: Internal API query
- **WHEN** an internal client requests the same root and limits
- **THEN** the API returns the same deterministic tree contract as the CLI

### Requirement: Real graph output is manually auditable
The implementation SHALL provide a repeatable real-data audit over the current eight StatusMatch projects and SHALL support human comparison of representative graph claims with the stored FactSets and original public evidence.

#### Scenario: Human fact and readability review
- **WHEN** an operator audits representative exact, conditional, wildcard, uncertain, multi-hop, and cyclic relationships
- **THEN** the review can determine whether edge direction and tiers match the facts and whether the rooted result remains a clear finite tree
