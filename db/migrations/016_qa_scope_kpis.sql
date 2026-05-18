-- 016_qa_scope_kpis.sql
-- Vue scope-aware pour overview /qa : coverage + soft score par jour × reporting_owner.
-- NULL reporting_owner ('UNKNOWN') = appels QA non encore réconciliés via /data.

create or replace view public.v_qa_scope_kpis as
select
  c.started_at::date as day,
  coalesce(fh.reporting_owner, 'UNKNOWN') as reporting_owner,
  count(distinct c.id) as total_calls,
  count(distinct e.id) as evaluated_calls,
  avg(e.score_global) filter (where e.score_global is not null) as avg_soft_score
from public.calls c
left join public.recon_fact_harmonized_calls fh
  on c.aircall_id = fh.aircall_call_id_internal
left join public.evaluations e on e.call_id = c.id
group by 1, 2;

grant select on public.v_qa_scope_kpis to dashboard_reader;
