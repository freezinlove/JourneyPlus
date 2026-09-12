-- clean_0003 后的六项约束放松；不更改数据、列、外键或知识版本模型。
-- 执行前归档完整 schema；当前旧 Alembic 链不适用于此数据库。
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.option_prices DROP CONSTRAINT ck_price_availability;
-- 保留原有状态取值检查，只解除 UNAVAILABLE 与 amount 的绑定。
ALTER TABLE public.option_prices ADD CONSTRAINT ck_price_availability
  CHECK (availability IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN', 'CONFLICT'));
ALTER TABLE public.activity_knowledge_versions
  DROP CONSTRAINT activity_knowledge_versions_analysis_run_id_key;
ALTER TABLE public.activity_briefs DROP CONSTRAINT ck_brief_ready;
DROP TRIGGER immutable_activity_briefs ON public.activity_briefs;
DROP TRIGGER immutable_supplement ON public.activity_supplements;
DROP FUNCTION public.knowledge_guard_supplement();
ALTER TABLE public.agent_wait_goals DROP CONSTRAINT ck_wait_schema_version;
COMMIT;
