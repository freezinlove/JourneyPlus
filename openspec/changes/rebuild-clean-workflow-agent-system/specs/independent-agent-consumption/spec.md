## ADDED Requirements

### Requirement: Replaceable model and generic harness
The harness SHALL manage the generic model-tool loop, protocol, budgets, cancellation, recovery, and tracing through ports. It SHALL NOT depend on business ORM, fixed loyalty workflows, brand-specific behavior, or hidden decision models.

#### Scenario: Replace the decision core
- **WHEN** a compatible ModelPort implementation replaces the current provider
- **THEN** the same harness, tools, database path, and user-facing API remain in use without changing business logic

### Requirement: Independent explicit tools
Tools SHALL accept explicit inputs and return interpretable observations, stable references, coverage, and errors. Tools SHALL NOT hide calls to other tools as business orchestration, require guessed internal identifiers, or start knowledge production.

#### Scenario: Tool rejects a parameter
- **WHEN** the model issues an invalid tool request
- **THEN** the harness returns a usable error to the model, which can choose its next action within the budget

### Requirement: Faithful progressive context
Context assembly SHALL preserve user constraints and corrections, distinguish assumptions from persisted facts, and retain evidence and continuation references. Progressive disclosure and compression SHALL NOT silently discard unread results or change their meaning.

#### Scenario: Resume a large result after correction
- **WHEN** a user corrects a condition during a multi-page or long-history conversation
- **THEN** subsequent model input preserves the correction, distinguishes earlier results, and permits explicit access to relevant remaining information

### Requirement: Delivery tied to actual outcomes
The system SHALL distinguish success, partial completion, cancellation, and failure using actual operations and artifacts. Structured output validity and model-declared completion SHALL NOT alone establish semantic correctness. The page SHALL show readable answers, progress, and actionable errors.

#### Scenario: Budget exhausted before completion
- **WHEN** the run reaches a resource limit before fulfilling the request
- **THEN** the page identifies incomplete work and preserves available results without reporting a completed business outcome

#### Scenario: User cancels an in-flight write
- **WHEN** a user cancels while an authorized write may already have committed
- **THEN** the recovered result reports the actual receipt and cancellation state without inventing a rollback or repeating the effect

### Requirement: Human ModelPort on the normal web path
Human acceptance SHALL replace only the ModelPort decision core behind the normal webpage. The human decision maker SHALL receive the actual model-visible request and submit the same response protocol. Observer evidence SHALL be correlated to that same run and reviewed separately from decision input.

#### Scenario: Human performs a path query
- **WHEN** the tester sends a membership request through the normal webpage
- **THEN** the human core chooses tool calls from the actual provided context, receives normal tool observations, and delivers a result through the same API and page used by the provider core

### Requirement: Correctness-preserving context efficiency
Context optimization SHALL follow correctness acceptance and compare equivalent scenarios and knowledge versions. Evaluation SHALL record per-request and per-turn token usage, call counts, latency, and correctness rather than using byte counts alone as token evidence.

#### Scenario: Compact repeated observations
- **WHEN** repeated tool output is replaced with a compact representation
- **THEN** relevant constraints, evidence, continuation, and operation outcomes remain accessible and the same scenarios retain correct answers and behavior
