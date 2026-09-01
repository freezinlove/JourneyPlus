## ADDED Requirements

### Requirement: Product API exposes the minimal local workflow
The product application SHALL expose membership catalog search, StatusHolding list/create/update/delete, personalized reachability, unified briefs, and opportunity detail under stable `/v1` endpoints. It SHALL NOT require authentication in the local single-user release.

#### Scenario: Complete local API flow
- **WHEN** a client searches the catalog, saves a holding, and requests personalized matches
- **THEN** the API returns the saved holding and the reachable graph using only the local database

### Requirement: Holdings page manages current statuses
The product SHALL provide a “我的会籍” page that searches the graph-backed catalog, adds or replaces a program tier, accepts an optional validity date, and deletes a holding.

#### Scenario: Add from catalog
- **WHEN** the user selects a catalog result and submits it
- **THEN** the page displays the normalized saved holding and refreshes without a model call

### Requirement: Match page displays one nearest-path card per membership
The product SHALL provide an “个性化匹配图” page rooted at all saved holdings. It SHALL derive a deterministic multi-source shortest-path projection from the complete reachability response, render each reachable membership exactly once, and retain exactly one minimum-hop incoming edge for every non-root card. It SHALL NOT render cycle edges, cross-reference placeholder cards, or additional non-nearest incoming edges.

#### Scenario: Converging paths and cycle stay out of the canvas
- **WHEN** the personalized response contains multiple arrivals at one membership and a cycle edge
- **THEN** the page renders one card for that membership, keeps one deterministic minimum-hop parent edge, and renders neither duplicate cards nor the cycle edge

#### Scenario: Nearest path wins
- **WHEN** one target is reachable in one hop and through another path in three hops
- **THEN** the page displays the one-hop parent relation and does not draw the longer arrival path

### Requirement: Nearest-path lines show only grounded target-tier fees
The match page SHALL display a compact fee label on a nearest-path line when the backing opportunity has an explicit structured amount for that target tier or explicitly states that the route is free. It SHALL preserve original currencies, display distinct prices from multiple routes without selecting a cheapest route, and omit the label when no reliable fee exists.

#### Scenario: Region routes have different prices
- **WHEN** the target tier costs `USD 175` on one route and `USD 299` on another
- **THEN** the line displays both values and does not present either one as the default or cheapest price

#### Scenario: Fee is unknown
- **WHEN** neither structured prices nor an explicit free cost supports the target tier
- **THEN** the line has no fee label and the page does not infer that the match is free

### Requirement: Brief page displays all existing briefs
The product SHALL provide an “机会简报” page backed by current official and ordinary article briefs. It MUST NOT default-filter briefs by OpportunityKind and MUST NOT trigger brief regeneration on page reads.

#### Scenario: Other brief remains visible
- **WHEN** current briefs contain both `STATUS_MATCH` and `OTHER` opportunities
- **THEN** both are displayed on the brief page and opening or filtering the page causes zero model calls

#### Scenario: Reachable brief navigation
- **WHEN** a brief has a relation reachable from a saved holding
- **THEN** the page can navigate to its opportunity detail or corresponding match node

### Requirement: Opportunity detail presents actionable evidence
The product SHALL provide an opportunity detail page that displays target status, complete application routes, per-tier original-currency prices, China advisory, eligibility, challenge text, dates, conflicts, evidence/source links, brief content, and application entry when those facts are known.

#### Scenario: Paid regional match detail
- **WHEN** an opportunity has multiple region routes and target-tier prices
- **THEN** the page shows every route and its original-currency prices without selecting a cheapest route for China

#### Scenario: Unknown field
- **WHEN** a detail field is not supported by evidence
- **THEN** the page omits it or labels it unknown and does not generate generic or invented content

### Requirement: Pages share one lightweight product shell
The four product pages SHALL be served by the existing Python application with package-local HTML/CSS/JavaScript and SHALL share navigation and responsive styling. The implementation MUST NOT require a Node build, external CDN, or a separate frontend deployment.

#### Scenario: Local product startup
- **WHEN** the product server starts from its CLI entrypoint
- **THEN** all four pages and their same-origin API/assets are available from one FastAPI process
