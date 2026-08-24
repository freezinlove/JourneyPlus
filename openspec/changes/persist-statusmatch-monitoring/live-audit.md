# Live validation audit — 2026-08-24

## Local PostgreSQL migration

- Created and verified a custom-format PostgreSQL backup at `.secrets/backups/statusmatch-monitoring-pre-0006-20260824.dump` before migration.
- Upgraded the live local database from `0005_document_parser_versions` to `0006_statusmatch_monitoring`.
- Backfill result: 8 watches, 16 page targets, 16 current document references, and one unambiguous current event association per watch.

## Gmail incremental behavior

- The dedicated Gmail query returned exactly 2 current message IDs.
- With the migrated database, the incremental adapter made 0 full-message retrieval calls and 0 public StatusMatch page calls for those existing messages.
- The audit transaction was rolled back. No private message body, tracking identifier, or member data is recorded here.

## Eight current projects

Each activity page and FAQ was opened in the in-app browser, visually inspected, and independently fetched through the production fetch/normalization/classification path.

| Host | Activity-page observation | FAQ observation | Classification |
| --- | --- | --- | --- |
| `airastana.statusmatch.com` | Active member form and Continue button | Current Nomad Club offer details | Active |
| `clubavolta.statusmatch.com` | Active member form and Continue button | Current Club Avolta offer details | Active |
| `enrich.statusmatch.com` | Active member form and Continue button | Current Enrich offer details | Active |
| `flyingblue.statusmatch.com` | Active member form and Continue button | Current offer plus a scoped “Recently ended offers” section | Active |
| `ghadiscovery.statusmatch.com` | Active member form and CONTINUE button | Current GHA DISCOVERY offer details | Active |
| `kenya-airways.statusmatch.com` | Active member form and Continue button | Current Asante Rewards offer details | Active |
| `rj.statusmatch.com` | Active member form and CONTINUE button | Current Royal Jordanian offer details, including scoped eligibility limits | Active |
| `vietnamairlines.statusmatch.com` | Active member form and CONTINUE button | Current Lotusmiles offer details | Active |

The live monitor fetched all 16 targets successfully. Fifteen were hash-equivalent to the stored current versions. The Flying Blue FAQ was the only changed page: the “Recently ended offers” heading moved so the China/Hong Kong/Taiwan table is now explicitly in the ended group. The change was committed as one new document version and processed alone. It linked to the existing event, created the current two-page-snapshot fact/brief version, and did not archive the project.

## Closure and partial-closure boundaries

| Host | Original-page observation | Classifier outcome |
| --- | --- | --- |
| `lufthansa.statusmatch.com` | Activity redirects within the same host to `waitlist.php`; visible page offers only future-opportunity waitlist registration; FAQ says the offer expired | Closed and removable from monitoring |
| `canada.statusmatch.com` | FAQ says the offer ended, but the activity URL redirects outside the project host | Fetch error/review; not auto-closed without a trustworthy current activity-page state |
| `etihad.statusmatch.com` | FAQ says an Australian complimentary sub-offer ended, while the homepage still has an active paid-match application form | Active; partial route closure only |
| `rj.statusmatch.com` | FAQ removes Gold for a scoped hotel-applicant group, while the homepage still has an active application form | Active; partial tier/source closure only |

The rule does not use a bare `await` substring. HTTP errors, challenge pages, and cross-host redirects never produce automatic closure.
