-- Convention: agent_id = '' représente le snapshot global quand scope = 'global'.
alter table public.daily_kpi_snapshot
    add column if not exists agent_id text not null default '',
    add column if not exists kb_compliance_rate numeric(5,1),
    add column if not exists warm_transfer_success_rate numeric(5,1);

do $$
begin
    if exists (
        select 1
        from information_schema.table_constraints
        where table_schema = 'public'
          and table_name = 'daily_kpi_snapshot'
          and constraint_type = 'PRIMARY KEY'
          and constraint_name = 'daily_kpi_snapshot_pkey'
    ) then
        alter table public.daily_kpi_snapshot drop constraint daily_kpi_snapshot_pkey;
    end if;
exception
    when undefined_object then
        null;
end $$;

alter table public.daily_kpi_snapshot
    add constraint daily_kpi_snapshot_pkey primary key (date, scope, agent_id);

create index if not exists idx_daily_kpi_snapshot_agent_id on public.daily_kpi_snapshot(agent_id);
create index if not exists idx_daily_kpi_snapshot_scope_date on public.daily_kpi_snapshot(scope, date desc);
create unique index if not exists idx_kb_gaps_detected_topic on public.kb_gaps(detected_on, topic);

create table if not exists public.anomaly_events (
    id text primary key,
    detected_on date not null,
    scope text not null,
    agent_id text not null default '',
    metric text not null,
    z_score numeric(8,3),
    current_value numeric(8,2),
    baseline_mean numeric(8,2),
    baseline_stddev numeric(8,2),
    representative_call_ids text[] not null default '{}',
    context jsonb not null default '{}'::jsonb,
    status text not null default 'new',
    created_at timestamptz not null default now()
);

create index if not exists idx_anomaly_events_detected_on on public.anomaly_events(detected_on desc);
create index if not exists idx_anomaly_events_scope_agent on public.anomaly_events(scope, agent_id);
