## ADDED Requirements

### Requirement: Binary opportunity kind controls only personalized matching
The system SHALL assign every persisted status opportunity exactly one `OpportunityKind` value from `STATUS_MATCH` or `OTHER`. Direct status matches, status challenges, Fast Tracks, and temporary-status challenges SHALL be `STATUS_MATCH`; card-granted status, elite-progress promotions, and other non-match activities SHALL be `OTHER`.

#### Scenario: Direct match and challenge are in one product kind
- **WHEN** one opportunity maps an existing elite tier to a target tier and another grants a target tier after a stated challenge
- **THEN** both opportunities are persisted as `STATUS_MATCH` without introducing match/challenge subtypes

#### Scenario: Elite progress promotion is other
- **WHEN** an activity only grants double elite nights, MQD, status credits, or equivalent qualification progress without directly granting a target tier
- **THEN** the opportunity is persisted as `OTHER` and is excluded from personalized reachability results

### Requirement: Opportunity kind never suppresses briefs
The system MUST continue generating, versioning, storing, and displaying existing briefs for both `STATUS_MATCH` and `OTHER`; opportunity kind SHALL NOT be a brief generation or publication gate.

#### Scenario: Other opportunity retains its brief
- **WHEN** a persisted opportunity is classified as `OTHER`
- **THEN** its normal brief generation runs unchanged and the resulting brief remains visible on the brief page

### Requirement: StatusMatch projects receive deterministic kind
The system SHALL set managed StatusMatch project facts to `STATUS_MATCH` without asking the model to classify the project. Ordinary articles SHALL return the kind within their existing interpretation call and SHALL NOT add a separate model stage.

#### Scenario: Managed project processing
- **WHEN** a managed StatusMatch HOME and FAQ snapshot is processed
- **THEN** its FactSet is written as `STATUS_MATCH` and the model call count does not include a classification call

### Requirement: Route prices are structured by target tier and evidence
Each application route SHALL retain its original cost text and MAY contain structured price entries with target tier, amount, currency, availability, raw text, and evidence. The system MUST NOT invent a numeric amount or combine fees when the material does not support a reliable total.

#### Scenario: Region-specific tier table
- **WHEN** one route states `Silver USD 99, Gold USD 299, Platinum USD 399`
- **THEN** the route exposes three price entries bound to the corresponding target tiers while preserving the original cost text and evidence

#### Scenario: Unavailable target tier
- **WHEN** a route explicitly says Platinum is unavailable
- **THEN** the route exposes a Platinum price entry with `UNAVAILABLE` availability and does not present a payable amount as an available Platinum price

#### Scenario: Complex fee cannot be totaled safely
- **WHEN** a route states a base application fee and a separate optional upgrade fee without an explicit final total
- **THEN** the system preserves the raw fee text and leaves any unsupported total amount unknown

### Requirement: Legacy prices remain readable
The system SHALL read legacy application routes that lack structured prices. It SHALL use conservative deterministic parsing for supported formats and otherwise display the original cost text without invoking AI at read time.

#### Scenario: Legacy formatted price
- **WHEN** a legacy route contains `Gold: EUR 199` and has no `prices` array
- **THEN** the product detail exposes the supported structured value and the original text with zero model calls

#### Scenario: Legacy unparseable price
- **WHEN** a legacy cost cannot be reliably split into target tier, amount, and currency
- **THEN** the detail displays the original cost and does not invent structured values

### Requirement: China region is advisory only
The system SHALL derive a China advisory from explicit route text and SHALL classify uncertain text as not explicit. The advisory MUST NOT filter opportunities, hide routes, block links, change graph reachability, change ordering, or substitute another region's price.

#### Scenario: Explicit exclusion
- **WHEN** a route explicitly excludes China
- **THEN** the route remains visible with all original prices and links and displays a prominent China exclusion advisory

#### Scenario: Region is not explicit
- **WHEN** the material does not reliably say whether China is included
- **THEN** the route displays the original region text and a not-explicit advisory instead of being treated as unavailable

### Requirement: Buy-points collection is not automatic
The AwardWallet buy-points source SHALL remain available for manual operation and historical reads but MUST NOT be selected by the daily automatic source scheduler.

#### Scenario: Daily source selection
- **WHEN** the daily cycle selects automatically scheduled sources
- **THEN** the buy-points source is absent while its manual CLI and stored data remain intact
