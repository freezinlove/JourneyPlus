from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import ReviewAction
from journeyplus.review.service import ReviewService


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    target_event_id: UUID | None = None
    document_version_ids: list[UUID] = Field(default_factory=list)
    conflict_resolutions: dict[str, str] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=2000)
    actor: str = Field(default="operator", max_length=200)


def create_review_app(
    session_factory: sessionmaker[Session], *, ai_provider: AIProvider | None = None
) -> FastAPI:
    app = FastAPI(title="JourneyPlus internal review", docs_url="/internal/docs")

    @app.get("/internal/review/queue")
    def queue():
        with session_factory.begin() as session:
            return ReviewService(session).queue()

    @app.get("/internal/review/events/{event_id}")
    def full_chain(event_id: UUID):
        try:
            with session_factory.begin() as session:
                return ReviewService(session).full_chain(event_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/internal/review/events/{event_id}/actions")
    def act(event_id: UUID, request: ReviewRequest):
        try:
            with session_factory.begin() as session:
                service = ReviewService(session)
                if request.action == ReviewAction.CONFIRM:
                    result = service.confirm(
                        event_id,
                        conflict_resolutions=request.conflict_resolutions,
                        reason=request.reason,
                        actor=request.actor,
                    )
                elif request.action == ReviewAction.REJECT:
                    result = service.reject(
                        event_id, reason=request.reason, actor=request.actor
                    )
                elif request.action == ReviewAction.MERGE:
                    if request.target_event_id is None:
                        raise ValueError("MERGE requires target_event_id")
                    result = service.merge(
                        event_id,
                        request.target_event_id,
                        reason=request.reason,
                        actor=request.actor,
                    )
                elif request.action == ReviewAction.SPLIT:
                    result = service.split(
                        event_id,
                        request.document_version_ids,
                        reason=request.reason,
                        actor=request.actor,
                    )
                elif request.action == ReviewAction.REGENERATE:
                    if ai_provider is None:
                        raise RuntimeError("Review brief regeneration has no AI provider")
                    result, _generation = service.regenerate_brief(
                        event_id,
                        ai_provider,
                        reason=request.reason,
                        actor=request.actor,
                    )
                else:
                    raise ValueError(f"Unsupported review action: {request.action}")
                return {
                    "event_id": str(result.event.id),
                    "status": result.event.status,
                    "decision_id": str(result.decision.id),
                    "created_event_id": (
                        str(result.created_event.id) if result.created_event else None
                    ),
                }
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app

