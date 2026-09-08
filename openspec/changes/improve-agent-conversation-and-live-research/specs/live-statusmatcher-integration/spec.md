## ADDED Requirements

### Requirement: Verified live research wiring
The unified agent SHALL receive an explicitly configured researcher with verified programme-page and report identity mappings; isolated preview can enable live public reads while production remains disabled by default.

#### Scenario: Mapped step research
- **WHEN** user requests application experiences for a displayed supported step
- **THEN** real company and report pages are read within budgets, comparable reports are attached to that step, and citations open original report URLs

### Requirement: Honest research scope and failure
Research SHALL distinguish unverified mapping, HTTP failure, parse failure, no reports and insufficient comparable reports; observations remain temporary and do not overwrite official facts.

#### Scenario: Site error
- **WHEN** the company page returns HTTP 500
- **THEN** the response states research is unavailable rather than claiming no applicants or a zero success rate

#### Scenario: Repeated research
- **WHEN** the same still-valid step is researched again within a workspace
- **THEN** applicable observations are reused and their date and scope remain visible

### Requirement: Real end-to-end evidence
Release readiness SHALL include live list/detail parsing, comparable report selection and Agent/browser linkage, not only fixtures.

#### Scenario: Supported project acceptance
- **WHEN** live integration is reported ready
- **THEN** at least one programme passes the full chain and a second programme has an honestly documented live outcome; user-reported sample ratios are not presented as approval probability
