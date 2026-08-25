## Real acceptance: LoyaltyLobby Kenya Airways / Accor

Date: 2026-08-25 (Asia/Shanghai)

### Materials inspected

- Third-party article: `https://loyaltylobby.com/2026/08/03/kenya-airways-skyteam-elite-plus-platinum-match-for-all-accor-gold-platinum-diamond/`
- Allowed machine body: LoyaltyLobby RSS page 11 entry, GUID `https://loyaltylobby.com/?p=259567`; stored raw Feed body length 17,782 and normalized body length 13,880.
- Managed project: `kenya-airways.statusmatch.com`.
- Visible official pages manually inspected in the in-app browser:
  - `https://kenya-airways.statusmatch.com/`
  - `https://kenya-airways.statusmatch.com/faq`
- The article page was opened only for manual visible verification. Machine extraction and persistence used the Feed body and did not fetch the article page through the source adapter.

### Deterministic routing result

- Article document: `52072d7e-6d2f-4a0b-9de6-8e41285663aa`.
- Raw HTML contains repeated affiliate links such as `https://kenya-airways.statusmatch.com/?fpr=91n9n4`; all canonicalized to one project route at `https://kenya-airways.statusmatch.com/`.
- Route: `ff8d6dff-2684-4860-8e38-d4cba7847702`.
- Exact attached event: `2d73e719-8d84-4e1d-a402-9c2640c67318`.
- The project already existed as ACTIVE watch `f9458f11-6229-4fb1-8050-2829a30e1d67`, so article preparation made zero page requests and reused:
  - HOME document `b5033178-2e21-4478-ae54-8087182dc5d2`;
  - FAQ document `0f2449a7-2ccd-4f01-929a-ec67047bd79c`;
  - FactSet `d8cfba8a-f7ce-4301-83e6-5511bed8278f`;
  - Brief `e97bd7b0-d8e9-4156-927e-baca8fec713a`.
- The watch and page `last_checked_at` values remained `2026-08-24 13:45:48.833544+00:00`, proving the article did not trigger an official refresh.
- Database audit found zero `STATUS_RELEVANCE`, `EVENT_RELATIONSHIP`, `FACT_CONSOLIDATION`, or generic `BRIEF_GENERATION` runs for the article document.

### Human review of the source relationship

The original article visibly links the Kenya Airways StatusMatch host and describes the same current Asante Rewards offer represented by the existing event: airline, hotel and credit-card inputs; Silver/Gold/Platinum outputs; the Accor Gold/Platinum/Diamond exception for Platinum; regional fees; and current HOME/FAQ application details. Exact-host attachment is therefore correct. No evidence supports creating a second generic event or relating the article to another host.

### Human review of current supplemental highlights

Current supplement: `6b96fc62-3152-47f1-8d4c-d7905aaa5166`, analysis run `ce7b2287-50e2-47b8-82d1-b5152a0d6894`, prompt `statusmatch-third-party-highlights-v7`.

1. `FACTUAL_DETAIL`: SkyTeam Elite Plus includes all SkyPriority services and lounge access on most itineraries.
   - Exact Feed/article excerpt: “Comes with all SkyPriority services and also lounge access on most itineraries.”
   - Judgment: supported, practically important, and absent from the current FactSet/Brief. The “most itineraries” limitation is retained.
2. `FACTUAL_DETAIL`: SkyTeam Elite includes extra baggage, priority check-in and baggage drop-off.
   - Exact excerpt: “Comes with extra luggage allowance and priority check-in and baggage drop-off.”
   - Judgment: supported, useful for value assessment, and not stated in the current FactSet/Brief.
3. `EDITORIAL_OBSERVATION`: the author is uncertain about Asante's usefulness as a crediting program and the maturity of partner award charts and booking.
   - Exact excerpt begins: “I am not sure, however, how well this Asante works as a crediting program...”
   - Judgment: correctly attributed as the author's uncertainty rather than an official or verified defect; useful as an additional decision consideration.
4. `FACTUAL_DETAIL`: a denied-application refund is processed immediately and usually appears within seven days depending on the bank.
   - Exact excerpt: “Refunds are processed immediately ... usually within 7 days, depending on your bank.”
   - Judgment: supported and more precise than the official brief's existing “申请不批准则退款”; calendar days were not changed to business days and the bank dependency was retained.

All four stored excerpts pass normalized exact-containment validation against the stored Feed document. The final list stays at the four-item product limit and does not repeat the official brief's eligibility, mapping table, prices, target tiers, duration, or standard caveats.

### Rejected iterations and guards added during acceptance

- The first broad input produced a false `NO_NOVEL_HIGHLIGHTS`; the official context was compacted to remove repeated evidence while retaining fact values, routes and mapping claims.
- A later draft changed “7 days” into “7 business days”; it was rejected manually and led to deterministic qualifier/unit guards for `may`, `usually`, `most`, `depending on`, and days versus business days.
- Another draft added a physical-card conclusion to an excerpt that only supported immediate system verification; the prompt was narrowed to one-excerpt/one-claim and a scope guard rejects physical-card claims without matching excerpt evidence.
- Overlong copied FAQ/list excerpts were rejected by the strict 300-character evidence contract; the final contract allows at most four high-value points and forbids quota filling.
- Historical supplement attempts remain stored for audit, but the composed project brief selects only the latest successful supplement for the current official FactSet/Brief.

### Idempotency, graph isolation, and verdict

- Immediate rerun result: 0 routes created, 0 official projects processed, 0 articles selected, 0 model calls.
- Membership graph audit after the supplement: 1,176 expected claims, 1,176 represented claims, 0 missing, 0 invented, 0 material mismatches, and 0 direction mismatches. Third-party highlights did not enter the graph.
- Final human verdict: PASS. The route points to the correct official event; the composed brief is concise, source-separated, evidence-backed and materially additive; no generic event/relationship path or official-page refresh was triggered.
