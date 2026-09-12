-- 撤销 relax_workflow_constraints.sql；不修改业务数据。
-- 新数据若已不满足旧约束，整个事务失败回滚，不删除或篡改数据。
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.option_prices DROP CONSTRAINT ck_price_availability;
ALTER TABLE public.option_prices ADD CONSTRAINT ck_price_availability
  CHECK (availability IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN', 'CONFLICT')
    AND (availability <> 'UNAVAILABLE' OR amount IS NULL));
ALTER TABLE public.activity_knowledge_versions
  ADD CONSTRAINT activity_knowledge_versions_analysis_run_id_key UNIQUE (analysis_run_id);
ALTER TABLE public.activity_briefs ADD CONSTRAINT ck_brief_ready CHECK (status = 'READY');
CREATE TRIGGER immutable_activity_briefs BEFORE INSERT OR UPDATE OR DELETE
  ON public.activity_briefs FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_child();
CREATE FUNCTION public.knowledge_guard_supplement() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'article supplements are immutable' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.activity_knowledge_versions
    WHERE id=NEW.knowledge_version_id AND status='PUBLISHED') THEN
    RAISE EXCEPTION 'supplements require published knowledge' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_supplement BEFORE INSERT OR UPDATE OR DELETE
  ON public.activity_supplements FOR EACH ROW EXECUTE FUNCTION public.knowledge_guard_supplement();
ALTER TABLE public.agent_wait_goals ADD CONSTRAINT ck_wait_schema_version
  CHECK (conditions_schema_version = 3);
COMMIT;
