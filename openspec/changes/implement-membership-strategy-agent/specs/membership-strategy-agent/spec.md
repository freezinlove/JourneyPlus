## ADDED Requirements

### Requirement: Natural-language strategy turns
The system SHALL accept a user's natural-language description of held memberships, desired target, hard constraints, and preferences through one Agent turn API, and SHALL return a typed interaction state with the Agent's next user-visible action.

#### Scenario: Sufficient request starts candidate query
- **WHEN** the user names an unambiguous existing holding, a target, and enough constraints to query safely
- **THEN** the Agent structures the request, requests confirmation for any new holding that would be persisted, and proceeds to candidate lookup after confirmation

#### Scenario: Existing confirmed holding is reused
- **WHEN** a request refers to a holding already stored with the same normalized program and tier
- **THEN** the system reuses the confirmed holding without asking the user to confirm it again

### Requirement: Bounded clarification and confirmation
The Agent SHALL ask at most one critical clarification question per interaction when ambiguity would change normalization, persistence, or candidate results, and the program MUST prevent unconfirmed or non-unique holdings from being persisted.

#### Scenario: Ambiguous catalogue match
- **WHEN** a described program or tier cannot be uniquely resolved against the current membership catalogue
- **THEN** the Agent asks one concise question and stores no new `StatusHolding`

#### Scenario: User confirms interpreted holding
- **WHEN** the user explicitly confirms a uniquely resolved pending holding
- **THEN** `StatusHoldingService` validates it again and persists it before the route query continues

#### Scenario: User modifies interpreted holding
- **WHEN** the user changes a pending holding in natural language
- **THEN** the Agent replaces the pending interpretation, revalidates it, and does not persist the previous interpretation

### Requirement: Fact-only candidate route query
The system SHALL query the current unified membership graph and official fact read models from confirmed holdings and SHALL return `matching_routes`, `nearby_routes`, and `unknown_routes` without selecting a recommended route.

#### Scenario: All target and hard constraints are proven
- **WHEN** a current reachable path matches the explicit program, tier, or alliance target and every hard constraint is supported by facts
- **THEN** the route appears in `matching_routes` with its node path, step opportunity references, costs, challenge/condition text, deadlines, conflicts, and evidence links

#### Scenario: Exactly one hard constraint fails
- **WHEN** a route matches the target but violates exactly one proven hard constraint
- **THEN** the route appears in `nearby_routes` with that one violation identified

#### Scenario: A hard constraint cannot be proven
- **WHEN** a route matches the target but a required fee, challenge, or comparable-currency fact is absent or indeterminate
- **THEN** the route appears in `unknown_routes` with the unknown item and MUST NOT be presented as satisfying the constraint

#### Scenario: Relative alliance tier request
- **WHEN** the user asks for a relative target such as a high SkyTeam tier and no normalized alliance-tier equivalence exists
- **THEN** the program filters by the structured alliance, leaves relative tier choice to the Agent, and exposes the equivalence limitation in the route facts

### Requirement: Agent-owned personalized recommendation
The Agent SHALL use the user's stated trade-offs and the fact-only route observations to choose one primary route and no more than two materially distinct alternatives, or SHALL explain why no safe recommendation exists.

#### Scenario: Several feasible routes have different trade-offs
- **WHEN** multiple `matching_routes` differ in fee, steps, challenge, validity, risk, or evidence confidence
- **THEN** the Agent selects and explains a primary route based on the user's expressed priorities and may show at most two distinct alternatives

#### Scenario: Program ordering is not a recommendation
- **WHEN** the candidate service returns routes in a stable technical order
- **THEN** the Agent independently decides the user-visible primary and alternatives and MUST NOT describe the technical order as a program-generated ranking

#### Scenario: Only unknown routes exist
- **WHEN** there are no matching routes and one or more `unknown_routes`
- **THEN** the Agent identifies the missing facts and MUST NOT claim that an unknown route is feasible or guaranteed

### Requirement: Genuine bounded Agent action selection
For each model call the Controller SHALL expose only the actions legal in the current interaction state, validate the structured decision, and allow the same Agent to select different next actions from user input and tool observations.

#### Scenario: Observation changes the next action
- **WHEN** candidate observations contain feasible routes, no feasible route, or a material unknown
- **THEN** the Agent can respectively choose recommendation/research, one minimal adjustment, or an uncertainty response within the allowed action set

#### Scenario: Model attempts an illegal action
- **WHEN** the model requests a write, network lookup, or transition not allowed in the current state
- **THEN** the Controller rejects the action without executing it and returns a bounded failure or one permitted recovery

#### Scenario: Model-call budget is exhausted
- **WHEN** three model calls have been attempted in one HTTP turn including any structured-output repair
- **THEN** the Controller stops and returns an explicit incomplete/degraded result

### Requirement: API and frontend responsibility boundary
The system SHALL expose `GET /agent`, `POST /v1/agent/turn`, and `GET /v1/agent/state`; the frontend SHALL render typed server state and submit user input or choices without implementing business rules.

#### Scenario: Frontend submits a turn
- **WHEN** the user sends natural language or selects confirm, modify, reject, or cancel
- **THEN** the frontend sends a typed turn request and renders the server-provided message, evidence, results, and allowed actions

#### Scenario: Agent provider is unavailable
- **WHEN** the product service starts without valid AI configuration
- **THEN** existing deterministic pages and APIs remain operational while Agent endpoints and UI report that the Agent is unavailable

### Requirement: Minimal durable Agent state
The system SHALL persist only the structured short-term interaction data required to resume confirmations and SHALL NOT persist model chain-of-thought, unbounded chat history, member numbers, proof documents, or full external report bodies.

#### Scenario: Interaction resumes after process restart
- **WHEN** a valid non-expired interaction ID is submitted after the API process restarts
- **THEN** the server restores its typed phase and pending structured data from the database

#### Scenario: Interaction expires
- **WHEN** a user tries to continue an interaction after its expiration time
- **THEN** the system refuses to mutate it and asks the user to start a new request

