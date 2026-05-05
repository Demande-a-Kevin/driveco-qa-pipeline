-- 009_pipeline_config.sql
-- I1 (coverage %), I2 (phone lines), I3 (date range), I4 (focus)
create table public.pipeline_config (
  id              uuid primary key default gen_random_uuid(),
  version         int  not null,
  is_active       boolean not null default false,
  coverage_target_pct       numeric(5,2),
  phone_line_ids            text[]  not null default '{}',
  default_date_range_days   int     not null default 1,
  focus_note                text,
  created_at      timestamptz not null default now(),
  created_by      text,
  notes           text
);
create unique index pipeline_config_one_active
  on public.pipeline_config (is_active) where is_active;

-- I5 — rubric versionnée
create table public.rubric_versions (
  id              uuid primary key default gen_random_uuid(),
  version         int  not null unique,
  is_active       boolean not null default false,
  yaml_source     text not null,
  criteria        jsonb not null,
  created_at      timestamptz not null default now(),
  created_by      text,
  notes           text
);
create unique index rubric_versions_one_active
  on public.rubric_versions (is_active) where is_active;

-- I6 — override prompt (hybride P3)
create table public.prompt_overrides (
  id              uuid primary key default gen_random_uuid(),
  is_active       boolean not null default false,
  baseline_sha    text,
  override_text   text not null,
  diff_summary    text,
  active_until    timestamptz,
  created_at      timestamptz not null default now(),
  created_by      text,
  notes           text
);
create unique index prompt_overrides_one_active
  on public.prompt_overrides (is_active) where is_active;

-- Lecture pour dashboard_reader (rôle déjà créé en 006_views.sql)
grant select on public.pipeline_config, public.rubric_versions, public.prompt_overrides
  to dashboard_reader;
