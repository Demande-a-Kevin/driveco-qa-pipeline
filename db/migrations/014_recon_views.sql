-- 014_recon_views.sql
-- Vues jointes pour exposer recon_* aux dashboards (toggle UCC/DRIVECO, drill agent, KPIs téléphoniques).

create or replace view public.v_calls_enriched as
select
  c.id, c.aircall_id, c.started_at, c.direction, c.duration_s,
  c.scope, c.answered, c.agent_id,
  fh.interaction_id, fh.reporting_owner, fh.resolved_by, fh.flow_type,
  fh.tag_reason_code, fh.tag_main_category, fh.tag_subcategory,
  fh.tag_problem_category, fh.tag_complexity_level, fh.tag_call_outcome,
  fh.tag_customer_type, fh.station_ref, fh.station_country,
  fh.has_transfer, fh.has_overflow,
  fh.call_success_flag, fh.tag_quality_score
from public.calls c
left join public.recon_fact_harmonized_calls fh
  on c.aircall_id = fh.aircall_call_id_internal;

create or replace view public.v_agent_perf_combined as
select
  ap.interaction_date, ap.team, ap.user_name,
  ap.segment_count, ap.inbound_count, ap.outbound_count,
  ap.answered_count, ap.answered_rate,
  ap.talk_time_sec, ap.waiting_time_sec, ap.total_duration_sec,
  ap.transfer_signal_count, ap.overflow_signal_count,
  eq.eval_count, eq.avg_score
from public.recon_fact_agent_performance ap
left join (
  select
    date_trunc('day', c.started_at)::date as d,
    a.name as agent_name,
    count(e.id) as eval_count,
    avg(e.score_global) as avg_score
  from public.evaluations e
  join public.calls c on c.id = e.call_id
  join public.agents a on a.id = c.agent_id
  group by 1, 2
) eq on eq.d = ap.interaction_date and eq.agent_name = ap.user_name;

create or replace view public.v_phoning_daily as
select
  interaction_date, market,
  volume_global_assistance, incoming_calls, outgoing_calls,
  answered_rate, answered_rate_decrochable,
  reporting_owner_ucc, reporting_owner_driveco, reporting_owner_ucc_driveco,
  overflow_rate, escalation_to_driveco_rate,
  ivr_volume, deflector_volume, b2b_epc_volume,
  callback_tag_volume, active_bug_tag_volume,
  global_tag_enrichment_quality_score,
  unmapped_reason_rate, unmapped_station_rate, unmapped_outcome_rate
from public.recon_fact_daily_kpis;

grant select on
  public.v_calls_enriched,
  public.v_agent_perf_combined,
  public.v_phoning_daily
to dashboard_reader;
