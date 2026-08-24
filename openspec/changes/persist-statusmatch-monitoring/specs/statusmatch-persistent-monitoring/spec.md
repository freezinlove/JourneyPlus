## ADDED Requirements

### Requirement: Durable project watch list
The system SHALL persist each active project-specific `*.statusmatch.com` host once and SHALL persist exactly one activity target and one FAQ target for that host.

#### Scenario: Seed existing projects
- **WHEN** monitoring state is backfilled from the current StatusMatch public page source items
- **THEN** each valid host with both required pages is represented by one watch and two page targets without a network request or model call

#### Scenario: Reject non-project hosts
- **WHEN** a candidate host is generic, nested, non-HTTPS, or outside `statusmatch.com`
- **THEN** the system does not create a watch

### Requirement: Change-gated page monitoring
The system SHALL fetch both targets of every active watch on a scheduled check and SHALL create a document version only for a page whose current normalized or raw content differs for the active parser version.

#### Scenario: Neither page changed
- **WHEN** both fetched pages match their existing current content
- **THEN** the check timestamps advance and no document version, model call, fact set, or brief is created

#### Scenario: One page changed
- **WHEN** only the FAQ or only the activity page differs
- **THEN** the system creates one new document version for that page and keeps the other page's current version

#### Scenario: Fetch failure
- **WHEN** a page returns an HTTP error, challenge page, invalid content type, oversized body, or cross-host redirect
- **THEN** the system records a monitoring error, preserves the watch, and does not infer closure

### Requirement: Current two-page snapshot rebuild
The system SHALL interpret a changed project using only the latest activity-page and FAQ-page document versions as the current semantic snapshot while preserving all older records as history.

#### Scenario: Material facts changed
- **WHEN** the latest two-page snapshot produces a materially different validated fact signature
- **THEN** the system creates a new fact-set version and a corresponding brief version for the existing current event

#### Scenario: Presentation-only change
- **WHEN** a changed page produces the same material fact signature as the current fact set
- **THEN** the system reuses the current fact set and brief rather than creating semantic versions

#### Scenario: Obsolete value removed
- **WHEN** the latest two-page snapshot no longer supports a value that appeared only in an older page version
- **THEN** the current rebuilt fact set does not retain that obsolete value while the old fact set and evidence remain queryable

### Requirement: Conservative whole-offer closure
The system SHALL automatically close only a whole StatusMatch project with strong closed/waitlist evidence and no active application path.

#### Scenario: Project-host waitlist landing page
- **WHEN** the activity request resolves within the same project host to a waitlist landing page whose visible content offers only future-interest or waitlist registration
- **THEN** the project is classified as closed

#### Scenario: Whole offer explicitly ended
- **WHEN** current visible content explicitly states that the whole offer has ended or expired and no active application action remains
- **THEN** the project is classified as closed

#### Scenario: Partial offer ended
- **WHEN** a FAQ states that only a region, route, tier, source program, or applicant category ended while the activity page still contains an active application form or continue/apply action
- **THEN** the project remains active

#### Scenario: Incidental await text
- **WHEN** the page contains the word `await` outside a whole-offer closed or waitlist state
- **THEN** that word alone does not close the project

### Requirement: Closure archives business state but preserves history
On confirmed whole-offer closure, the system SHALL archive the associated current event, record closure provenance, and remove only the live watch and its page targets.

#### Scenario: Archive closed project
- **WHEN** a monitored project is confidently classified as closed
- **THEN** its event is excluded from active candidates, its watch is removed, and all source items, document versions, revisions, evidence, fact sets, and briefs remain stored

#### Scenario: New campaign on a former host
- **WHEN** a later genuinely new Gmail message references a host whose earlier watch was removed and whose earlier event is archived
- **THEN** the system onboards the host again and does not merge the new campaign automatically into the archived event

### Requirement: Monitoring is independent from Gmail availability
The system SHALL run checks for existing StatusMatch watches even when Gmail enumeration or message retrieval fails.

#### Scenario: Gmail OAuth failure
- **WHEN** Gmail collection fails during a scheduled cycle
- **THEN** the system still checks the persisted StatusMatch activity and FAQ targets and reports the stages independently
