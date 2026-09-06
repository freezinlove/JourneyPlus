from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from journeyplus.agent.contracts import (
    AgentStateResponse,
    AgentTurnRequest,
    AgentTurnResponse,
)
from journeyplus.agent.controller import (
    AgentController,
    AgentProviderError,
    AgentStateError,
    ExperienceResearcher,
    cleanup_expired_interactions,
)
from journeyplus.agent.waiting import WaitGoalError, WaitGoalService
from journeyplus.ai.provider import AIProvider
from journeyplus.membership.contracts import MembershipCatalog
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.product.briefs import ProductBriefService
from journeyplus.product.contracts import (
    BriefList,
    OpportunityDetail,
    PersonalizedMatches,
    StatusHoldingInput,
    StatusHoldingView,
)
from journeyplus.product.holdings import StatusHoldingService
from journeyplus.product.opportunities import PersonalizedMatchService


_STATIC_DIR = Path(__file__).with_name("static")


def create_product_app(
    session_factory: sessionmaker[Session],
    *,
    ai_provider: AIProvider | None = None,
    experience_researcher: ExperienceResearcher | None = None,
    agent_interaction_ttl_hours: int = 24,
    agent_max_model_calls: int = 3,
    knowledge_read_mode: str = 'legacy',
    knowledge_user_writes_paused: bool = False,
) -> FastAPI:
    app = FastAPI(
        title="JourneyPlus personalized status matches",
        docs_url="/docs",
        redoc_url=None,
    )
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR), name="assets")
    from journeyplus.product.rollout import install_rollout
    install_rollout(app,knowledge_read_mode,knowledge_user_writes_paused)
    from journeyplus.knowledge.user_journal import configure_user_data
    configure_user_data(session_factory,knowledge_read_mode.casefold(),knowledge_user_writes_paused)
    from journeyplus.product.knowledge_api import knowledge_router
    app.include_router(knowledge_router(session_factory,ai_provider,
        ttl_hours=agent_interaction_ttl_hours,max_calls=agent_max_model_calls,researcher=experience_researcher))

    @app.get("/workspace", response_class=HTMLResponse, include_in_schema=False)
    def workspace_page() -> str:
        return (_STATIC_DIR / "workspace.html").read_text(encoding="utf-8")

    @app.get('/knowledge',response_class=HTMLResponse,include_in_schema=False)
    def knowledge_page() -> str:
        return (_STATIC_DIR / 'knowledge.html').read_text(encoding='utf-8')

    @app.get('/explore',response_class=HTMLResponse,include_in_schema=False)
    def explore_page() -> str:
        return (_STATIC_DIR / 'explore.html').read_text(encoding='utf-8')

    def agent_controller(session: Session) -> AgentController:
        if ai_provider is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="会籍策略 Agent 暂不可用：服务端尚未配置模型。",
            )
        return AgentController(
            session,
            ai_provider,
            interaction_ttl=timedelta(hours=agent_interaction_ttl_hours),
            max_model_calls=agent_max_model_calls,
            experience_researcher=experience_researcher,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(_request, _exc) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": (
                    "产品数据库暂不可用。请关闭服务后重新运行 "
                    "`uv run journeyplus product-api`；本地 PostgreSQL 会自动检查并启动。"
                )
            },
        )

    @app.get("/v1/membership-catalog", response_model=MembershipCatalog)
    def membership_catalog(
        q: str | None = Query(default=None, max_length=300),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> MembershipCatalog:
        with session_factory.begin() as session:
            catalog = UnifiedMembershipTreeService(session).catalog(query=q)
            return catalog.model_copy(update={"nodes": catalog.nodes[:limit]})

    @app.post("/v1/agent/turn", response_model=AgentTurnResponse)
    def agent_turn(request: AgentTurnRequest) -> AgentTurnResponse:
        try:
            with session_factory.begin() as session:
                return agent_controller(session).turn(request)
        except HTTPException:
            raise
        except (AgentStateError, WaitGoalError, LookupError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AgentProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/agent/state", response_model=AgentStateResponse)
    def agent_state() -> AgentStateResponse:
        with session_factory.begin() as session:
            cleanup_expired_interactions(session)
            wait_service = WaitGoalService(session)
            pending = wait_service.consume_pending()
            latest = (
                agent_controller(session).latest_response()
                if ai_provider is not None
                else None
            )
            if (
                pending is not None
                and latest is not None
                and pending.interaction_id == latest.interaction_id
            ):
                latest = None
            return AgentStateResponse(
                available=ai_provider is not None,
                interaction=latest,
                wait_goal=wait_service.current(),
                pending_result=pending,
            )

    @app.get("/v1/status-holdings", response_model=list[StatusHoldingView])
    def list_status_holdings() -> list[StatusHoldingView]:
        with session_factory.begin() as session:
            return StatusHoldingService(session).list()

    @app.post(
        "/v1/status-holdings",
        response_model=StatusHoldingView,
        status_code=status.HTTP_201_CREATED,
    )
    def upsert_status_holding(request: StatusHoldingInput) -> StatusHoldingView:
        try:
            with session_factory.begin() as session:
                return StatusHoldingService(session).upsert(request)
        except LookupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/v1/status-holdings/{holding_id}", response_model=StatusHoldingView)
    def update_status_holding(
        holding_id: UUID, request: StatusHoldingInput
    ) -> StatusHoldingView:
        try:
            with session_factory.begin() as session:
                return StatusHoldingService(session).update(holding_id, request)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete(
        "/v1/status-holdings/{holding_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_status_holding(holding_id: UUID) -> Response:
        try:
            with session_factory.begin() as session:
                StatusHoldingService(session).delete(holding_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/personalized-matches", response_model=PersonalizedMatches)
    def personalized_matches(
        technical_node_limit: int = Query(default=5000, ge=1, le=20000),
    ) -> PersonalizedMatches:
        try:
            with session_factory.begin() as session:
                return PersonalizedMatchService(session).read(
                    technical_node_limit=technical_node_limit
                )
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/briefs", response_model=BriefList)
    def briefs(
        q: str | None = Query(default=None, max_length=300),
        reachable_only: bool = False,
    ) -> BriefList:
        with session_factory.begin() as session:
            return ProductBriefService(session).list(
                query=q,
                reachable_only=reachable_only,
            )

    @app.get(
        "/v1/match-opportunities/{opportunity_id}",
        response_model=OpportunityDetail,
    )
    def match_opportunity(opportunity_id: UUID) -> OpportunityDetail:
        try:
            with session_factory.begin() as session:
                return PersonalizedMatchService(session).detail(opportunity_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/holdings", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get("/holdings", response_class=HTMLResponse, include_in_schema=False)
    def holdings_page() -> str:
        return _page("holdings", "我的会籍")

    @app.get("/agent", response_class=HTMLResponse, include_in_schema=False)
    def agent_page() -> str:
        return _page("agent", "会籍策略 Agent")

    @app.get("/matches", response_class=HTMLResponse, include_in_schema=False)
    def matches_page() -> str:
        return _page("matches", "个性化匹配图")

    @app.get("/briefs", response_class=HTMLResponse, include_in_schema=False)
    def briefs_page() -> str:
        return _page("briefs", "机会简报")

    @app.get(
        "/opportunities/{opportunity_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def opportunity_page(opportunity_id: UUID) -> str:
        return _page(
            "opportunity",
            "机会详情",
            page_data=f'data-opportunity-id="{opportunity_id}"',
        )

    return app


def _page(page: str, title: str, *, page_data: str = "") -> str:
    navigation = (
        ("agent", "/agent", "策略 Agent"),
        ("holdings", "/holdings", "我的会籍"),
        ("matches", "/matches", "匹配图"),
        ("briefs", "/briefs", "机会简报"),
    )
    links = "".join(
        f'<a href="{href}"{(" aria-current=\"page\"" if key == page else "")}>{label}</a>'
        for key, href, label in navigation
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="个性化常旅客会籍匹配与挑战机会">
  <title>{title} · JourneyPlus</title>
  <link rel="stylesheet" href="/assets/app.css?v=20260904-agent-v1">
</head>
<body data-page="{page}" {page_data}>
  <header class="topbar">
    <a class="brand" href="/holdings"><span>J+</span> JourneyPlus</a>
    <nav aria-label="主导航">{links}</nav>
  </header>
  <main id="app" class="page" aria-live="polite">
    <div class="loading-card"><span class="spinner"></span>正在读取当前数据…</div>
  </main>
  <footer>默认地区：中国 · 地区仅作提醒，不限制机会</footer>
  <script src="/assets/app.js?v=20260904-agent-v1" defer></script>
</body>
</html>"""
