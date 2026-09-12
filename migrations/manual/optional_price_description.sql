-- clean_0003 数据库的小范围调整：价格说明省略时使用空字符串。
-- 不改已有内容，不新增约束；当前工作区的旧 Alembic 链不用于执行此调整。
-- 可重复执行。此 SQL 不修改 alembic_version。
-- 撤销方式：ALTER TABLE public.option_prices ALTER COLUMN raw_text DROP DEFAULT;
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.option_prices ALTER COLUMN raw_text SET DEFAULT '';
COMMIT;
