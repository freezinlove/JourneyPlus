## ADDED Requirements

### Requirement: Shared shortest membership search
All matching consumers SHALL use shortest reachable membership paths and SHALL NOT expand paths by region or exact prices.

#### Scenario: Cycles and longer duplicate targets
- **WHEN** A reaches C directly and also through D and B
- **THEN** C uses the direct path, B remains reachable, and C is not expanded again from the longer path

#### Scenario: Multiple origins and highest target
- **WHEN** several valid origins reach several tiers of one target program
- **THEN** each tier has a shortest predecessor and the highest known eligible tier is the displayed destination, retaining necessary intermediate tiers

### Requirement: Binary fee selection
The system SHALL use only free or paid matching labels; missing fee information SHALL default to free. Original region and numeric price data SHALL remain available in activity details.

#### Scenario: Paid filter before highest tier
- **WHEN** Gold is free and Platinum requires payment and free-only is selected
- **THEN** Gold is returned without region variants or numeric prices in the route result

### Requirement: Compact durable results
The system SHALL persist only selected result nodes, edges and version references, never exploration queues or discarded paths.

#### Scenario: Prefix and shared edges
- **WHEN** selected results contain A-C, A-C-E and A-C-F
- **THEN** the result and graph contain the shared A-C connection once with branches to E and F

### Requirement: Consistent consumers and safe transition
Agent, waiting and matching pages SHALL share the same result semantics. Previous incompatible queries SHALL request refresh or explicit condition update without changing stored facts.

#### Scenario: Real production acceptance
- **WHEN** the normal browser runs the same query through the real configured model and waiting service
- **THEN** their selected paths and fee flags agree and stored activity facts remain unchanged
