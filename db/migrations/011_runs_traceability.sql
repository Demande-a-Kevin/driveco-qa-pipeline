-- 011_runs_traceability.sql
alter table public.llm_runs
  add column if not exists trigger_source text not null default 'cron'
    check (trigger_source in ('cron','manual','webhook')),
  add column if not exists triggered_by   text,
  add column if not exists params         jsonb not null default '{}'::jsonb,
  add column if not exists logs_excerpt   text,
  add column if not exists rubric_version_id   uuid references public.rubric_versions(id),
  add column if not exists prompt_override_id  uuid references public.prompt_overrides(id),
  add column if not exists pipeline_config_id  uuid references public.pipeline_config(id);

create or replace view public.v_runs_recent as
select
  r.id, r.started_at, r.ended_at, r.mode, r.model,
  r.calls_count, r.errors_count, r.status, r.trigger_source, r.triggered_by,
  r.params, r.logs_excerpt,
  rv.version as rubric_version,
  po.id is not null as had_prompt_override
from public.llm_runs r
left join public.rubric_versions  rv on rv.id = r.rubric_version_id
left join public.prompt_overrides po on po.id = r.prompt_override_id
order by r.started_at desc
limit 200;

grant select on public.v_runs_recent to dashboard_reader;
