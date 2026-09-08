## ADDED Requirements

### Requirement: Natural grounded conversation
The agent SHALL answer the current question in natural language, preserve verified financial and eligibility facts, and place structured detail in cards and graphs without unconditional template replacement.

#### Scenario: Follow-up asks for missing eligibility
- **WHEN** user asks what remains to be verified after viewing a route
- **THEN** the answer identifies relevant missing user information and missing source facts instead of repeating the route introduction

#### Scenario: Critical restriction
- **WHEN** a restriction affects whether the user can apply
- **THEN** prose mentions it and the detail retains its evidence; UNKNOWN is not presented as PASS or free

### Requirement: Explicit unrestricted task scope
The workspace SHALL retain temporary intent and distinguish unspecified scope from explicitly unrestricted scope without extra model classification calls.

#### Scenario: Repeated broad request
- **WHEN** user says “所有都行” then “酒店和航司都要” after requesting public opportunities
- **THEN** agent searches the requested broad scope without asking for a preferred programme again and without using saved holdings as the hypothetical starting point

### Requirement: Grounded presentation references
The agent SHALL understand visible order and selected objects through bounded presentation summaries and validated stable references.

#### Scenario: Selected second route
- **WHEN** user asks “第二条贵在哪里” or clicks a node and asks about its documents
- **THEN** the corresponding displayed route or step is used; browsing invokes zero model calls and next-step suggestions create visible user messages

### Requirement: Bounded efficient reads
The system SHALL validate reference identity and version, reuse applicable reads, disclose relevant data progressively, and preserve pagination coverage.

#### Scenario: Fees and validity
- **WHEN** user requests one activity's fees and validity
- **THEN** relevant facts are returned without unrelated full mappings and valid disclosed references resolve to the correct version

#### Scenario: All candidates
- **WHEN** user requests all opportunities
- **THEN** search scope remains broad, presentation is paged, and the model does not receive the entire database

### Requirement: Explicit model parameters and measurements
Agent requests SHALL explicitly choose thinking mode and record provider, reasoning, cache and timing metrics without exposing secrets or reasoning text.

#### Scenario: Routine turn
- **WHEN** the standard agent makes a routine request
- **THEN** thinking is disabled, actual timeout is bounded, and AIWorkflow defaults are not silently changed

### Requirement: Recoverable verified streaming
The system SHALL deliver real phase events, incrementally generated validated prose, complete blocks and a durable terminal state using turn identity and ordered resumable events.

#### Scenario: Streaming response
- **WHEN** a route response is generated
- **THEN** the user sees immediate feedback and real stages, prose arrives progressively, and cards appear only after validation without internal JSON or thought text

#### Scenario: Connection lost
- **WHEN** the stream disconnects and the page reconnects or refreshes
- **THEN** events resume without duplicate turns, messages or writes, and an interrupted generation is explicitly marked incomplete

### Requirement: Real conversational acceptance
Acceptance SHALL replay complete user conversations and unseen phrasing variants, measure end-to-end latency and aggregate token use, and preserve failures.

#### Scenario: Acceptance report
- **WHEN** a stage is marked accepted
- **THEN** its report distinguishes deterministic tests, live model/database/browser checks, performance targets and observed limitations; schema-valid alone is not business success

#### Scenario: Existing holding with all targets
- **WHEN** user says “我有万豪白金，给我所有可能的匹配路径” and follows with “所有活动都给我列出来，我不知道有啥会籍”
- **THEN** the agent resolves the existing programme and tier independently of activity lookup, searches all targets with that temporary starting tier, retains it on continuation, and never asks for an optional target or source activity

#### Scenario: Missing source programme
- **WHEN** user only identifies a rank such as Gold without a programme
- **THEN** the agent asks for the source programme and does not treat a programme-name substring match as the user's holding

#### Scenario: Target-only continuation
- **WHEN** a user changes only the target after establishing a starting membership
- **THEN** execution retains the existing starting tier and rejects attempts to replace it with target tiers unless a source change is explicitly requested

#### Scenario: Optional collection compatibility
- **WHEN** a model uses null for an unused optional list with an empty-list default
- **THEN** the workspace treats it as omitted without another model request while still rejecting invalid actions, required empty data and undisclosed references

#### Scenario: Broad continuation after earlier failed answers
- **WHEN** a user repeats the unrestricted request in a workspace containing previous incorrect clarifications
- **THEN** task completion still requires actual route evaluation and cannot be bypassed by putting an optional-target question in an ANSWER action

#### Scenario: All routes to a selected destination with missing source
- **WHEN** a user requests all paths to a named destination but only gives a source rank, then supplies the source programme
- **THEN** the clarification retains the selected destination, the actual query contains that target, and unrelated destinations are not returned even if scope defaults disagree with supplied target IDs

#### Scenario: Partial scope updates
- **WHEN** a user supplies a missing source or changes only one query condition
- **THEN** other established conditions survive; removing a target requires an explicit change, and unresolved selected targets cannot execute as unrestricted searches

#### Scenario: Elliptical source switch
- **WHEN** the user asks about another named membership after a source-to-target query
- **THEN** the next query uses that new source and retains the target without requiring the user to repeat the complete route question

#### Scenario: Returning to a source for broad exploration
- **WHEN** the user returns to a previously supplied source and explicitly requests all its matching paths
- **THEN** the first response evaluates that source across the requested target scope rather than re-executing the previous source-to-target query
