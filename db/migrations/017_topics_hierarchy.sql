-- 017_topics_hierarchy.sql
-- Vue agrégée pour /qa/topics : hiérarchie Codex (main → sub → problem → complexity → outcome)
-- par jour × reporting_owner. Sert le treetable expansible (fetch all + groupBy client).

create or replace view public.v_topics_hierarchy_daily as
select
  fh.interaction_date,
  coalesce(fh.reporting_owner, 'UNKNOWN') as reporting_owner,
  fh.tag_main_category,
  fh.tag_subcategory,
  fh.tag_problem_category,
  fh.tag_complexity_level,
  fh.tag_call_outcome,
  count(*) as mentions,
  count(*) filter (where fh.call_success_flag) as success_count,
  count(*) filter (where fh.call_failed_flag) as fail_count,
  count(*) filter (where fh.call_transfer_flag) as transfer_count
from public.recon_fact_harmonized_calls fh
where fh.tag_main_category is not null
group by 1, 2, 3, 4, 5, 6, 7;

grant select on public.v_topics_hierarchy_daily to dashboard_reader;
