## ADDED Requirements

### Requirement: Explicitly gated experience research
The system MUST keep automated StatusMatcher research disabled by default and SHALL expose it to the Agent only when server-side authorization is enabled, at least one formal candidate exists, and the user requested or accepted real-experience research.

#### Scenario: Research is not authorized
- **WHEN** authorization is disabled or the user has not requested experience research
- **THEN** the Controller does not expose an executable StatusMatcher action and the Agent completes from JourneyPlus facts with a clear availability note

#### Scenario: No formal candidate exists
- **WHEN** candidate lookup returns no `matching_routes`
- **THEN** StatusMatcher is not queried and MUST NOT be used to discover a database-external route

#### Scenario: Research is allowed
- **WHEN** authorization is enabled, the user requested experience evidence, and the Agent has selected no more than three formal candidates
- **THEN** the Controller may research only those candidates within the configured request and time budgets

### Requirement: Restricted StatusMatcher access
The StatusMatcher client SHALL make read-only HTTPS requests only to allowlisted `statusmatcher.com` company pages resolved by program aliases, with fixed timeouts, response-size limits, page limits, and a declared User-Agent.

#### Scenario: Model supplies an arbitrary URL
- **WHEN** an Agent decision includes a URL outside the allowlisted host or expected company-page shape
- **THEN** the Controller rejects it and the client performs no request

#### Scenario: Program page cannot be resolved reliably
- **WHEN** the normalized target program cannot be mapped to one StatusMatcher company page
- **THEN** the tool returns `UNAVAILABLE` without guessing a slug or broadening to web search

### Requirement: Comparable report observations
The client SHALL extract only reports for obtaining the candidate target, compare normalized source and target program/tier text, and return structured counts for `MATCH`, `CHALLENGE`, `DENY`, and `OTHER` plus bounded summaries and source-page links.

#### Scenario: Comparable reports are present
- **WHEN** the target company page contains visible reports whose source and target programs match the candidate route
- **THEN** the result includes categorized observation counts, sample size, recurring practical signals, observed time, and the StatusMatcher page URL

#### Scenario: Reports are not comparable
- **WHEN** reports concern a different source program, reverse direction, or unrelated target
- **THEN** they are excluded from route-specific counts

### Requirement: Community evidence wording and isolation
The system MUST describe StatusMatcher results as self-reported experience signals, MUST NOT call an observed ratio the true approval probability, and MUST NOT write observations into official facts, lifecycle state, or the unified membership graph.

#### Scenario: Most visible reports are matches
- **WHEN** comparable reports contain more `MATCH` observations than other outcomes
- **THEN** the Agent may describe the experience signal as stronger while still stating the sample basis and absence of approval guarantee

#### Scenario: Experience conflicts with official facts
- **WHEN** a community report differs from JourneyPlus official facts
- **THEN** official facts remain authoritative and the Agent presents the community item only as a caution or discrepancy

### Requirement: Safe research degradation
Network errors, timeouts, blocked access, changed HTML, insufficient samples, or parser failures SHALL produce a typed degraded result and SHALL NOT prevent a recommendation based on formal JourneyPlus facts.

#### Scenario: StatusMatcher request times out
- **WHEN** a request exceeds the configured timeout
- **THEN** the tool returns a timeout/unavailable observation and the Agent continues without retrying beyond its budget or searching other sites

#### Scenario: Page structure is unsupported
- **WHEN** no expected obtaining-report section can be parsed
- **THEN** the tool returns insufficient/unavailable evidence without storing the response body

