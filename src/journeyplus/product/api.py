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
    agent_model=None,
    agent_network_enabled: bool = False,
    knowledge_user_writes_paused: bool = False,
) -> FastAPI:
    from journeyplus.agent.composition import compose_business
    from journeyplus.agent.adapters.unconfigured import UnconfiguredModel
    from journeyplus.product.agent_api import install_agent
    runtime,store=compose_business(session_factory,agent_model or UnconfiguredModel(),network_enabled=agent_network_enabled)
    app = FastAPI(title='JourneyPlus personalized status matches')
    install_agent(app, runtime, store, include_home=False)
    from journeyplus.product.rollout import install_rollout, configure_user_writes
    install_rollout(app,knowledge_user_writes_paused)
    configure_user_writes(session_factory,knowledge_user_writes_paused)
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

    @app.get('/v1/agent/state')
    def legacy_agent_state():
        from sqlalchemy import select
        from journeyplus.models import AgentInteraction
        with session_factory() as session:
            row=session.scalar(select(AgentInteraction).where(AgentInteraction.schema_version.not_in(['workspace-1','harness-2']))
                               .order_by(AgentInteraction.updated_at.desc()).limit(1))
            return {'available':False,'read_only':True,'interaction':row.last_response if row else None,
                    'wait_goal':None,'pending_result':None,'workspace_url':'/workspace'}

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
        include_archived: bool = False,
    ) -> BriefList:
        with session_factory.begin() as session:
            return ProductBriefService(session).list(
                query=q,
                reachable_only=reachable_only,
                include_archived=include_archived,
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
        return RedirectResponse("/workspace",status_code=307)

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
