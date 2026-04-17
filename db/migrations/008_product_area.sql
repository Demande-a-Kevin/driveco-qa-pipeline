alter table public.calls
    add column if not exists caller_hash text;

create index if not exists idx_calls_caller_hash on public.calls(caller_hash);

alter table public.topic_mentions
    add column if not exists product_area text not null default 'other';

alter table public.evaluations
    add column if not exists resolution_status text;

alter table public.daily_kpi_snapshot
    add column if not exists fcr_rate numeric(5,1);

create or replace view public.v_kpi_trend_daily as
select
    date,
    scope,
    agent_id,
    total_calls,
    pickup_rate,
    abandon_rate,
    avg_handle_time,
    repeat_caller_rate,
    avg_soft_score,
    kb_compliance_rate,
    warm_transfer_success_rate,
    coverage_pct,
    fcr_rate,
    computed_at
from public.daily_kpi_snapshot
where date >= current_date - interval '90 days';

grant select on public.v_kpi_trend_daily to dashboard_reader;
