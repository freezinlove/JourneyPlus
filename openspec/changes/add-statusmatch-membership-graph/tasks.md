## 1. Graph contracts and source metadata

- [x] 1.1 Add strict node, claim, edge, wildcard rule, tree, limits, snapshot, and audit contracts
- [x] 1.2 Expose deterministic StatusMatch FAQ mapping category metadata without changing persisted FactSet contents
- [x] 1.3 Add program alias, tier, wildcard, and uncertainty normalization with ambiguity reporting

## 2. Graph construction and traversal

- [x] 2.1 Build a current graph from ACTIVE watch FactSets with correct source-to-target direction and current snapshot provenance
- [x] 2.2 Aggregate duplicate node pairs while retaining distinct factual claims and exclude UNAVAILABLE mappings from traversal
- [x] 2.3 Implement category wildcard and program-level uncertain rules for concrete membership queries
- [x] 2.4 Implement bounded rooted tree expansion with deterministic ordering, cycle leaves, cross-reference leaves, and explicit truncation

## 3. Audit and access

- [x] 3.1 Implement claim-fidelity auditing for missing, invented, and duplicate claims
- [x] 3.2 Implement topology auditing for self-loops, strongly connected components, uncertainty, conflicts, and representative tree behavior
- [x] 3.3 Add CLI commands for rooted tree queries and real-data graph audits
- [x] 3.4 Add matching read-only endpoints to the internal review API

## 4. Automated verification

- [x] 4.1 Test exact, conditional, unavailable, duplicate-claim, and evidence-preservation behavior
- [x] 4.2 Test alias connection, ambiguity, category wildcard, and uncertain-tier behavior
- [x] 4.3 Test multi-hop trees, directed cycles, cross-references, stable ordering, and all traversal limits
- [x] 4.4 Test current-only database construction plus CLI/API contracts without model calls

## 5. Real-data and human audit

- [x] 5.1 Build the graph from all eight current StatusMatch projects and verify every available mapping claim is represented without invented or reversed claims
- [x] 5.2 Manually compare representative exact, conditional, wildcard, and any present uncertain edges with stored FactSets and visible source evidence
- [x] 5.3 Manually inspect representative rooted multi-hop trees for understandable direction, bounded branching, cross-references, and cycle truncation
- [x] 5.4 Run the full test suite, strict OpenSpec validation, compile checks, and worktree checks
