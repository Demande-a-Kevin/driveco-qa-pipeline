create table if not exists public.agent_best_practices (
    id text primary key,
    evaluation_id text not null references public.evaluations(id) on delete cascade,
    quote text not null,
    agent_id text,
    topic_code text
);

create index if not exists idx_agent_best_practices_agent_id on public.agent_best_practices(agent_id);

create or replace view public.v_voc_opportunities_ranked as
select
    description,
    type,
    frequency,
    severity,
    first_seen,
    last_seen,
    round(
        (
            frequency * (
                1.0 / greatest(
                    1.0,
                    (current_date - coalesce(last_seen, detected_on)) + 1
                )
            )
        )::numeric,
        2
    ) as opportunity_score,
    source_call_ids,
    status,
    tags
from public.voc_signals
where type in ('opportunity', 'product_idea', 'unmet_need')
order by opportunity_score desc, frequency desc, last_seen desc nulls last;

grant select on public.v_voc_opportunities_ranked to dashboard_reader;
