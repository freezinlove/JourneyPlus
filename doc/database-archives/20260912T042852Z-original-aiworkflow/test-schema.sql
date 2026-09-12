--
-- PostgreSQL database dump
--

\restrict xdaofwk0rhf8PgaiY7jlqeTVUa6vhP6kLTaCmBcMVUseElb4rg0QGOz9Y7gFjIW

-- Dumped from database version 17.11
-- Dumped by pg_dump version 17.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_interactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_interactions (
    id uuid NOT NULL,
    status character varying(60) NOT NULL,
    state json NOT NULL,
    last_response json,
    provider character varying(100) NOT NULL,
    model character varying(200) NOT NULL,
    prompt_version character varying(100) NOT NULL,
    schema_version character varying(100) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: agent_wait_goals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_wait_goals (
    id uuid NOT NULL,
    source_interaction_id uuid,
    status character varying(30) NOT NULL,
    query json NOT NULL,
    preferences json NOT NULL,
    research_statusmatcher boolean NOT NULL,
    holding_node_ids json NOT NULL,
    last_candidate_signature character varying(64),
    pending_result json,
    pending_seen_at timestamp with time zone,
    notified_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: analysis_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analysis_runs (
    id uuid NOT NULL,
    idempotency_key character varying(255) NOT NULL,
    document_version_id uuid,
    event_id uuid,
    stage character varying(100) NOT NULL,
    status character varying(30) NOT NULL,
    input_version character varying(255) NOT NULL,
    provider character varying(100) NOT NULL,
    model character varying(200) NOT NULL,
    model_config_version character varying(100) NOT NULL,
    prompt_version character varying(100) NOT NULL,
    schema_version character varying(100) NOT NULL,
    result json,
    error text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: article_analyses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.article_analyses (
    id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    source_item_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL,
    input_version character varying(255) NOT NULL,
    label character varying(40) NOT NULL,
    confidence double precision NOT NULL,
    reason text NOT NULL,
    status character varying(40) NOT NULL,
    content_signature character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: article_briefs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.article_briefs (
    id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL,
    input_version character varying(255) NOT NULL,
    version integer NOT NULL,
    schema_version character varying(100) NOT NULL,
    content json NOT NULL,
    status character varying(50) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: article_opportunities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.article_opportunities (
    id uuid NOT NULL,
    analysis_id uuid NOT NULL,
    opportunity_index integer NOT NULL,
    program character varying(300) NOT NULL,
    target_status character varying(300),
    summary text NOT NULL,
    application_start_raw text,
    application_deadline_raw text,
    application_start_at timestamp with time zone,
    application_deadline_at timestamp with time zone,
    lifecycle_status character varying(30) NOT NULL,
    action_links json NOT NULL,
    facts json NOT NULL,
    fact_signature character varying(64) NOT NULL,
    status character varying(40) NOT NULL,
    current_brief_id uuid,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    visibility_until_at timestamp with time zone NOT NULL,
    visibility_policy character varying(40) NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(40)
);


--
-- Name: automation_leases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_leases (
    name character varying(100) NOT NULL,
    owner_id character varying(100),
    acquired_at timestamp with time zone,
    expires_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: automation_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_runs (
    id uuid NOT NULL,
    idempotency_key character varying(255) NOT NULL,
    day_bucket date NOT NULL,
    status character varying(30) NOT NULL,
    attempts integer NOT NULL,
    owner_id character varying(100) NOT NULL,
    limits json NOT NULL,
    source_results json NOT NULL,
    processing_result json NOT NULL,
    lifecycle_result json NOT NULL,
    model_calls integer NOT NULL,
    backlog_count integer NOT NULL,
    needs_review_count integer NOT NULL,
    error text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: briefs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.briefs (
    id uuid NOT NULL,
    fact_set_id uuid NOT NULL,
    version integer NOT NULL,
    schema_version character varying(100) NOT NULL,
    content json NOT NULL,
    status character varying(50) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: buy_points_offers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.buy_points_offers (
    id uuid NOT NULL,
    snapshot_id uuid NOT NULL,
    offer_key character varying(500) NOT NULL,
    category character varying(30) NOT NULL,
    program_name character varying(500) NOT NULL,
    offer_text text NOT NULL,
    offer_kind character varying(30) NOT NULL,
    max_percent numeric(8,3) NOT NULL,
    deadline_raw character varying(200),
    deadline_date date,
    posting_time_raw character varying(200),
    detail_url text,
    action_url text,
    material_signature character varying(64) NOT NULL,
    evidence json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: buy_points_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.buy_points_snapshots (
    id uuid NOT NULL,
    source_item_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    parser_version character varying(100) NOT NULL,
    page_title text NOT NULL,
    page_modified_at timestamp with time zone,
    parsed_offer_count integer NOT NULL,
    offers_signature character varying(64) NOT NULL,
    diagnostics json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: collection_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.collection_runs (
    id uuid NOT NULL,
    source_id character varying(100) NOT NULL,
    idempotency_key character varying(255) NOT NULL,
    status character varying(30) NOT NULL,
    discovered_count integer NOT NULL,
    document_count integer NOT NULL,
    error text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: document_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_versions (
    id uuid NOT NULL,
    source_item_id uuid NOT NULL,
    canonical_url text NOT NULL,
    raw_body text,
    normalized_body text NOT NULL,
    content_type character varying(200) NOT NULL,
    storage_mode character varying(100) NOT NULL,
    raw_hash character varying(64) NOT NULL,
    normalized_hash character varying(64) NOT NULL,
    parser_version character varying(100) NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    duplicate_of_id uuid,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    section_parser_version character varying(100)
);


--
-- Name: event_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_evidence (
    id uuid NOT NULL,
    event_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    hint_index integer NOT NULL,
    source_url text NOT NULL,
    locator text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: event_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_revisions (
    id uuid NOT NULL,
    event_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    relationship character varying(50) NOT NULL,
    snapshot json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: fact_sets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fact_sets (
    id uuid NOT NULL,
    event_id uuid NOT NULL,
    version integer NOT NULL,
    schema_version character varying(100) NOT NULL,
    facts json NOT NULL,
    has_conflicts boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: gold_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gold_cases (
    id uuid NOT NULL,
    case_id character varying(200) NOT NULL,
    version integer NOT NULL,
    document_text text NOT NULL,
    labels json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: initialization_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.initialization_runs (
    id uuid NOT NULL,
    batch_key character varying(255) NOT NULL,
    batch_type character varying(50) NOT NULL,
    window_start date,
    window_end date,
    status character varying(30) NOT NULL,
    audit_status character varying(30) NOT NULL,
    attempts integer NOT NULL,
    limits json NOT NULL,
    source_results json NOT NULL,
    processing_result json NOT NULL,
    audit_notes text,
    error text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: job_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_runs (
    id uuid NOT NULL,
    idempotency_key character varying(255) NOT NULL,
    job_type character varying(100) NOT NULL,
    status character varying(30) NOT NULL,
    attempts integer NOT NULL,
    result json,
    error text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: review_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_decisions (
    id uuid NOT NULL,
    action character varying(50) NOT NULL,
    entity_type character varying(100) NOT NULL,
    entity_id uuid NOT NULL,
    target_entity_id uuid,
    reason text,
    actor character varying(200) NOT NULL,
    payload json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: source_automation_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_automation_states (
    source_id character varying(100) NOT NULL,
    last_day_bucket date,
    last_attempt_at timestamp with time zone,
    last_success_at timestamp with time zone,
    last_failure_at timestamp with time zone,
    last_error text,
    consecutive_failures integer NOT NULL,
    last_new_document_count integer NOT NULL,
    pending_document_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    discovery_cursor character varying(500)
);


--
-- Name: source_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_items (
    id uuid NOT NULL,
    source_id character varying(100) NOT NULL,
    external_id character varying(500) NOT NULL,
    discovered_url text NOT NULL,
    canonical_url text NOT NULL,
    title text NOT NULL,
    published_at timestamp with time zone,
    observed_at timestamp with time zone NOT NULL,
    discovery_fingerprint character varying(128),
    raw_metadata json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    document_role character varying(30) DEFAULT 'OTHER'::character varying
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    id character varying(100) NOT NULL,
    name character varying(300) NOT NULL,
    adapter_type character varying(100) NOT NULL,
    discovery_config json NOT NULL,
    access_policy json NOT NULL,
    collection_cadence character varying(100),
    automatic_scheduling boolean NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: status_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.status_events (
    id uuid NOT NULL,
    created_from_key character varying(255) NOT NULL,
    program character varying(300) NOT NULL,
    target_status character varying(300),
    summary text NOT NULL,
    search_text text NOT NULL,
    status character varying(50) NOT NULL,
    merged_into_id uuid,
    current_fact_set_id uuid,
    current_brief_id uuid,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    application_start_at timestamp with time zone,
    application_deadline_at timestamp with time zone,
    lifecycle_status character varying(30) DEFAULT 'UNKNOWN'::character varying NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(100),
    closure_document_version_id uuid
);


--
-- Name: status_holdings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.status_holdings (
    id uuid NOT NULL,
    program_key character varying(300) NOT NULL,
    tier_key character varying(300) NOT NULL,
    program_display_name character varying(300) NOT NULL,
    tier_display_name character varying(300) NOT NULL,
    valid_until date,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: statusmatch_article_routes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statusmatch_article_routes (
    id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    project_host character varying(255) NOT NULL,
    project_url text NOT NULL,
    event_id uuid,
    status character varying(40) NOT NULL,
    last_error text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: statusmatch_article_supplements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statusmatch_article_supplements (
    id uuid NOT NULL,
    route_id uuid NOT NULL,
    event_id uuid NOT NULL,
    article_document_version_id uuid NOT NULL,
    fact_set_id uuid NOT NULL,
    brief_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL,
    input_version character varying(255) NOT NULL,
    status character varying(40) NOT NULL,
    highlights json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    mapping_claims json DEFAULT '[]'::json NOT NULL
);


--
-- Name: statusmatch_change_sets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statusmatch_change_sets (
    id uuid NOT NULL,
    event_id uuid NOT NULL,
    from_fact_set_id uuid,
    to_fact_set_id uuid NOT NULL,
    activity_document_version_id uuid NOT NULL,
    faq_document_version_id uuid NOT NULL,
    kind character varying(50) NOT NULL,
    changes json NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    terms_document_version_id uuid
);


--
-- Name: statusmatch_watch_pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statusmatch_watch_pages (
    id uuid NOT NULL,
    watch_id uuid NOT NULL,
    page_kind character varying(20) NOT NULL,
    canonical_url text NOT NULL,
    current_document_version_id uuid,
    last_checked_at timestamp with time zone,
    last_changed_at timestamp with time zone,
    last_error text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: statusmatch_watches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statusmatch_watches (
    id uuid NOT NULL,
    host character varying(255) NOT NULL,
    status character varying(30) NOT NULL,
    current_event_id uuid,
    last_checked_at timestamp with time zone,
    last_changed_at timestamp with time zone,
    last_error text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: agent_interactions agent_interactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_interactions
    ADD CONSTRAINT agent_interactions_pkey PRIMARY KEY (id);


--
-- Name: agent_wait_goals agent_wait_goals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_wait_goals
    ADD CONSTRAINT agent_wait_goals_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: analysis_runs analysis_runs_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT analysis_runs_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: analysis_runs analysis_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT analysis_runs_pkey PRIMARY KEY (id);


--
-- Name: article_analyses article_analyses_analysis_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_analyses
    ADD CONSTRAINT article_analyses_analysis_run_id_key UNIQUE (analysis_run_id);


--
-- Name: article_analyses article_analyses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_analyses
    ADD CONSTRAINT article_analyses_pkey PRIMARY KEY (id);


--
-- Name: article_briefs article_briefs_opportunity_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_briefs
    ADD CONSTRAINT article_briefs_opportunity_id_version_key UNIQUE (opportunity_id, version);


--
-- Name: article_briefs article_briefs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_briefs
    ADD CONSTRAINT article_briefs_pkey PRIMARY KEY (id);


--
-- Name: article_opportunities article_opportunities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_opportunities
    ADD CONSTRAINT article_opportunities_pkey PRIMARY KEY (id);


--
-- Name: automation_leases automation_leases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_leases
    ADD CONSTRAINT automation_leases_pkey PRIMARY KEY (name);


--
-- Name: automation_runs automation_runs_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT automation_runs_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: automation_runs automation_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT automation_runs_pkey PRIMARY KEY (id);


--
-- Name: briefs briefs_fact_set_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.briefs
    ADD CONSTRAINT briefs_fact_set_id_version_key UNIQUE (fact_set_id, version);


--
-- Name: briefs briefs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.briefs
    ADD CONSTRAINT briefs_pkey PRIMARY KEY (id);


--
-- Name: buy_points_offers buy_points_offers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.buy_points_offers
    ADD CONSTRAINT buy_points_offers_pkey PRIMARY KEY (id);


--
-- Name: buy_points_snapshots buy_points_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.buy_points_snapshots
    ADD CONSTRAINT buy_points_snapshots_pkey PRIMARY KEY (id);


--
-- Name: collection_runs collection_runs_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_runs
    ADD CONSTRAINT collection_runs_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: collection_runs collection_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_runs
    ADD CONSTRAINT collection_runs_pkey PRIMARY KEY (id);


--
-- Name: document_versions document_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_pkey PRIMARY KEY (id);


--
-- Name: event_evidence event_evidence_event_id_document_version_id_hint_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_evidence
    ADD CONSTRAINT event_evidence_event_id_document_version_id_hint_index_key UNIQUE (event_id, document_version_id, hint_index);


--
-- Name: event_evidence event_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_evidence
    ADD CONSTRAINT event_evidence_pkey PRIMARY KEY (id);


--
-- Name: event_revisions event_revisions_event_id_document_version_id_relationship_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_revisions
    ADD CONSTRAINT event_revisions_event_id_document_version_id_relationship_key UNIQUE (event_id, document_version_id, relationship);


--
-- Name: event_revisions event_revisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_revisions
    ADD CONSTRAINT event_revisions_pkey PRIMARY KEY (id);


--
-- Name: fact_sets fact_sets_event_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sets
    ADD CONSTRAINT fact_sets_event_id_version_key UNIQUE (event_id, version);


--
-- Name: fact_sets fact_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sets
    ADD CONSTRAINT fact_sets_pkey PRIMARY KEY (id);


--
-- Name: gold_cases gold_cases_case_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gold_cases
    ADD CONSTRAINT gold_cases_case_id_version_key UNIQUE (case_id, version);


--
-- Name: gold_cases gold_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gold_cases
    ADD CONSTRAINT gold_cases_pkey PRIMARY KEY (id);


--
-- Name: initialization_runs initialization_runs_batch_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.initialization_runs
    ADD CONSTRAINT initialization_runs_batch_key_key UNIQUE (batch_key);


--
-- Name: initialization_runs initialization_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.initialization_runs
    ADD CONSTRAINT initialization_runs_pkey PRIMARY KEY (id);


--
-- Name: job_runs job_runs_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: job_runs job_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_pkey PRIMARY KEY (id);


--
-- Name: review_decisions review_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_decisions
    ADD CONSTRAINT review_decisions_pkey PRIMARY KEY (id);


--
-- Name: source_automation_states source_automation_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_automation_states
    ADD CONSTRAINT source_automation_states_pkey PRIMARY KEY (source_id);


--
-- Name: source_items source_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_items
    ADD CONSTRAINT source_items_pkey PRIMARY KEY (id);


--
-- Name: source_items source_items_source_id_external_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_items
    ADD CONSTRAINT source_items_source_id_external_id_key UNIQUE (source_id, external_id);


--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);


--
-- Name: status_events status_events_created_from_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_events
    ADD CONSTRAINT status_events_created_from_key_key UNIQUE (created_from_key);


--
-- Name: status_events status_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_events
    ADD CONSTRAINT status_events_pkey PRIMARY KEY (id);


--
-- Name: status_holdings status_holdings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_holdings
    ADD CONSTRAINT status_holdings_pkey PRIMARY KEY (id);


--
-- Name: status_holdings status_holdings_program_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_holdings
    ADD CONSTRAINT status_holdings_program_key_key UNIQUE (program_key);


--
-- Name: statusmatch_article_routes statusmatch_article_routes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_routes
    ADD CONSTRAINT statusmatch_article_routes_pkey PRIMARY KEY (id);


--
-- Name: statusmatch_article_supplements statusmatch_article_supplements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT statusmatch_article_supplements_pkey PRIMARY KEY (id);


--
-- Name: statusmatch_change_sets statusmatch_change_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT statusmatch_change_sets_pkey PRIMARY KEY (id);


--
-- Name: statusmatch_watch_pages statusmatch_watch_pages_canonical_url_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watch_pages
    ADD CONSTRAINT statusmatch_watch_pages_canonical_url_key UNIQUE (canonical_url);


--
-- Name: statusmatch_watch_pages statusmatch_watch_pages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watch_pages
    ADD CONSTRAINT statusmatch_watch_pages_pkey PRIMARY KEY (id);


--
-- Name: statusmatch_watch_pages statusmatch_watch_pages_watch_id_page_kind_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watch_pages
    ADD CONSTRAINT statusmatch_watch_pages_watch_id_page_kind_key UNIQUE (watch_id, page_kind);


--
-- Name: statusmatch_watches statusmatch_watches_host_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watches
    ADD CONSTRAINT statusmatch_watches_host_key UNIQUE (host);


--
-- Name: statusmatch_watches statusmatch_watches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watches
    ADD CONSTRAINT statusmatch_watches_pkey PRIMARY KEY (id);


--
-- Name: article_briefs uq_article_brief_input; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_briefs
    ADD CONSTRAINT uq_article_brief_input UNIQUE (opportunity_id, input_version);


--
-- Name: article_opportunities uq_article_opportunity_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_opportunities
    ADD CONSTRAINT uq_article_opportunity_index UNIQUE (analysis_id, opportunity_index);


--
-- Name: buy_points_offers uq_buy_points_offer_snapshot_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.buy_points_offers
    ADD CONSTRAINT uq_buy_points_offer_snapshot_key UNIQUE (snapshot_id, offer_key);


--
-- Name: buy_points_snapshots uq_buy_points_snapshot_document_parser; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.buy_points_snapshots
    ADD CONSTRAINT uq_buy_points_snapshot_document_parser UNIQUE (document_version_id, parser_version);


--
-- Name: document_versions uq_document_versions_source_item_raw_parser; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT uq_document_versions_source_item_raw_parser UNIQUE (source_item_id, raw_hash, parser_version);


--
-- Name: statusmatch_article_routes uq_statusmatch_article_route_document_host; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_routes
    ADD CONSTRAINT uq_statusmatch_article_route_document_host UNIQUE (document_version_id, project_host);


--
-- Name: statusmatch_article_supplements uq_statusmatch_article_supplement_input; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT uq_statusmatch_article_supplement_input UNIQUE (route_id, fact_set_id, brief_id, input_version);


--
-- Name: statusmatch_change_sets uq_statusmatch_change_sets_event_snapshot_fact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT uq_statusmatch_change_sets_event_snapshot_fact UNIQUE (event_id, activity_document_version_id, faq_document_version_id, terms_document_version_id, to_fact_set_id);


--
-- Name: ix_agent_interactions_status_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_interactions_status_expires ON public.agent_interactions USING btree (status, expires_at);


--
-- Name: ix_article_analyses_source_item_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_article_analyses_source_item_created ON public.article_analyses USING btree (source_item_id, created_at);


--
-- Name: ix_article_opportunities_analysis_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_article_opportunities_analysis_status ON public.article_opportunities USING btree (analysis_id, status);


--
-- Name: ix_article_opportunities_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_article_opportunities_visibility ON public.article_opportunities USING btree (visibility_until_at, archived_at);


--
-- Name: ix_buy_points_offers_offer_key_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_buy_points_offers_offer_key_snapshot ON public.buy_points_offers USING btree (offer_key, snapshot_id);


--
-- Name: ix_buy_points_offers_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_buy_points_offers_snapshot ON public.buy_points_offers USING btree (snapshot_id);


--
-- Name: ix_buy_points_snapshots_source_parser_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_buy_points_snapshots_source_parser_created ON public.buy_points_snapshots USING btree (source_item_id, parser_version, created_at);


--
-- Name: ix_document_versions_normalized_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_document_versions_normalized_hash ON public.document_versions USING btree (normalized_hash);


--
-- Name: ix_source_items_canonical_url; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_items_canonical_url ON public.source_items USING btree (canonical_url);


--
-- Name: ix_status_events_lifecycle_archived; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_status_events_lifecycle_archived ON public.status_events USING btree (lifecycle_status, archived_at);


--
-- Name: ix_statusmatch_article_routes_event_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_statusmatch_article_routes_event_status ON public.statusmatch_article_routes USING btree (event_id, status);


--
-- Name: ix_statusmatch_article_supplements_event_fact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_statusmatch_article_supplements_event_fact ON public.statusmatch_article_supplements USING btree (event_id, fact_set_id);


--
-- Name: ix_statusmatch_change_sets_event_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_statusmatch_change_sets_event_created ON public.statusmatch_change_sets USING btree (event_id, created_at);


--
-- Name: uq_agent_wait_goals_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_wait_goals_single_active ON public.agent_wait_goals USING btree (status) WHERE ((status)::text = 'ACTIVE'::text);


--
-- Name: agent_wait_goals agent_wait_goals_source_interaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_wait_goals
    ADD CONSTRAINT agent_wait_goals_source_interaction_id_fkey FOREIGN KEY (source_interaction_id) REFERENCES public.agent_interactions(id) ON DELETE SET NULL;


--
-- Name: analysis_runs analysis_runs_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT analysis_runs_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: analysis_runs analysis_runs_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT analysis_runs_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.status_events(id);


--
-- Name: article_analyses article_analyses_analysis_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_analyses
    ADD CONSTRAINT article_analyses_analysis_run_id_fkey FOREIGN KEY (analysis_run_id) REFERENCES public.analysis_runs(id);


--
-- Name: article_analyses article_analyses_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_analyses
    ADD CONSTRAINT article_analyses_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: article_analyses article_analyses_source_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_analyses
    ADD CONSTRAINT article_analyses_source_item_id_fkey FOREIGN KEY (source_item_id) REFERENCES public.source_items(id);


--
-- Name: article_briefs article_briefs_analysis_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_briefs
    ADD CONSTRAINT article_briefs_analysis_run_id_fkey FOREIGN KEY (analysis_run_id) REFERENCES public.analysis_runs(id);


--
-- Name: article_briefs article_briefs_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_briefs
    ADD CONSTRAINT article_briefs_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES public.article_opportunities(id) ON DELETE CASCADE;


--
-- Name: article_opportunities article_opportunities_analysis_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_opportunities
    ADD CONSTRAINT article_opportunities_analysis_id_fkey FOREIGN KEY (analysis_id) REFERENCES public.article_analyses(id) ON DELETE CASCADE;


--
-- Name: briefs briefs_fact_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.briefs
    ADD CONSTRAINT briefs_fact_set_id_fkey FOREIGN KEY (fact_set_id) REFERENCES public.fact_sets(id);


--
-- Name: buy_points_offers buy_points_offers_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.buy_points_offers
    ADD CONSTRAINT buy_points_offers_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.buy_points_snapshots(id) ON DELETE CASCADE;


--
-- Name: buy_points_snapshots buy_points_snapshots_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.buy_points_snapshots
    ADD CONSTRAINT buy_points_snapshots_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: buy_points_snapshots buy_points_snapshots_source_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.buy_points_snapshots
    ADD CONSTRAINT buy_points_snapshots_source_item_id_fkey FOREIGN KEY (source_item_id) REFERENCES public.source_items(id);


--
-- Name: collection_runs collection_runs_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_runs
    ADD CONSTRAINT collection_runs_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


--
-- Name: document_versions document_versions_duplicate_of_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_duplicate_of_id_fkey FOREIGN KEY (duplicate_of_id) REFERENCES public.document_versions(id);


--
-- Name: document_versions document_versions_source_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_source_item_id_fkey FOREIGN KEY (source_item_id) REFERENCES public.source_items(id);


--
-- Name: event_evidence event_evidence_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_evidence
    ADD CONSTRAINT event_evidence_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: event_evidence event_evidence_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_evidence
    ADD CONSTRAINT event_evidence_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.status_events(id);


--
-- Name: event_revisions event_revisions_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_revisions
    ADD CONSTRAINT event_revisions_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: event_revisions event_revisions_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_revisions
    ADD CONSTRAINT event_revisions_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.status_events(id);


--
-- Name: fact_sets fact_sets_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sets
    ADD CONSTRAINT fact_sets_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.status_events(id);


--
-- Name: status_events fk_status_events_closure_document_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_events
    ADD CONSTRAINT fk_status_events_closure_document_version_id FOREIGN KEY (closure_document_version_id) REFERENCES public.document_versions(id);


--
-- Name: statusmatch_change_sets fk_statusmatch_change_sets_terms_document_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT fk_statusmatch_change_sets_terms_document_version_id FOREIGN KEY (terms_document_version_id) REFERENCES public.document_versions(id);


--
-- Name: source_automation_states source_automation_states_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_automation_states
    ADD CONSTRAINT source_automation_states_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


--
-- Name: source_items source_items_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_items
    ADD CONSTRAINT source_items_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


--
-- Name: status_events status_events_merged_into_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_events
    ADD CONSTRAINT status_events_merged_into_id_fkey FOREIGN KEY (merged_into_id) REFERENCES public.status_events(id);


--
-- Name: statusmatch_article_routes statusmatch_article_routes_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_routes
    ADD CONSTRAINT statusmatch_article_routes_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: statusmatch_article_routes statusmatch_article_routes_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_routes
    ADD CONSTRAINT statusmatch_article_routes_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.status_events(id);


--
-- Name: statusmatch_article_supplements statusmatch_article_supplement_article_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT statusmatch_article_supplement_article_document_version_id_fkey FOREIGN KEY (article_document_version_id) REFERENCES public.document_versions(id);


--
-- Name: statusmatch_article_supplements statusmatch_article_supplements_analysis_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT statusmatch_article_supplements_analysis_run_id_fkey FOREIGN KEY (analysis_run_id) REFERENCES public.analysis_runs(id);


--
-- Name: statusmatch_article_supplements statusmatch_article_supplements_brief_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT statusmatch_article_supplements_brief_id_fkey FOREIGN KEY (brief_id) REFERENCES public.briefs(id);


--
-- Name: statusmatch_article_supplements statusmatch_article_supplements_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT statusmatch_article_supplements_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.status_events(id);


--
-- Name: statusmatch_article_supplements statusmatch_article_supplements_fact_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT statusmatch_article_supplements_fact_set_id_fkey FOREIGN KEY (fact_set_id) REFERENCES public.fact_sets(id);


--
-- Name: statusmatch_article_supplements statusmatch_article_supplements_route_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_article_supplements
    ADD CONSTRAINT statusmatch_article_supplements_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.statusmatch_article_routes(id) ON DELETE CASCADE;


--
-- Name: statusmatch_change_sets statusmatch_change_sets_activity_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT statusmatch_change_sets_activity_document_version_id_fkey FOREIGN KEY (activity_document_version_id) REFERENCES public.document_versions(id);


--
-- Name: statusmatch_change_sets statusmatch_change_sets_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT statusmatch_change_sets_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.status_events(id);


--
-- Name: statusmatch_change_sets statusmatch_change_sets_faq_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT statusmatch_change_sets_faq_document_version_id_fkey FOREIGN KEY (faq_document_version_id) REFERENCES public.document_versions(id);


--
-- Name: statusmatch_change_sets statusmatch_change_sets_from_fact_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT statusmatch_change_sets_from_fact_set_id_fkey FOREIGN KEY (from_fact_set_id) REFERENCES public.fact_sets(id);


--
-- Name: statusmatch_change_sets statusmatch_change_sets_to_fact_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_change_sets
    ADD CONSTRAINT statusmatch_change_sets_to_fact_set_id_fkey FOREIGN KEY (to_fact_set_id) REFERENCES public.fact_sets(id);


--
-- Name: statusmatch_watch_pages statusmatch_watch_pages_current_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watch_pages
    ADD CONSTRAINT statusmatch_watch_pages_current_document_version_id_fkey FOREIGN KEY (current_document_version_id) REFERENCES public.document_versions(id);


--
-- Name: statusmatch_watch_pages statusmatch_watch_pages_watch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watch_pages
    ADD CONSTRAINT statusmatch_watch_pages_watch_id_fkey FOREIGN KEY (watch_id) REFERENCES public.statusmatch_watches(id) ON DELETE CASCADE;


--
-- Name: statusmatch_watches statusmatch_watches_current_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watches
    ADD CONSTRAINT statusmatch_watches_current_event_id_fkey FOREIGN KEY (current_event_id) REFERENCES public.status_events(id);


--
-- PostgreSQL database dump complete
--

\unrestrict xdaofwk0rhf8PgaiY7jlqeTVUa6vhP6kLTaCmBcMVUseElb4rg0QGOz9Y7gFjIW

