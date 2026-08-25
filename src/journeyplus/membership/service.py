from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from journeyplus.membership.contracts import (
    MappingClaimStatus,
    MembershipMappingClaim,
)
from journeyplus.models import ReviewDecision, StatusMatchArticleSupplement


def approve_third_party_mapping_claim(
    session: Session,
    *,
    supplement_id: UUID | str,
    claim_id: str,
    actor: str = "operator",
    reason: str | None = None,
) -> MembershipMappingClaim:
    supplement = session.get(
        StatusMatchArticleSupplement, UUID(str(supplement_id))
    )
    if supplement is None:
        raise LookupError("StatusMatch article supplement was not found")
    claims = [
        MembershipMappingClaim.model_validate(item)
        for item in supplement.mapping_claims
    ]
    selected: MembershipMappingClaim | None = None
    updated: list[dict] = []
    for claim in claims:
        if claim.claim_id == claim_id:
            if claim.status == MappingClaimStatus.CORROBORATED:
                raise ValueError("Corroborated official-equivalent claims need no approval")
            if claim.status == MappingClaimStatus.REJECTED:
                raise ValueError("Rejected claims cannot be approved")
            claim = claim.model_copy(update={"status": MappingClaimStatus.APPROVED})
            selected = claim
        updated.append(claim.model_dump(mode="json"))
    if selected is None:
        raise LookupError("Membership mapping claim was not found")
    supplement.mapping_claims = updated
    session.add(
        ReviewDecision(
            action="APPROVE_THIRD_PARTY_MAPPING",
            entity_type="membership_mapping_claim",
            entity_id=supplement.id,
            reason=reason,
            actor=actor,
            payload={"claim_id": claim_id},
        )
    )
    session.flush()
    return selected


def reject_third_party_mapping_claim(
    session: Session,
    *,
    supplement_id: UUID | str,
    claim_id: str,
    actor: str = "operator",
    reason: str | None = None,
) -> MembershipMappingClaim:
    supplement = session.get(
        StatusMatchArticleSupplement, UUID(str(supplement_id))
    )
    if supplement is None:
        raise LookupError("StatusMatch article supplement was not found")
    selected: MembershipMappingClaim | None = None
    updated: list[dict] = []
    for raw in supplement.mapping_claims:
        claim = MembershipMappingClaim.model_validate(raw)
        if claim.claim_id == claim_id:
            claim = claim.model_copy(update={"status": MappingClaimStatus.REJECTED})
            selected = claim
        updated.append(claim.model_dump(mode="json"))
    if selected is None:
        raise LookupError("Membership mapping claim was not found")
    supplement.mapping_claims = updated
    session.add(
        ReviewDecision(
            action="REJECT_THIRD_PARTY_MAPPING",
            entity_type="membership_mapping_claim",
            entity_id=supplement.id,
            reason=reason,
            actor=actor,
            payload={"claim_id": claim_id},
        )
    )
    session.flush()
    return selected
