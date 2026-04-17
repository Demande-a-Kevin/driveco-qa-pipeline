create or replace view public.v_agent_scorecard_30d as
select
    s.date,
    s.agent_id,
    a.name as agent_name,
    a.team,
    s.total_calls,
    s.pickup_rate,
    s.abandon_rate,
    s.avg_handle_time,
    s.repeat_caller_rate,
    s.avg_soft_score,
    s.kb_compliance_rate,
    s.warm_transfer_success_rate,
    s.coverage_pct
from public.daily_kpi_snapshot s
left join public.agents a on a.id = s.agent_id
where s.scope = 'agent'
  and s.date >= current_date - interval '30 days';

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
    computed_at
from public.daily_kpi_snapshot
where date >= current_date - interval '90 days';

create or replace view public.v_top_issues_30d as
select
    i.description as issue_label,
    count(*) as occurrences,
    array_agg(distinct e.call_id) filter (where e.call_id is not null) as example_call_ids,
    max(c.started_at) as last_seen_at
from public.issues i
join public.evaluations e on e.id = i.evaluation_id
left join public.calls c on c.id = e.call_id
where c.started_at >= now() - interval '30 days'
group by i.description
order by occurrences desc, last_seen_at desc;

create or replace view public.v_kb_gaps_active as
select
    detected_on,
    topic,
    frequency,
    example_call_ids,
    status
from public.kb_gaps
where status <> 'closed'
order by detected_on desc, frequency desc;

create or replace view public.v_anomaly_feed as
select
    ae.detected_on,
    ae.scope,
    ae.agent_id,
    a.name as agent_name,
    ae.metric,
    ae.z_score,
    ae.current_value,
    ae.baseline_mean,
    ae.baseline_stddev,
    ae.representative_call_ids,
    ae.status,
    ae.created_at
from public.anomaly_events ae
left join public.agents a on a.id = ae.agent_id
order by ae.created_at desc;

create or replace view public.v_voc_topics_trend_28d as
select
    c.started_at::date as day,
    tm.topic_code,
    count(*) as mentions,
    round(avg(case tm.sentiment
        when 'très_négatif' then -2
        when 'négatif' then -1
        when 'neutre' then 0
        when 'positif' then 1
        when 'très_positif' then 2
        else 0 end)::numeric, 2) as avg_sentiment
from public.topic_mentions tm
join public.evaluations e on e.id = tm.evaluation_id
join public.calls c on c.id = e.call_id
where c.started_at >= now() - interval '28 days'
group by c.started_at::date, tm.topic_code
order by day desc, mentions desc;

create or replace view public.v_voc_entity_sentiment_30d as
select
    c.started_at::date as day,
    ep.entity_code,
    count(*) as mentions,
    round(avg(case ep.sentiment
        when 'très_négatif' then -2
        when 'négatif' then -1
        when 'neutre' then 0
        when 'positif' then 1
        when 'très_positif' then 2
        else 0 end)::numeric, 2) as avg_sentiment
from public.entity_perceptions ep
join public.evaluations e on e.id = ep.evaluation_id
join public.calls c on c.id = e.call_id
where c.started_at >= now() - interval '30 days'
group by c.started_at::date, ep.entity_code
order by day desc, mentions desc;

create or replace view public.v_voc_weak_signals_active as
select
    detected_on,
    description,
    frequency,
    severity,
    source_call_ids,
    status,
    tags
from public.voc_signals
where type = 'weak_signal'
  and status <> 'closed'
order by frequency desc, severity desc nulls last, detected_on desc;

create or replace view public.v_voc_verbatims_pinned as
select
    v.id,
    v.quote,
    v.timestamp_s,
    v.speaker,
    v.topic_code,
    v.sentiment,
    e.call_id,
    c.started_at
from public.verbatims v
join public.evaluations e on e.id = v.evaluation_id
join public.calls c on c.id = e.call_id
where v.pinned = true
order by c.started_at desc;

create or replace view public.v_voc_churn_risk_feed_7d as
select
    c.started_at,
    e.call_id,
    a.name as agent_name,
    vx.churn_risk_signal,
    vx.satisfaction_signal,
    (
        select v.quote
        from public.verbatims v
        where v.evaluation_id = vx.evaluation_id
        order by v.created_at asc
        limit 1
    ) as quote
from public.voc_extracts vx
join public.evaluations e on e.id = vx.evaluation_id
join public.calls c on c.id = e.call_id
left join public.agents a on a.id = c.agent_id
where c.started_at >= now() - interval '7 days'
  and vx.churn_risk_signal in ('modéré', 'élevé')
order by c.started_at desc;

create or replace view public.v_voc_opportunities_ranked as
select
    description,
    frequency,
    severity,
    first_seen,
    last_seen,
    (frequency * greatest(1, 30 - (current_date - coalesce(last_seen, detected_on))))::numeric as opportunity_score,
    source_call_ids,
    status
from public.voc_signals
where type = 'opportunity'
order by opportunity_score desc, frequency desc, last_seen desc nulls last;

create or replace view public.v_voc_competitors_watch as
select
    date_trunc('week', c.started_at)::date as week_start,
    cm.competitor_name,
    count(*) as mentions,
    array_agg(distinct e.call_id) filter (where e.call_id is not null) as example_call_ids
from public.competitor_mentions cm
join public.evaluations e on e.id = cm.evaluation_id
join public.calls c on c.id = e.call_id
where c.started_at >= now() - interval '90 days'
group by week_start, cm.competitor_name
order by week_start desc, mentions desc;

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'dashboard_reader') then
        create role dashboard_reader nologin;
    end if;
end $$;

grant usage on schema public to dashboard_reader;
grant select on
    public.v_agent_scorecard_30d,
    public.v_kpi_trend_daily,
    public.v_top_issues_30d,
    public.v_kb_gaps_active,
    public.v_anomaly_feed,
    public.v_voc_topics_trend_28d,
    public.v_voc_entity_sentiment_30d,
    public.v_voc_weak_signals_active,
    public.v_voc_verbatims_pinned,
    public.v_voc_churn_risk_feed_7d,
    public.v_voc_opportunities_ranked,
    public.v_voc_competitors_watch
to dashboard_reader;
