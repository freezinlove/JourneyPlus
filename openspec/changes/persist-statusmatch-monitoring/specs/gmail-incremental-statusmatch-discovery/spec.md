## ADDED Requirements

### Requirement: Successfully processed messages are not reread
The system SHALL enumerate candidate Gmail message IDs using the dedicated label and recipient query and SHALL download full content only for an unseen message or a message whose prior processing did not succeed.

#### Scenario: Existing successful message
- **WHEN** an enumerated Gmail message already has a successfully persisted message document
- **THEN** the system does not call Gmail full-message retrieval for that ID

#### Scenario: Previously failed message
- **WHEN** an enumerated Gmail message has no successful persisted document because an earlier attempt failed
- **THEN** the system may download and retry that message

#### Scenario: Local parser upgrade
- **WHEN** stored mail requires a parser-version replay
- **THEN** the system reprocesses the restricted local snapshot instead of downloading the Gmail message again

### Requirement: Existing watched hosts are ignored during email discovery
The system SHALL normalize StatusMatch links extracted from a newly read Gmail message to a project host before deciding whether public pages need onboarding.

#### Scenario: Link already watched
- **WHEN** a newly processed Gmail message contains a StatusMatch project host that exists in the live watch list
- **THEN** the system stores the message result but does not fetch that project's activity or FAQ page

#### Scenario: Duplicate links in one or more new messages
- **WHEN** multiple links normalize to the same project host
- **THEN** the system attempts to onboard that host at most once

### Requirement: Unknown email host is onboarded with two pages
The system SHALL create a pending watch and fetch both required public pages when a newly processed Gmail message contains a valid project host absent from the live watch list.

#### Scenario: Successful onboarding
- **WHEN** both activity and FAQ pages are valid and the project is not closed
- **THEN** the watch becomes active, both current page versions are recorded, and the two-page project is processed into a current event

#### Scenario: Initial pages show closure
- **WHEN** the first activity/FAQ fetch confidently shows that the whole offer is closed
- **THEN** the system preserves any fetched page history but does not retain the project in the live watch list

#### Scenario: Initial fetch fails
- **WHEN** one required page cannot be fetched or validated
- **THEN** the pending watch remains retryable with its error recorded and no false active event is published

### Requirement: Removed watches are not recreated from old mail
The system SHALL NOT recreate a removed StatusMatch watch by rereading an already successfully processed Gmail message.

#### Scenario: Closed watch with historical message
- **WHEN** a project watch was removed after closure and its original Gmail message remains labeled
- **THEN** a later cycle skips that old message and does not recreate the watch

#### Scenario: New message references removed host
- **WHEN** a different unseen Gmail message later references the same host
- **THEN** the absent host is treated as a new onboarding candidate
