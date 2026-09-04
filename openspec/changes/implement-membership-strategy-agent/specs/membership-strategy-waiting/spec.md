## ADDED Requirements

### Requirement: One minimal adjustment before waiting
When no route satisfies the current target and hard constraints, the Agent SHALL propose at most one minimal adjustment selected from `nearby_routes`; the program SHALL apply only that confirmed adjustment and rerun the candidate query.

#### Scenario: One-condition nearby route exists
- **WHEN** there are no `matching_routes` and at least one route violates exactly one hard condition
- **THEN** the Agent proposes one specific change, explains what it unlocks and its trade-off, and waits for confirm, modify, or reject

#### Scenario: User confirms the adjustment
- **WHEN** the user explicitly confirms the proposed adjustment
- **THEN** the system changes only that condition and reruns candidate lookup

#### Scenario: User rejects the adjustment
- **WHEN** the user rejects the proposed adjustment
- **THEN** the system keeps the original conditions and MUST NOT automatically relax another condition

### Requirement: Agent-initiated continuous-follow-up offer
The Agent SHALL proactively offer continued tracking under the current user-approved conditions when the user rejects the single adjustment or when the adjusted query still has no matching route.

#### Scenario: Rejected adjustment leads to follow-up choice
- **WHEN** the user rejects the one proposed adjustment
- **THEN** the next Agent response asks whether to continue tracking the unchanged target and conditions and permits confirm, modify, or reject

#### Scenario: Confirmed adjustment still has no solution
- **WHEN** the rerun after a confirmed adjustment has no `matching_routes`
- **THEN** the Agent offers tracking under the resulting confirmed conditions instead of proposing another adjustment

#### Scenario: User rejects continued tracking
- **WHEN** the user rejects the follow-up offer
- **THEN** the interaction ends without creating a wait goal

### Requirement: Single confirmed wait goal
The program SHALL create or replace at most one ACTIVE wait goal only after explicit user confirmation, and SHALL persist its normalized target, hard constraints, confirmed holdings reference, status, candidate signature, and pending first-hit result.

#### Scenario: User confirms tracking
- **WHEN** an interaction is awaiting follow-up confirmation and the user explicitly confirms
- **THEN** `WaitGoalService` validates the state and saves one ACTIVE goal

#### Scenario: Unconfirmed interpretation attempts to save
- **WHEN** the model or client requests a wait-goal write before the required no-solution flow and user confirmation
- **THEN** the Controller rejects the write and no goal is created

#### Scenario: A goal already exists
- **WHEN** the user confirms a new or modified wait goal while another goal is ACTIVE
- **THEN** the service replaces or closes the previous goal atomically so only one remains active

### Requirement: Deterministic daily wait check
The existing daily automation SHALL check the ACTIVE wait goal after normal fact and lifecycle processing by calling the candidate route service without a model call unless a previously unseen matching route appears.

#### Scenario: No matching route appears
- **WHEN** the daily check returns no `matching_routes`
- **THEN** it records a no-hit summary, does not call the Agent model, and does not produce a user-visible result

#### Scenario: Same candidate signature remains
- **WHEN** matching routes produce a signature already handled for the goal
- **THEN** the daily check performs no Agent call and creates no duplicate result

#### Scenario: Wait checking fails
- **WHEN** candidate checking or Agent resume fails
- **THEN** the failure is isolated in the daily summary, the main automation result remains available, and an unhandled signature is not marked delivered

### Requirement: First-hit Agent resume and one-time result
On the first unseen matching-route signature, the system SHALL resume the same strategy Agent with the saved goal and new candidate observation, optionally research authorized StatusMatcher evidence, and store one pending application result.

#### Scenario: First new route appears
- **WHEN** the daily check finds a previously unseen `matching_routes` signature
- **THEN** the Agent creates a fresh personalized recommendation for the saved trade-offs and the goal stores it as a pending first-hit result

#### Scenario: User reads the pending result
- **WHEN** the frontend calls `GET /v1/agent/state`
- **THEN** the response includes the pending first-hit recommendation once and the service records it as seen without creating a separate notification entity

### Requirement: Wait goal lifecycle management
The user SHALL be able to inspect, modify, cancel, or finish the current wait goal through the Agent turn API, and accepted/cancelled/completed goals SHALL no longer be checked.

#### Scenario: User modifies wait conditions
- **WHEN** the user submits a modification to the active goal and confirms the normalized change
- **THEN** the service updates the goal, resets candidate-signature tracking as needed, and continues with one active goal

#### Scenario: User cancels tracking
- **WHEN** the user explicitly cancels the active goal
- **THEN** its status becomes cancelled and subsequent daily runs skip it

