alter table public.llm_runs
    add column if not exists raw jsonb not null default '{}'::jsonb;

create table if not exists public.shadow_runs (
    id text primary key,
    call_id text not null references public.calls(id) on delete cascade,
    evaluation_id text references public.evaluations(id) on delete cascade,
    primary_model text not null,
    shadow_model text not null,
    primary_score numeric(4,1),
    shadow_score numeric(4,1),
    delta_score numeric(4,1),
    created_at timestamptz not null default now(),
    raw jsonb not null default '{}'::jsonb
);

create index if not exists idx_shadow_runs_call_id on public.shadow_runs(call_id);
create index if not exists idx_shadow_runs_created_at on public.shadow_runs(created_at desc);
