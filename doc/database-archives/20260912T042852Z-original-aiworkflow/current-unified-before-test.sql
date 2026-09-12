--
-- PostgreSQL database dump
--

\restrict a6BdwgxphkLcaVoBKrAQZH4bQSnTuegXaqm4wuz9ZrYKHj3hfyqBzmMVmC9MCEM

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

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: knowledge_guard_child(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.knowledge_guard_child() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE parent record;
    BEGIN
      FOR parent IN SELECT id, status FROM activity_knowledge_versions
        WHERE id IN ((to_jsonb(OLD)->>'knowledge_version_id')::uuid,
                     (to_jsonb(NEW)->>'knowledge_version_id')::uuid)
        ORDER BY id FOR UPDATE
      LOOP
        IF parent.status='PUBLISHED' THEN
          RAISE EXCEPTION 'published child facts are immutable' USING ERRCODE='23514';
        END IF;
      END LOOP;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;


--
-- Name: knowledge_guard_current(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.knowledge_guard_current() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF NEW.current_version_id IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM activity_knowledge_versions
         WHERE id=NEW.current_version_id AND activity_id=NEW.id AND status='PUBLISHED') THEN
        RAISE EXCEPTION 'current knowledge must be a published version of this activity' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;


--
-- Name: knowledge_guard_document(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.knowledge_guard_document() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'source document content is immutable' USING ERRCODE='23514';
      END IF;
      IF (to_jsonb(OLD) - 'section_parser_version' - 'updated_at') IS DISTINCT FROM
         (to_jsonb(NEW) - 'section_parser_version' - 'updated_at') THEN
        RAISE EXCEPTION 'source document content is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;


--
-- Name: knowledge_guard_price_map(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.knowledge_guard_price_map() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE parent record;
    BEGIN
      FOR parent IN SELECT k.id, k.status FROM activity_knowledge_versions k
        WHERE k.id IN (SELECT o.knowledge_version_id FROM application_option_versions o
          WHERE o.id IN ((to_jsonb(OLD)->>'option_version_id')::uuid,
                         (to_jsonb(NEW)->>'option_version_id')::uuid))
        ORDER BY k.id FOR UPDATE
      LOOP
        IF parent.status='PUBLISHED' THEN
          RAISE EXCEPTION 'published price associations are immutable' USING ERRCODE='23514';
        END IF;
      END LOOP;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;


--
-- Name: knowledge_guard_section(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.knowledge_guard_section() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN RAISE EXCEPTION 'source sections are immutable; create a new version' USING ERRCODE='23514'; END $$;


--
-- Name: knowledge_guard_version(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.knowledge_guard_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF OLD.status = 'PUBLISHED' THEN
        RAISE EXCEPTION 'published knowledge is immutable' USING ERRCODE='23514';
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activities (
    identity_key text NOT NULL,
    primary_program_id uuid,
    kind character varying(30) NOT NULL,
    edition_key text NOT NULL,
    current_version_id uuid,
    merged_into_id uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_activity_kind CHECK (((kind)::text = ANY ((ARRAY['STATUS_MATCH'::character varying, 'OTHER'::character varying])::text[])))
);


--
-- Name: activity_briefs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_briefs (
    activity_id uuid NOT NULL,
    knowledge_version_id uuid NOT NULL,
    brief_kind character varying(30) NOT NULL,
    previous_version_id uuid,
    generator_version text NOT NULL,
    status character varying(30) DEFAULT 'READY'::character varying NOT NULL,
    content jsonb NOT NULL,
    fact_refs jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_brief_kind CHECK (((brief_kind)::text = ANY ((ARRAY['CURRENT'::character varying, 'UPDATE'::character varying])::text[])))
);


--
-- Name: activity_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_documents (
    knowledge_version_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    role character varying(30) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_activity_document_role CHECK (((role)::text = ANY ((ARRAY['OFFICIAL_PRIMARY'::character varying, 'OFFICIAL_SUPPORT'::character varying, 'THIRD_PARTY'::character varying])::text[])))
);


--
-- Name: activity_edition_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_edition_reviews (
    source_binding_id uuid NOT NULL,
    activity_id uuid NOT NULL,
    base_version_id uuid,
    decision character varying(20) NOT NULL,
    target_activity_id uuid,
    reason text NOT NULL,
    request_json jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_edition_review_decision CHECK (((decision)::text = ANY ((ARRAY['SAME'::character varying, 'NEW'::character varying, 'UNRESOLVED'::character varying])::text[]))),
    CONSTRAINT ck_edition_review_target CHECK (((((decision)::text = 'UNRESOLVED'::text) AND (target_activity_id IS NULL)) OR (((decision)::text = ANY ((ARRAY['SAME'::character varying, 'NEW'::character varying])::text[])) AND (target_activity_id IS NOT NULL))))
);


--
-- Name: activity_knowledge_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_knowledge_versions (
    activity_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL,
    source_binding_id uuid NOT NULL,
    version_no integer NOT NULL,
    base_version_id uuid,
    status character varying(30) NOT NULL,
    schema_version integer NOT NULL,
    facts jsonb NOT NULL,
    fact_hash character varying(64) NOT NULL,
    source_hash character varying(64) NOT NULL,
    extraction_key text NOT NULL,
    published_at timestamp with time zone,
    validation_errors jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_knowledge_status CHECK (((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'VALIDATED'::character varying, 'PUBLISHED'::character varying, 'REJECTED'::character varying])::text[])))
);


--
-- Name: activity_observation_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_observation_state (
    activity_id uuid NOT NULL,
    last_checked_at timestamp with time zone,
    last_source_changed_at timestamp with time zone,
    last_error text,
    freshness character varying(30) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: activity_source_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_source_bindings (
    source_item_id uuid NOT NULL,
    subject_key text NOT NULL,
    activity_id uuid,
    status character varying(30) NOT NULL,
    reason text,
    observation jsonb NOT NULL,
    revision integer DEFAULT 0 NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_binding_revision CHECK ((revision >= 0)),
    CONSTRAINT ck_binding_status CHECK ((((status)::text = ANY ((ARRAY['UNRESOLVED'::character varying, 'BOUND'::character varying, 'RETIRED'::character varying])::text[])) AND (((status)::text <> 'BOUND'::text) OR (activity_id IS NOT NULL))))
);


--
-- Name: activity_supplements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_supplements (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    knowledge_version_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    input_key text NOT NULL,
    highlights jsonb NOT NULL
);


--
-- Name: agent_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_artifacts (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    kind character varying(30) NOT NULL,
    payload jsonb NOT NULL,
    content_hash character varying(64) NOT NULL,
    source_refs jsonb NOT NULL,
    created_by_turn_id uuid,
    created_by_call_id character varying(200),
    created_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: agent_delivery_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_delivery_events (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    seq integer NOT NULL,
    kind character varying(30) NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: agent_delivery_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_delivery_runs (
    turn_id uuid NOT NULL,
    runtime_fingerprint jsonb NOT NULL,
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    client_message_id character varying(100) NOT NULL,
    request jsonb NOT NULL,
    status character varying(30) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: agent_interactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_interactions (
    id uuid NOT NULL,
    status character varying(60) NOT NULL,
    state jsonb NOT NULL,
    provider character varying(100) NOT NULL,
    model character varying(200) NOT NULL,
    prompt_version character varying(100) NOT NULL,
    schema_version character varying(100) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revision integer DEFAULT 0 NOT NULL,
    active_turn_id uuid,
    lease_expires_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: agent_model_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_model_attempts (
    run_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    adapter_kind character varying(30) NOT NULL,
    status character varying(30) NOT NULL,
    request_hash character varying(64) NOT NULL,
    response_hash character varying(64),
    request_artifact_id uuid,
    response_artifact_id uuid,
    wire_artifact_id uuid,
    usage jsonb,
    error jsonb,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_model_attempt_number CHECK ((attempt_no >= 1)),
    CONSTRAINT ck_model_attempt_status CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'RUNNING'::character varying, 'COMPLETED'::character varying, 'FAILED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: agent_operation_receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_operation_receipts (
    id uuid NOT NULL,
    owner_key character varying(100) NOT NULL,
    idempotency_key character varying(500) NOT NULL,
    operation_kind character varying(40) NOT NULL,
    payload_hash character varying(64) NOT NULL,
    status character varying(20) NOT NULL,
    entity_kind character varying(30) NOT NULL,
    entity_id uuid NOT NULL,
    before jsonb,
    after jsonb,
    authorization_snapshot jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: agent_run_checkpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_run_checkpoints (
    run_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    phase character varying(30) NOT NULL,
    model_attempt integer NOT NULL,
    pending_calls jsonb NOT NULL,
    remaining_budget jsonb NOT NULL,
    last_message_ordinal integer NOT NULL,
    cancel_requested boolean NOT NULL,
    lease_owner uuid,
    heartbeat_at timestamp with time zone,
    revision integer NOT NULL
);


--
-- Name: agent_tool_calls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_tool_calls (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    provider_call_id character varying(200) NOT NULL,
    tool_name character varying(100) NOT NULL,
    tool_version character varying(30) NOT NULL,
    arguments jsonb NOT NULL,
    arguments_hash character varying(64) NOT NULL,
    effect character varying(30) NOT NULL,
    status character varying(30) NOT NULL,
    result_artifact_id uuid,
    operation_ref character varying(100),
    attempt integer NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    error jsonb
);


--
-- Name: agent_turns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_turns (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    client_message_id character varying(100) NOT NULL,
    request_hash character varying(64) NOT NULL,
    status character varying(30) NOT NULL,
    input_revision integer NOT NULL,
    result_revision integer,
    model_calls integer NOT NULL,
    repair_calls integer NOT NULL,
    error_code character varying(40),
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
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
    query jsonb NOT NULL,
    last_candidate_signature character varying(64),
    seen_candidate_signatures jsonb DEFAULT '[]'::jsonb NOT NULL,
    pending_result jsonb,
    pending_seen_at timestamp with time zone,
    notified_at timestamp with time zone,
    singleton_key integer DEFAULT 1 NOT NULL,
    revision integer DEFAULT 0 NOT NULL,
    holding_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    conditions_schema_version integer DEFAULT 3 NOT NULL,
    readiness jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_checked_snapshot character varying(64),
    result_id uuid,
    result_version integer DEFAULT 0 NOT NULL,
    ended_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_wait_singleton CHECK ((singleton_key = 1))
);


--
-- Name: agent_workspace_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_workspace_messages (
    id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    ordinal integer NOT NULL,
    role character varying(20) NOT NULL,
    content jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_message_ordinal CHECK ((ordinal >= 1)),
    CONSTRAINT ck_message_role CHECK (((role)::text = ANY ((ARRAY['USER'::character varying, 'ASSISTANT'::character varying, 'TOOL'::character varying, 'SYSTEM'::character varying])::text[])))
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
    source_binding_id uuid,
    activity_id uuid,
    base_version_id uuid,
    usage jsonb,
    stage character varying(100) NOT NULL,
    status character varying(30) NOT NULL,
    input_version character varying(255) NOT NULL,
    provider character varying(100) NOT NULL,
    model character varying(200) NOT NULL,
    model_config_version character varying(100) NOT NULL,
    prompt_version character varying(100) NOT NULL,
    schema_version character varying(100) NOT NULL,
    result jsonb,
    error text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_analysis_base_activity CHECK (((base_version_id IS NULL) OR (activity_id IS NOT NULL)))
);


--
-- Name: application_option_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.application_option_versions (
    knowledge_version_id uuid NOT NULL,
    activity_id uuid NOT NULL,
    option_id uuid NOT NULL,
    method character varying(30) NOT NULL,
    label text NOT NULL,
    source_scope jsonb NOT NULL,
    conditions jsonb NOT NULL,
    challenge jsonb NOT NULL,
    application_window jsonb NOT NULL,
    status_validity jsonb NOT NULL,
    action_link jsonb NOT NULL,
    availability character varying(30) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_option_availability CHECK (((availability)::text = ANY ((ARRAY['AVAILABLE'::character varying, 'UNAVAILABLE'::character varying, 'UNKNOWN'::character varying, 'CONFLICT'::character varying])::text[]))),
    CONSTRAINT ck_option_method CHECK (((method)::text = ANY ((ARRAY['MATCH'::character varying, 'CHALLENGE'::character varying, 'OTHER'::character varying])::text[])))
);


--
-- Name: application_options; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.application_options (
    activity_id uuid NOT NULL,
    logical_key text NOT NULL,
    retired_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
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
    limits jsonb NOT NULL,
    source_results jsonb NOT NULL,
    processing_result jsonb NOT NULL,
    lifecycle_result jsonb NOT NULL,
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
-- Name: collection_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.collection_runs (
    id uuid NOT NULL,
    source_id character varying(100) NOT NULL,
    idempotency_key character varying(255) NOT NULL,
    status character varying(30) NOT NULL,
    discovered_count integer NOT NULL,
    document_count integer NOT NULL,
    progress jsonb NOT NULL,
    error text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: document_sections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_sections (
    document_version_id uuid NOT NULL,
    section_key text NOT NULL,
    parent_id uuid,
    kind character varying(30) NOT NULL,
    ordinal integer NOT NULL,
    heading_path jsonb NOT NULL,
    body text NOT NULL,
    locator jsonb NOT NULL,
    related_section_ids jsonb NOT NULL,
    topics jsonb NOT NULL,
    id uuid NOT NULL,
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
    section_parser_version character varying(100),
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
    limits jsonb NOT NULL,
    source_results jsonb NOT NULL,
    processing_result jsonb NOT NULL,
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
    result jsonb,
    error text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: membership_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.membership_aliases (
    normalized_alias text NOT NULL,
    program_id uuid NOT NULL,
    tier_id uuid,
    locale character varying(30),
    origin text NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: membership_programs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.membership_programs (
    canonical_key text NOT NULL,
    display_name text NOT NULL,
    category character varying(30) NOT NULL,
    alliance character varying(30),
    metadata_provenance jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_program_category CHECK (((category)::text = ANY ((ARRAY['AIRLINE'::character varying, 'HOTEL'::character varying, 'CRUISE'::character varying, 'OTHER'::character varying])::text[])))
);


--
-- Name: membership_tiers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.membership_tiers (
    program_id uuid NOT NULL,
    canonical_key text NOT NULL,
    display_name text NOT NULL,
    rank integer,
    rank_provenance jsonb,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: option_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.option_mappings (
    option_version_id uuid NOT NULL,
    knowledge_version_id uuid NOT NULL,
    source_scope jsonb NOT NULL,
    target_program_id uuid NOT NULL,
    target_tier_id uuid NOT NULL,
    conditions jsonb NOT NULL,
    availability character varying(30) NOT NULL,
    semantic_key text NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_mapping_availability CHECK (((availability)::text = ANY ((ARRAY['AVAILABLE'::character varying, 'UNAVAILABLE'::character varying, 'UNKNOWN'::character varying, 'CONFLICT'::character varying])::text[])))
);


--
-- Name: option_price_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.option_price_mappings (
    price_id uuid NOT NULL,
    mapping_id uuid NOT NULL,
    option_version_id uuid NOT NULL
);


--
-- Name: option_prices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.option_prices (
    option_version_id uuid NOT NULL,
    knowledge_version_id uuid NOT NULL,
    price_key text NOT NULL,
    target_tier_id uuid,
    target_scope character varying(30) NOT NULL,
    mapping_scope character varying(30) NOT NULL,
    amount numeric(18,4),
    currency character varying(3),
    known_state character varying(30) NOT NULL,
    fee_role character varying(30) NOT NULL,
    charge_key text NOT NULL,
    combination character varying(30) NOT NULL,
    alternative_group text,
    conditions jsonb NOT NULL,
    raw_text text DEFAULT ''::text NOT NULL,
    availability character varying(30) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_price_availability CHECK (((availability)::text = ANY ((ARRAY['AVAILABLE'::character varying, 'UNAVAILABLE'::character varying, 'UNKNOWN'::character varying, 'CONFLICT'::character varying])::text[]))),
    CONSTRAINT ck_price_combination CHECK (((((combination)::text = 'ALTERNATIVE'::text) AND (alternative_group IS NOT NULL)) OR (((combination)::text = ANY ((ARRAY['REQUIRED'::character varying, 'CONDITIONAL'::character varying])::text[])) AND (alternative_group IS NULL)))),
    CONSTRAINT ck_price_known_state CHECK (((((known_state)::text = 'KNOWN'::text) AND (amount IS NOT NULL) AND ((amount = (0)::numeric) OR (currency IS NOT NULL))) OR (((known_state)::text = ANY ((ARRAY['UNKNOWN'::character varying, 'CONFLICT'::character varying, 'NOT_APPLICABLE'::character varying])::text[])) AND (amount IS NULL)))),
    CONSTRAINT ck_price_mapping_scope CHECK (((mapping_scope)::text = ANY ((ARRAY['EXPLICIT'::character varying, 'ALL_MAPPINGS'::character varying])::text[]))),
    CONSTRAINT ck_price_nonnegative CHECK (((amount IS NULL) OR (amount >= (0)::numeric))),
    CONSTRAINT ck_price_role CHECK (((fee_role)::text = ANY ((ARRAY['APPLICATION'::character varying, 'CHALLENGE_SPEND'::character varying, 'OTHER'::character varying])::text[]))),
    CONSTRAINT ck_price_target_scope CHECK (((((target_scope)::text = 'EXACT'::text) AND (target_tier_id IS NOT NULL)) OR (((target_scope)::text = 'ALL_TARGETS'::text) AND (target_tier_id IS NULL))))
);


--
-- Name: review_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_decisions (
    id uuid NOT NULL,
    action character varying(50) NOT NULL,
    activity_id uuid NOT NULL,
    knowledge_version_id uuid,
    target_activity_id uuid,
    source_binding_id uuid,
    reason text NOT NULL,
    actor character varying(200) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_review_action_scope CHECK (((((action)::text = ANY ((ARRAY['APPROVE'::character varying, 'REJECT'::character varying])::text[])) AND (knowledge_version_id IS NOT NULL) AND (target_activity_id IS NULL)) OR (((action)::text = 'MERGE'::text) AND (knowledge_version_id IS NULL) AND (target_activity_id IS NOT NULL) AND (target_activity_id <> activity_id)))),
    CONSTRAINT ck_review_reason CHECK ((length(TRIM(BOTH FROM reason)) > 0))
);


--
-- Name: source_automation_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_automation_states (
    source_id character varying(100) NOT NULL,
    discovery_cursor character varying(500),
    last_day_bucket date,
    last_attempt_at timestamp with time zone,
    last_success_at timestamp with time zone,
    last_failure_at timestamp with time zone,
    last_error text,
    consecutive_failures integer NOT NULL,
    last_new_document_count integer NOT NULL,
    pending_document_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
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
    raw_metadata jsonb NOT NULL,
    document_role character varying(30) DEFAULT 'OTHER'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    id character varying(100) NOT NULL,
    name character varying(300) NOT NULL,
    adapter_type character varying(100) NOT NULL,
    discovery_config jsonb NOT NULL,
    access_policy jsonb NOT NULL,
    collection_cadence character varying(100),
    automatic_scheduling boolean NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
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
    program_id uuid,
    tier_id uuid,
    revision integer DEFAULT 1 NOT NULL,
    identity_status character varying(30) DEFAULT 'NEEDS_CONFIRMATION'::character varying NOT NULL,
    source_record jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_holding_confirmed_identity CHECK ((((identity_status)::text <> 'CONFIRMED'::text) OR ((program_id IS NOT NULL) AND (tier_id IS NOT NULL)))),
    CONSTRAINT ck_holding_revision CHECK ((revision >= 1)),
    CONSTRAINT ck_holding_tier_requires_program CHECK (((tier_id IS NULL) OR (program_id IS NOT NULL)))
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
    source_binding_id uuid,
    last_checked_at timestamp with time zone,
    last_changed_at timestamp with time zone,
    last_error text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: user_business_operations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_business_operations (
    sequence integer NOT NULL,
    operation_id uuid NOT NULL,
    entity_kind character varying(20) NOT NULL,
    entity_id uuid NOT NULL,
    before_state jsonb,
    after_state jsonb,
    payload_hash character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_user_operation_kind CHECK (((entity_kind)::text = ANY ((ARRAY['HOLDING'::character varying, 'WAIT_GOAL'::character varying])::text[])))
);


--
-- Name: user_business_operations_sequence_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_business_operations_sequence_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_business_operations_sequence_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_business_operations_sequence_seq OWNED BY public.user_business_operations.sequence;


--
-- Name: user_business_operations sequence; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_business_operations ALTER COLUMN sequence SET DEFAULT nextval('public.user_business_operations_sequence_seq'::regclass);


--
-- Name: activities activities_identity_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_identity_key_key UNIQUE (identity_key);


--
-- Name: activities activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (id);


--
-- Name: activity_briefs activity_briefs_knowledge_version_id_brief_kind_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_briefs
    ADD CONSTRAINT activity_briefs_knowledge_version_id_brief_kind_key UNIQUE (knowledge_version_id, brief_kind);


--
-- Name: activity_briefs activity_briefs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_briefs
    ADD CONSTRAINT activity_briefs_pkey PRIMARY KEY (id);


--
-- Name: activity_documents activity_documents_knowledge_version_id_document_version_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_documents
    ADD CONSTRAINT activity_documents_knowledge_version_id_document_version_id_key UNIQUE (knowledge_version_id, document_version_id, role);


--
-- Name: activity_documents activity_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_documents
    ADD CONSTRAINT activity_documents_pkey PRIMARY KEY (id);


--
-- Name: activity_edition_reviews activity_edition_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_edition_reviews
    ADD CONSTRAINT activity_edition_reviews_pkey PRIMARY KEY (id);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_activity_id_extraction_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_activity_id_extraction_key_key UNIQUE (activity_id, extraction_key);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_activity_id_version_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_activity_id_version_no_key UNIQUE (activity_id, version_no);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_id_activity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_id_activity_id_key UNIQUE (id, activity_id);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_pkey PRIMARY KEY (id);


--
-- Name: activity_observation_state activity_observation_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_observation_state
    ADD CONSTRAINT activity_observation_state_pkey PRIMARY KEY (activity_id);


--
-- Name: activity_source_bindings activity_source_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_source_bindings
    ADD CONSTRAINT activity_source_bindings_pkey PRIMARY KEY (id);


--
-- Name: activity_source_bindings activity_source_bindings_source_item_id_subject_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_source_bindings
    ADD CONSTRAINT activity_source_bindings_source_item_id_subject_key_key UNIQUE (source_item_id, subject_key);


--
-- Name: activity_supplements activity_supplements_input_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_supplements
    ADD CONSTRAINT activity_supplements_input_key_key UNIQUE (input_key);


--
-- Name: activity_supplements activity_supplements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_supplements
    ADD CONSTRAINT activity_supplements_pkey PRIMARY KEY (id);


--
-- Name: agent_artifacts agent_artifacts_id_workspace_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_artifacts
    ADD CONSTRAINT agent_artifacts_id_workspace_id_key UNIQUE (id, workspace_id);


--
-- Name: agent_artifacts agent_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_artifacts
    ADD CONSTRAINT agent_artifacts_pkey PRIMARY KEY (id);


--
-- Name: agent_delivery_events agent_delivery_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_events
    ADD CONSTRAINT agent_delivery_events_pkey PRIMARY KEY (id);


--
-- Name: agent_delivery_events agent_delivery_events_run_id_seq_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_events
    ADD CONSTRAINT agent_delivery_events_run_id_seq_key UNIQUE (run_id, seq);


--
-- Name: agent_delivery_runs agent_delivery_runs_id_workspace_id_turn_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_runs
    ADD CONSTRAINT agent_delivery_runs_id_workspace_id_turn_id_key UNIQUE (id, workspace_id, turn_id);


--
-- Name: agent_delivery_runs agent_delivery_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_runs
    ADD CONSTRAINT agent_delivery_runs_pkey PRIMARY KEY (id);


--
-- Name: agent_delivery_runs agent_delivery_runs_turn_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_runs
    ADD CONSTRAINT agent_delivery_runs_turn_id_key UNIQUE (turn_id);


--
-- Name: agent_delivery_runs agent_delivery_runs_workspace_id_client_message_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_runs
    ADD CONSTRAINT agent_delivery_runs_workspace_id_client_message_id_key UNIQUE (workspace_id, client_message_id);


--
-- Name: agent_interactions agent_interactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_interactions
    ADD CONSTRAINT agent_interactions_pkey PRIMARY KEY (id);


--
-- Name: agent_model_attempts agent_model_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_model_attempts
    ADD CONSTRAINT agent_model_attempts_pkey PRIMARY KEY (id);


--
-- Name: agent_model_attempts agent_model_attempts_run_id_attempt_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_model_attempts
    ADD CONSTRAINT agent_model_attempts_run_id_attempt_no_key UNIQUE (run_id, attempt_no);


--
-- Name: agent_operation_receipts agent_operation_receipts_owner_key_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_operation_receipts
    ADD CONSTRAINT agent_operation_receipts_owner_key_idempotency_key_key UNIQUE (owner_key, idempotency_key);


--
-- Name: agent_operation_receipts agent_operation_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_operation_receipts
    ADD CONSTRAINT agent_operation_receipts_pkey PRIMARY KEY (id);


--
-- Name: agent_run_checkpoints agent_run_checkpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_checkpoints
    ADD CONSTRAINT agent_run_checkpoints_pkey PRIMARY KEY (run_id);


--
-- Name: agent_tool_calls agent_tool_calls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_pkey PRIMARY KEY (id);


--
-- Name: agent_tool_calls agent_tool_calls_turn_id_provider_call_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_turn_id_provider_call_id_key UNIQUE (turn_id, provider_call_id);


--
-- Name: agent_turns agent_turns_id_workspace_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_turns
    ADD CONSTRAINT agent_turns_id_workspace_id_key UNIQUE (id, workspace_id);


--
-- Name: agent_turns agent_turns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_turns
    ADD CONSTRAINT agent_turns_pkey PRIMARY KEY (id);


--
-- Name: agent_turns agent_turns_workspace_id_client_message_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_turns
    ADD CONSTRAINT agent_turns_workspace_id_client_message_id_key UNIQUE (workspace_id, client_message_id);


--
-- Name: agent_wait_goals agent_wait_goals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_wait_goals
    ADD CONSTRAINT agent_wait_goals_pkey PRIMARY KEY (id);


--
-- Name: agent_workspace_messages agent_workspace_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_workspace_messages
    ADD CONSTRAINT agent_workspace_messages_pkey PRIMARY KEY (id);


--
-- Name: agent_workspace_messages agent_workspace_messages_workspace_id_ordinal_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_workspace_messages
    ADD CONSTRAINT agent_workspace_messages_workspace_id_ordinal_key UNIQUE (workspace_id, ordinal);


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
-- Name: application_option_versions application_option_versions_id_knowledge_version_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_option_versions
    ADD CONSTRAINT application_option_versions_id_knowledge_version_id_key UNIQUE (id, knowledge_version_id);


--
-- Name: application_option_versions application_option_versions_knowledge_version_id_option_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_option_versions
    ADD CONSTRAINT application_option_versions_knowledge_version_id_option_id_key UNIQUE (knowledge_version_id, option_id);


--
-- Name: application_option_versions application_option_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_option_versions
    ADD CONSTRAINT application_option_versions_pkey PRIMARY KEY (id);


--
-- Name: application_options application_options_activity_id_logical_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_options
    ADD CONSTRAINT application_options_activity_id_logical_key_key UNIQUE (activity_id, logical_key);


--
-- Name: application_options application_options_id_activity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_options
    ADD CONSTRAINT application_options_id_activity_id_key UNIQUE (id, activity_id);


--
-- Name: application_options application_options_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_options
    ADD CONSTRAINT application_options_pkey PRIMARY KEY (id);


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
-- Name: document_sections document_sections_document_version_id_section_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_sections
    ADD CONSTRAINT document_sections_document_version_id_section_key_key UNIQUE (document_version_id, section_key);


--
-- Name: document_sections document_sections_id_document_version_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_sections
    ADD CONSTRAINT document_sections_id_document_version_id_key UNIQUE (id, document_version_id);


--
-- Name: document_sections document_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_sections
    ADD CONSTRAINT document_sections_pkey PRIMARY KEY (id);


--
-- Name: document_versions document_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_pkey PRIMARY KEY (id);


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
-- Name: membership_aliases membership_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_aliases
    ADD CONSTRAINT membership_aliases_pkey PRIMARY KEY (id);


--
-- Name: membership_programs membership_programs_canonical_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_programs
    ADD CONSTRAINT membership_programs_canonical_key_key UNIQUE (canonical_key);


--
-- Name: membership_programs membership_programs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_programs
    ADD CONSTRAINT membership_programs_pkey PRIMARY KEY (id);


--
-- Name: membership_tiers membership_tiers_id_program_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_tiers
    ADD CONSTRAINT membership_tiers_id_program_id_key UNIQUE (id, program_id);


--
-- Name: membership_tiers membership_tiers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_tiers
    ADD CONSTRAINT membership_tiers_pkey PRIMARY KEY (id);


--
-- Name: membership_tiers membership_tiers_program_id_canonical_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_tiers
    ADD CONSTRAINT membership_tiers_program_id_canonical_key_key UNIQUE (program_id, canonical_key);


--
-- Name: option_mappings option_mappings_id_option_version_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_mappings
    ADD CONSTRAINT option_mappings_id_option_version_id_key UNIQUE (id, option_version_id);


--
-- Name: option_mappings option_mappings_option_version_id_semantic_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_mappings
    ADD CONSTRAINT option_mappings_option_version_id_semantic_key_key UNIQUE (option_version_id, semantic_key);


--
-- Name: option_mappings option_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_mappings
    ADD CONSTRAINT option_mappings_pkey PRIMARY KEY (id);


--
-- Name: option_price_mappings option_price_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_price_mappings
    ADD CONSTRAINT option_price_mappings_pkey PRIMARY KEY (price_id, mapping_id);


--
-- Name: option_prices option_prices_id_option_version_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_prices
    ADD CONSTRAINT option_prices_id_option_version_id_key UNIQUE (id, option_version_id);


--
-- Name: option_prices option_prices_option_version_id_price_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_prices
    ADD CONSTRAINT option_prices_option_version_id_price_key_key UNIQUE (option_version_id, price_key);


--
-- Name: option_prices option_prices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_prices
    ADD CONSTRAINT option_prices_pkey PRIMARY KEY (id);


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
-- Name: statusmatch_watches statusmatch_watches_source_binding_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watches
    ADD CONSTRAINT statusmatch_watches_source_binding_id_key UNIQUE (source_binding_id);


--
-- Name: document_versions uq_document_versions_source_item_raw_parser; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT uq_document_versions_source_item_raw_parser UNIQUE (source_item_id, raw_hash, parser_version);


--
-- Name: user_business_operations user_business_operations_operation_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_business_operations
    ADD CONSTRAINT user_business_operations_operation_id_key UNIQUE (operation_id);


--
-- Name: user_business_operations user_business_operations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_business_operations
    ADD CONSTRAINT user_business_operations_pkey PRIMARY KEY (sequence);


--
-- Name: ix_activities_primary_program_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activities_primary_program_id ON public.activities USING btree (primary_program_id);


--
-- Name: ix_activity_supplements_knowledge_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_activity_supplements_knowledge_version_id ON public.activity_supplements USING btree (knowledge_version_id);


--
-- Name: ix_agent_artifact_scope_kind_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_artifact_scope_kind_time ON public.agent_artifacts USING btree (workspace_id, kind, created_at);


--
-- Name: ix_agent_delivery_events_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_delivery_events_run_id ON public.agent_delivery_events USING btree (run_id);


--
-- Name: ix_agent_delivery_runs_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_delivery_runs_workspace_id ON public.agent_delivery_runs USING btree (workspace_id);


--
-- Name: ix_agent_interactions_status_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_interactions_status_expires ON public.agent_interactions USING btree (status, expires_at);


--
-- Name: ix_agent_run_checkpoints_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_run_checkpoints_workspace_id ON public.agent_run_checkpoints USING btree (workspace_id);


--
-- Name: ix_agent_tool_calls_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_tool_calls_workspace_id ON public.agent_tool_calls USING btree (workspace_id);


--
-- Name: ix_agent_turns_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_turns_workspace_id ON public.agent_turns USING btree (workspace_id);


--
-- Name: ix_agent_workspace_messages_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_workspace_messages_workspace_id ON public.agent_workspace_messages USING btree (workspace_id);


--
-- Name: ix_analysis_binding_stage_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analysis_binding_stage_time ON public.analysis_runs USING btree (source_binding_id, stage, created_at);


--
-- Name: ix_analysis_status_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_analysis_status_time ON public.analysis_runs USING btree (status, created_at);


--
-- Name: ix_binding_activity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_binding_activity ON public.activity_source_bindings USING btree (activity_id);


--
-- Name: ix_binding_status_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_binding_status_time ON public.activity_source_bindings USING btree (status, updated_at);


--
-- Name: ix_document_sections_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_document_sections_order ON public.document_sections USING btree (document_version_id, ordinal);


--
-- Name: ix_document_versions_normalized_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_document_versions_normalized_hash ON public.document_versions USING btree (normalized_hash);


--
-- Name: ix_edition_review_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_edition_review_source ON public.activity_edition_reviews USING btree (source_binding_id, created_at);


--
-- Name: ix_knowledge_activity_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_activity_status ON public.activity_knowledge_versions USING btree (activity_id, status);


--
-- Name: ix_knowledge_binding_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_binding_time ON public.activity_knowledge_versions USING btree (source_binding_id, created_at);


--
-- Name: ix_membership_alias_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_membership_alias_lookup ON public.membership_aliases USING btree (normalized_alias);


--
-- Name: ix_model_attempt_status_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_attempt_status_time ON public.agent_model_attempts USING btree (status, created_at);


--
-- Name: ix_option_mapping_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_option_mapping_target ON public.option_mappings USING btree (target_program_id, target_tier_id);


--
-- Name: ix_option_price_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_option_price_target ON public.option_prices USING btree (option_version_id, target_tier_id);


--
-- Name: ix_review_activity_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_activity_time ON public.review_decisions USING btree (activity_id, created_at);


--
-- Name: ix_review_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_version ON public.review_decisions USING btree (knowledge_version_id);


--
-- Name: ix_source_items_canonical_url; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_source_items_canonical_url ON public.source_items USING btree (canonical_url);


--
-- Name: uq_agent_presentation_call_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_presentation_call_scope ON public.agent_artifacts USING btree (workspace_id, created_by_turn_id, created_by_call_id) WHERE (((kind)::text = 'PRESENTATION'::text) AND (created_by_turn_id IS NOT NULL));


--
-- Name: uq_agent_wait_goals_single_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_wait_goals_single_active ON public.agent_wait_goals USING btree (singleton_key) WHERE ((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'RESULT_PENDING'::character varying, 'NEEDS_RECONFIRMATION'::character varying])::text[]));


--
-- Name: uq_program_alias; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_program_alias ON public.membership_aliases USING btree (normalized_alias, program_id) WHERE (tier_id IS NULL);


--
-- Name: uq_tier_alias; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tier_alias ON public.membership_aliases USING btree (normalized_alias, program_id, tier_id) WHERE (tier_id IS NOT NULL);


--
-- Name: activity_documents immutable_activity_documents; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_activity_documents BEFORE INSERT OR DELETE OR UPDATE ON public.activity_documents FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_child();


--
-- Name: application_option_versions immutable_application_option_versions; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_application_option_versions BEFORE INSERT OR DELETE OR UPDATE ON public.application_option_versions FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_child();


--
-- Name: document_versions immutable_document; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_document BEFORE DELETE OR UPDATE ON public.document_versions FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_document();


--
-- Name: activity_knowledge_versions immutable_knowledge; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_knowledge BEFORE DELETE OR UPDATE ON public.activity_knowledge_versions FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_version();


--
-- Name: option_mappings immutable_option_mappings; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_option_mappings BEFORE INSERT OR DELETE OR UPDATE ON public.option_mappings FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_child();


--
-- Name: option_prices immutable_option_prices; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_option_prices BEFORE INSERT OR DELETE OR UPDATE ON public.option_prices FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_child();


--
-- Name: option_price_mappings immutable_price_mapping; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_price_mapping BEFORE INSERT OR DELETE OR UPDATE ON public.option_price_mappings FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_price_map();


--
-- Name: document_sections immutable_section; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER immutable_section BEFORE DELETE OR UPDATE ON public.document_sections FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_section();


--
-- Name: activities valid_current; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER valid_current BEFORE INSERT OR UPDATE OF current_version_id ON public.activities FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_current();


--
-- Name: activities activities_merged_into_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_merged_into_id_fkey FOREIGN KEY (merged_into_id) REFERENCES public.activities(id);


--
-- Name: activities activities_primary_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_primary_program_id_fkey FOREIGN KEY (primary_program_id) REFERENCES public.membership_programs(id);


--
-- Name: activity_briefs activity_briefs_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_briefs
    ADD CONSTRAINT activity_briefs_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: activity_briefs activity_briefs_knowledge_version_id_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_briefs
    ADD CONSTRAINT activity_briefs_knowledge_version_id_activity_id_fkey FOREIGN KEY (knowledge_version_id, activity_id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: activity_briefs activity_briefs_knowledge_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_briefs
    ADD CONSTRAINT activity_briefs_knowledge_version_id_fkey FOREIGN KEY (knowledge_version_id) REFERENCES public.activity_knowledge_versions(id);


--
-- Name: activity_briefs activity_briefs_previous_version_id_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_briefs
    ADD CONSTRAINT activity_briefs_previous_version_id_activity_id_fkey FOREIGN KEY (previous_version_id, activity_id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: activity_briefs activity_briefs_previous_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_briefs
    ADD CONSTRAINT activity_briefs_previous_version_id_fkey FOREIGN KEY (previous_version_id) REFERENCES public.activity_knowledge_versions(id);


--
-- Name: activity_documents activity_documents_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_documents
    ADD CONSTRAINT activity_documents_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: activity_documents activity_documents_knowledge_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_documents
    ADD CONSTRAINT activity_documents_knowledge_version_id_fkey FOREIGN KEY (knowledge_version_id) REFERENCES public.activity_knowledge_versions(id);


--
-- Name: activity_edition_reviews activity_edition_reviews_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_edition_reviews
    ADD CONSTRAINT activity_edition_reviews_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: activity_edition_reviews activity_edition_reviews_base_version_id_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_edition_reviews
    ADD CONSTRAINT activity_edition_reviews_base_version_id_activity_id_fkey FOREIGN KEY (base_version_id, activity_id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: activity_edition_reviews activity_edition_reviews_source_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_edition_reviews
    ADD CONSTRAINT activity_edition_reviews_source_binding_id_fkey FOREIGN KEY (source_binding_id) REFERENCES public.activity_source_bindings(id);


--
-- Name: activity_edition_reviews activity_edition_reviews_target_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_edition_reviews
    ADD CONSTRAINT activity_edition_reviews_target_activity_id_fkey FOREIGN KEY (target_activity_id) REFERENCES public.activities(id);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_analysis_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_analysis_run_id_fkey FOREIGN KEY (analysis_run_id) REFERENCES public.analysis_runs(id);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_base_version_id_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_base_version_id_activity_id_fkey FOREIGN KEY (base_version_id, activity_id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: activity_knowledge_versions activity_knowledge_versions_source_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_knowledge_versions
    ADD CONSTRAINT activity_knowledge_versions_source_binding_id_fkey FOREIGN KEY (source_binding_id) REFERENCES public.activity_source_bindings(id);


--
-- Name: activity_observation_state activity_observation_state_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_observation_state
    ADD CONSTRAINT activity_observation_state_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: activity_source_bindings activity_source_bindings_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_source_bindings
    ADD CONSTRAINT activity_source_bindings_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: activity_source_bindings activity_source_bindings_source_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_source_bindings
    ADD CONSTRAINT activity_source_bindings_source_item_id_fkey FOREIGN KEY (source_item_id) REFERENCES public.source_items(id);


--
-- Name: activity_supplements activity_supplements_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_supplements
    ADD CONSTRAINT activity_supplements_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: activity_supplements activity_supplements_knowledge_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_supplements
    ADD CONSTRAINT activity_supplements_knowledge_version_id_fkey FOREIGN KEY (knowledge_version_id) REFERENCES public.activity_knowledge_versions(id);


--
-- Name: agent_artifacts agent_artifacts_created_by_turn_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_artifacts
    ADD CONSTRAINT agent_artifacts_created_by_turn_id_workspace_id_fkey FOREIGN KEY (created_by_turn_id, workspace_id) REFERENCES public.agent_turns(id, workspace_id) ON DELETE CASCADE;


--
-- Name: agent_artifacts agent_artifacts_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_artifacts
    ADD CONSTRAINT agent_artifacts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.agent_interactions(id) ON DELETE CASCADE;


--
-- Name: agent_delivery_events agent_delivery_events_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_events
    ADD CONSTRAINT agent_delivery_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_delivery_runs(id) ON DELETE CASCADE;


--
-- Name: agent_delivery_runs agent_delivery_runs_turn_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_runs
    ADD CONSTRAINT agent_delivery_runs_turn_id_workspace_id_fkey FOREIGN KEY (turn_id, workspace_id) REFERENCES public.agent_turns(id, workspace_id) ON DELETE CASCADE;


--
-- Name: agent_delivery_runs agent_delivery_runs_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_delivery_runs
    ADD CONSTRAINT agent_delivery_runs_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.agent_interactions(id) ON DELETE CASCADE;


--
-- Name: agent_model_attempts agent_model_attempts_request_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_model_attempts
    ADD CONSTRAINT agent_model_attempts_request_artifact_id_fkey FOREIGN KEY (request_artifact_id) REFERENCES public.agent_artifacts(id) ON DELETE SET NULL;


--
-- Name: agent_model_attempts agent_model_attempts_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_model_attempts
    ADD CONSTRAINT agent_model_attempts_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES public.agent_artifacts(id) ON DELETE SET NULL;


--
-- Name: agent_model_attempts agent_model_attempts_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_model_attempts
    ADD CONSTRAINT agent_model_attempts_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_delivery_runs(id) ON DELETE CASCADE;


--
-- Name: agent_model_attempts agent_model_attempts_wire_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_model_attempts
    ADD CONSTRAINT agent_model_attempts_wire_artifact_id_fkey FOREIGN KEY (wire_artifact_id) REFERENCES public.agent_artifacts(id) ON DELETE SET NULL;


--
-- Name: agent_run_checkpoints agent_run_checkpoints_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_checkpoints
    ADD CONSTRAINT agent_run_checkpoints_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_delivery_runs(id) ON DELETE CASCADE;


--
-- Name: agent_run_checkpoints agent_run_checkpoints_run_id_workspace_id_turn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_checkpoints
    ADD CONSTRAINT agent_run_checkpoints_run_id_workspace_id_turn_id_fkey FOREIGN KEY (run_id, workspace_id, turn_id) REFERENCES public.agent_delivery_runs(id, workspace_id, turn_id) ON DELETE CASCADE;


--
-- Name: agent_run_checkpoints agent_run_checkpoints_turn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_checkpoints
    ADD CONSTRAINT agent_run_checkpoints_turn_id_fkey FOREIGN KEY (turn_id) REFERENCES public.agent_turns(id) ON DELETE CASCADE;


--
-- Name: agent_run_checkpoints agent_run_checkpoints_turn_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_checkpoints
    ADD CONSTRAINT agent_run_checkpoints_turn_id_workspace_id_fkey FOREIGN KEY (turn_id, workspace_id) REFERENCES public.agent_turns(id, workspace_id) ON DELETE CASCADE;


--
-- Name: agent_run_checkpoints agent_run_checkpoints_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_checkpoints
    ADD CONSTRAINT agent_run_checkpoints_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.agent_interactions(id) ON DELETE CASCADE;


--
-- Name: agent_tool_calls agent_tool_calls_result_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_result_artifact_id_fkey FOREIGN KEY (result_artifact_id) REFERENCES public.agent_artifacts(id) ON DELETE SET NULL;


--
-- Name: agent_tool_calls agent_tool_calls_result_artifact_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_result_artifact_id_workspace_id_fkey FOREIGN KEY (result_artifact_id, workspace_id) REFERENCES public.agent_artifacts(id, workspace_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: agent_tool_calls agent_tool_calls_turn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_turn_id_fkey FOREIGN KEY (turn_id) REFERENCES public.agent_turns(id) ON DELETE CASCADE;


--
-- Name: agent_tool_calls agent_tool_calls_turn_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_turn_id_workspace_id_fkey FOREIGN KEY (turn_id, workspace_id) REFERENCES public.agent_turns(id, workspace_id) ON DELETE CASCADE;


--
-- Name: agent_tool_calls agent_tool_calls_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.agent_interactions(id) ON DELETE CASCADE;


--
-- Name: agent_turns agent_turns_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_turns
    ADD CONSTRAINT agent_turns_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.agent_interactions(id) ON DELETE CASCADE;


--
-- Name: agent_wait_goals agent_wait_goals_source_interaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_wait_goals
    ADD CONSTRAINT agent_wait_goals_source_interaction_id_fkey FOREIGN KEY (source_interaction_id) REFERENCES public.agent_interactions(id) ON DELETE SET NULL;


--
-- Name: agent_workspace_messages agent_workspace_messages_turn_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_workspace_messages
    ADD CONSTRAINT agent_workspace_messages_turn_id_workspace_id_fkey FOREIGN KEY (turn_id, workspace_id) REFERENCES public.agent_turns(id, workspace_id) ON DELETE CASCADE;


--
-- Name: agent_workspace_messages agent_workspace_messages_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_workspace_messages
    ADD CONSTRAINT agent_workspace_messages_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.agent_interactions(id) ON DELETE CASCADE;


--
-- Name: analysis_runs analysis_runs_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT analysis_runs_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: analysis_runs analysis_runs_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT analysis_runs_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: analysis_runs analysis_runs_source_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT analysis_runs_source_binding_id_fkey FOREIGN KEY (source_binding_id) REFERENCES public.activity_source_bindings(id);


--
-- Name: application_option_versions application_option_versions_knowledge_version_id_activity__fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_option_versions
    ADD CONSTRAINT application_option_versions_knowledge_version_id_activity__fkey FOREIGN KEY (knowledge_version_id, activity_id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: application_option_versions application_option_versions_option_id_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_option_versions
    ADD CONSTRAINT application_option_versions_option_id_activity_id_fkey FOREIGN KEY (option_id, activity_id) REFERENCES public.application_options(id, activity_id);


--
-- Name: application_options application_options_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.application_options
    ADD CONSTRAINT application_options_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: collection_runs collection_runs_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.collection_runs
    ADD CONSTRAINT collection_runs_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


--
-- Name: document_sections document_sections_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_sections
    ADD CONSTRAINT document_sections_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);


--
-- Name: document_sections document_sections_parent_id_document_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_sections
    ADD CONSTRAINT document_sections_parent_id_document_version_id_fkey FOREIGN KEY (parent_id, document_version_id) REFERENCES public.document_sections(id, document_version_id);


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
-- Name: activities fk_activity_current_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT fk_activity_current_version FOREIGN KEY (current_version_id, id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: analysis_runs fk_analysis_base; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analysis_runs
    ADD CONSTRAINT fk_analysis_base FOREIGN KEY (base_version_id, activity_id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: status_holdings fk_holding_program; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_holdings
    ADD CONSTRAINT fk_holding_program FOREIGN KEY (program_id) REFERENCES public.membership_programs(id);


--
-- Name: status_holdings fk_holding_tier_program; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status_holdings
    ADD CONSTRAINT fk_holding_tier_program FOREIGN KEY (tier_id, program_id) REFERENCES public.membership_tiers(id, program_id);


--
-- Name: agent_interactions fk_workspace_active_turn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_interactions
    ADD CONSTRAINT fk_workspace_active_turn FOREIGN KEY (active_turn_id, id) REFERENCES public.agent_turns(id, workspace_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: membership_aliases membership_aliases_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_aliases
    ADD CONSTRAINT membership_aliases_program_id_fkey FOREIGN KEY (program_id) REFERENCES public.membership_programs(id);


--
-- Name: membership_aliases membership_aliases_tier_id_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_aliases
    ADD CONSTRAINT membership_aliases_tier_id_program_id_fkey FOREIGN KEY (tier_id, program_id) REFERENCES public.membership_tiers(id, program_id);


--
-- Name: membership_tiers membership_tiers_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_tiers
    ADD CONSTRAINT membership_tiers_program_id_fkey FOREIGN KEY (program_id) REFERENCES public.membership_programs(id);


--
-- Name: option_mappings option_mappings_option_version_id_knowledge_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_mappings
    ADD CONSTRAINT option_mappings_option_version_id_knowledge_version_id_fkey FOREIGN KEY (option_version_id, knowledge_version_id) REFERENCES public.application_option_versions(id, knowledge_version_id);


--
-- Name: option_mappings option_mappings_target_tier_id_target_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_mappings
    ADD CONSTRAINT option_mappings_target_tier_id_target_program_id_fkey FOREIGN KEY (target_tier_id, target_program_id) REFERENCES public.membership_tiers(id, program_id);


--
-- Name: option_price_mappings option_price_mappings_mapping_id_option_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_price_mappings
    ADD CONSTRAINT option_price_mappings_mapping_id_option_version_id_fkey FOREIGN KEY (mapping_id, option_version_id) REFERENCES public.option_mappings(id, option_version_id);


--
-- Name: option_price_mappings option_price_mappings_price_id_option_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_price_mappings
    ADD CONSTRAINT option_price_mappings_price_id_option_version_id_fkey FOREIGN KEY (price_id, option_version_id) REFERENCES public.option_prices(id, option_version_id);


--
-- Name: option_prices option_prices_option_version_id_knowledge_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_prices
    ADD CONSTRAINT option_prices_option_version_id_knowledge_version_id_fkey FOREIGN KEY (option_version_id, knowledge_version_id) REFERENCES public.application_option_versions(id, knowledge_version_id);


--
-- Name: option_prices option_prices_target_tier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.option_prices
    ADD CONSTRAINT option_prices_target_tier_id_fkey FOREIGN KEY (target_tier_id) REFERENCES public.membership_tiers(id);


--
-- Name: review_decisions review_decisions_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_decisions
    ADD CONSTRAINT review_decisions_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);


--
-- Name: review_decisions review_decisions_knowledge_version_id_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_decisions
    ADD CONSTRAINT review_decisions_knowledge_version_id_activity_id_fkey FOREIGN KEY (knowledge_version_id, activity_id) REFERENCES public.activity_knowledge_versions(id, activity_id);


--
-- Name: review_decisions review_decisions_source_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_decisions
    ADD CONSTRAINT review_decisions_source_binding_id_fkey FOREIGN KEY (source_binding_id) REFERENCES public.activity_source_bindings(id);


--
-- Name: review_decisions review_decisions_target_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_decisions
    ADD CONSTRAINT review_decisions_target_activity_id_fkey FOREIGN KEY (target_activity_id) REFERENCES public.activities(id);


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
-- Name: statusmatch_watches statusmatch_watches_source_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statusmatch_watches
    ADD CONSTRAINT statusmatch_watches_source_binding_id_fkey FOREIGN KEY (source_binding_id) REFERENCES public.activity_source_bindings(id);


--
-- PostgreSQL database dump complete
--

\unrestrict a6BdwgxphkLcaVoBKrAQZH4bQSnTuegXaqm4wuz9ZrYKHj3hfyqBzmMVmC9MCEM

