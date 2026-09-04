## 1. Contracts and persistence foundation

- [x] 1.1 Add typed Agent, candidate-route, StatusMatcher observation, interaction, wait-goal, and API contracts with strict validation and bounded collections.
- [x] 1.2 Add minimal `AgentInteraction` and `AgentWaitGoal` SQLAlchemy models plus an Alembic migration with one-active-goal constraints/indexes.
- [x] 1.3 Add Agent and StatusMatcher runtime settings with safe defaults, validation, and product/CLI dependency injection.
- [x] 1.4 Add migration and contract tests covering upgrade/downgrade, defaults, invalid states, and collection limits.

## 2. Fact-only candidate routes

- [x] 2.1 Implement `CandidateRouteService` over confirmed holdings and the existing unified graph, including bounded shortest acyclic route reconstruction with step opportunity references.
- [x] 2.2 Implement explicit target matching and conservative hard-condition classification into `matching_routes`, one-condition `nearby_routes`, and `unknown_routes` without subjective ranking.
- [x] 2.3 Include route comparison facts, official evidence links, conflicts, alliance limitation notes, and deterministic signatures without duplicating graph or fact storage.
- [x] 2.4 Add candidate-query tests for exact program/tier, alliance targets, free/paid/unknown cost, challenge/unknown challenge, one-condition near routes, multi-step paths, and no holdings.

## 3. Single Agent runtime and natural-language flow

- [x] 3.1 Add versioned prompts and structured model decisions for request interpretation, legal next-action selection, personalized recommendation, minimal adjustment, and waiting offer.
- [x] 3.2 Implement interaction persistence and a thin Controller with explicit action dispatch, dynamic allowed actions, confirmation/write guards, expiry, action audit, and a three-call limit.
- [x] 3.3 Integrate catalogue resolution and `StatusHoldingService` so new natural-language holdings are persisted only after explicit confirmation while existing holdings are reused.
- [x] 3.4 Implement Agent-owned selection of one primary and at most two distinct alternatives, evidence/risk explanations, unknown handling, and safe Provider degradation.
- [x] 3.5 Add deterministic Provider replay tests proving different observations choose different actions, illegal actions are rejected, confirmation gates hold, and budgets stop loops.

## 4. Controlled StatusMatcher experience research

- [x] 4.1 Implement an allowlisted, timeout/size/page-bounded StatusMatcher client and company-page resolver with no arbitrary URL access.
- [x] 4.2 Parse obtaining-status reports into comparable `MATCH/CHALLENGE/DENY/OTHER` observations, bounded practical summaries, sample signal, and source links.
- [x] 4.3 Gate research on server authorization, user intent, formal candidates, and the three-candidate limit; isolate it from official facts and degrade without web fallback.
- [x] 4.4 Add fixed-HTML parser, authorization, direction/comparability, URL-policy, timeout, insufficient-evidence, and Agent-integration tests.

## 5. No-solution adjustment and continuous follow-up

- [x] 5.1 Implement the one-adjustment flow and enforce transition to an Agent-initiated follow-up offer after rejection or a still-empty adjusted query.
- [x] 5.2 Implement `WaitGoalService` for explicit confirmation, atomic single-active-goal replacement, read/modify/cancel/finish, candidate signatures, and pending first-hit results.
- [x] 5.3 Integrate deterministic wait checking after daily lifecycle processing so no hit/same signature uses zero Agent calls and first unseen hit resumes the same Agent once.
- [x] 5.4 Add transition, write-guard, single-goal, no-hit, deduplication, first-hit, retry-isolation, and lifecycle tests.

## 6. Product API and frontend

- [x] 6.1 Add `GET /agent`, `POST /v1/agent/turn`, and `GET /v1/agent/state` with typed errors and optional Provider/tool availability that does not affect existing APIs.
- [x] 6.2 Build the Agent page in the existing static frontend to submit natural language, show confirmations/allowed choices, render routes/evidence/experience/risks, and manage the current wait goal without frontend business logic.
- [x] 6.3 Update navigation, accessibility, responsive styles, cache versions, CLI startup, and operational documentation for Agent availability and StatusMatcher enablement.
- [x] 6.4 Add API/frontend contract tests for all interaction states, unavailable dependencies, database errors, and unchanged deterministic pages.

## 7. End-to-end verification

- [x] 7.1 Run focused and full pytest suites, architecture checks, migration checks, formatting/static sanity checks, and fix regressions.
- [x] 7.2 Seed or use the actual local database, submit representative Chinese natural-language requests, follow returned confirmation/adjustment/waiting choices, and record observed end-to-end results.
- [x] 7.3 Manually compare returned holdings, paths, opportunity facts, and evidence against the database/unified graph and compare one authorized experience result against the current StatusMatcher page.
- [x] 7.4 Reconcile implementation, OpenSpec artifacts, Agent direction, technical baseline, and operations documentation; record known data limitations without claiming unsupported precision.
