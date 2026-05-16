-- 013_recon_schema.sql
-- Schéma reconciliation Aircall ↔ UCC (additif).
-- Source : driveco-call-reconciliation full_run_export.zip

-- ===== Audit des imports =====
create table public.recon_runs (
  id                          uuid primary key default gen_random_uuid(),
  status                      text not null default 'pending_upload'
                              check (status in ('pending_upload','ready_to_run','running','importing','done','error')),
  triggered_by                text,
  started_at                  timestamptz,
  ended_at                    timestamptz,
  period_start                date,
  period_end                  date,
  uploaded_aircall_path       text,
  uploaded_ucc_path           text,
  output_dir                  text,
  metrics                     jsonb not null default '{}'::jsonb,
  error                       text,
  created_at                  timestamptz not null default now()
);
create index recon_runs_status_idx       on public.recon_runs (status);
create index recon_runs_started_at_idx   on public.recon_runs (started_at desc);

-- ===== Dimensions =====
create table public.recon_dim_agents (
  agent_key       text primary key,
  user_name       text,
  team            text,
  source_system   text,
  updated_at      timestamptz not null default now()
);

create table public.recon_dim_call_reasons (
  tag_reason_code            text primary key,
  tag_reason_raw             text,
  tag_reason_normalized      text,
  tag_main_category          text,
  tag_subcategory            text,
  tag_problem_category       text,
  tag_complexity_level       text,
  tag_call_outcome           text,
  tag_mapping_match_flag     text,
  updated_at                 timestamptz not null default now()
);

-- ===== Faits =====
create table public.recon_fact_harmonized_calls (
  interaction_id                  text primary key,
  interaction_start_utc           timestamptz,
  interaction_end_utc             timestamptz,
  interaction_date                date not null,
  market                          text,
  country_code                    text,
  flow_type                       text,
  reporting_owner                 text,
  resolved_by                     text,
  match_confidence_tier           text,
  match_rule_id                   text,
  match_confidence_score          numeric,
  ambiguity_flag                  boolean,
  source_systems_involved         text,
  aircall_segment_count           int,
  ucc_segment_count               int,
  aircall_call_id                 text,
  aircall_call_id_internal        text,
  aircall_preferred_line_role     text,
  front_bridge_match_flag         boolean,
  front_bridge_match_count        int,
  has_transfer                    boolean,
  has_overflow                    boolean,
  has_callback                    boolean,
  transfer_attempt_count          int,
  transfer_attempt_failed_flag    boolean,
  technical_ucc_number_seen       boolean,
  known_misrouting_flag           boolean,
  b2b_epc_flag                    boolean,
  call_deflector_flag             boolean,
  ring_reached_flag               boolean,
  main_kpi_eligible_flag          boolean,
  primary_customer_phone_normalized text,
  customer_phone_missing_flag     boolean,
  operating_model_version         text,
  final_answered_flag             boolean,
  total_waiting_time_sec          numeric,
  total_talk_time_sec             numeric,
  total_duration_sec              numeric,
  transfer_delay_sec              numeric,
  tags_raw_aircall                text,
  tags_raw_ucc                    text,
  tag_items_aircall               text,
  tag_items_ucc                   text,
  csat_eligible                   boolean,
  csat_available                  boolean,
  csat_source_system              text,
  csat_scope_note                 text,
  tag_customer_type               text,
  customer_type_code              text,
  customer_type_mapping_match_flag text,
  tag_station_raw                 text,
  tag_station_normalized          text,
  tag_station_quality_flag        text,
  station_ref                     text,
  station_zipcode                 text,
  station_ssd_name                text,
  station_aircall_tag_v1          text,
  station_aircall_tag_v2          text,
  station_cpo_epc                 text,
  station_group                   text,
  station_country                 text,
  station_mapping_match_flag      text,
  tag_reason_raw                  text,
  tag_reason_normalized           text,
  tag_reason_code                 text,
  tag_main_category               text,
  tag_subcategory                 text,
  tag_complexity_level            text,
  tag_problem_category            text,
  tag_call_outcome                text,
  outcome_code                    text,
  outcome_mapping_match_flag      text,
  call_success_flag               boolean,
  call_failed_flag                boolean,
  call_transfer_flag              boolean,
  call_callback_flag              boolean,
  tag_mapping_match_flag          text,
  tag_mapping_version             text,
  tag_quality_score               int,
  tag_callback_flag               boolean,
  tag_b2b_epc_flag                boolean,
  tag_active_bug_flag             boolean,
  source_run_id                   uuid references public.recon_runs(id) on delete set null,
  imported_at                     timestamptz not null default now()
);
create index recon_fhc_interaction_date_idx on public.recon_fact_harmonized_calls (interaction_date);
create index recon_fhc_aircall_internal_idx on public.recon_fact_harmonized_calls (aircall_call_id_internal);
create index recon_fhc_reporting_owner_idx  on public.recon_fact_harmonized_calls (reporting_owner);
create index recon_fhc_source_run_idx       on public.recon_fact_harmonized_calls (source_run_id);

create table public.recon_fact_daily_kpis (
  id                                          uuid primary key default gen_random_uuid(),
  interaction_date                            date not null,
  market                                      text,
  operating_model_version                     text,
  volume_global_assistance                    int,
  incoming_calls                              int,
  outgoing_calls                              int,
  answered_rate                               numeric,
  answered_rate_decrochable                   numeric,
  reporting_owner_ucc                         int,
  reporting_owner_driveco                     int,
  reporting_owner_ucc_driveco                 int,
  overflow_rate                               numeric,
  escalation_to_driveco_rate                  numeric,
  ivr_volume                                  int,
  deflector_volume                            int,
  b2b_epc_volume                              int,
  callback_tag_volume                         int,
  active_bug_tag_volume                       int,
  unmapped_reason_rate                        numeric,
  unmapped_station_rate                       numeric,
  unmapped_customer_type_rate                 numeric,
  unmapped_outcome_rate                       numeric,
  global_tag_enrichment_quality_score         numeric,
  probable_interactions                       int,
  unknown_interactions                        int,
  unknown_rate                                numeric,
  ambiguous_interactions                      int,
  certain_cross_tool_matches                  int,
  probable_cross_tool_matches                 int,
  front_bridge_matches                        int,
  unknown_case_volume                         int,
  known_misrouting_volume                     int,
  legacy_plus34_usage_volume                  int,
  source_run_id                               uuid references public.recon_runs(id) on delete set null,
  imported_at                                 timestamptz not null default now()
);
create index recon_fdk_date_idx        on public.recon_fact_daily_kpis (interaction_date);
create index recon_fdk_source_run_idx  on public.recon_fact_daily_kpis (source_run_id);

create table public.recon_fact_agent_performance (
  id                          uuid primary key default gen_random_uuid(),
  interaction_date            date not null,
  market                      text,
  source_system               text,
  team                        text,
  user_name                   text,
  segment_count               int,
  inbound_count               int,
  outbound_count              int,
  answered_count              int,
  answered_rate               numeric,
  talk_time_sec               numeric,
  waiting_time_sec            numeric,
  total_duration_sec          numeric,
  transfer_signal_count       int,
  overflow_signal_count       int,
  source_run_id               uuid references public.recon_runs(id) on delete set null,
  imported_at                 timestamptz not null default now()
);
create index recon_fap_date_idx        on public.recon_fact_agent_performance (interaction_date);
create index recon_fap_user_idx        on public.recon_fact_agent_performance (user_name);
create index recon_fap_source_run_idx  on public.recon_fact_agent_performance (source_run_id);

-- ===== Grants =====
grant select on
  public.recon_runs,
  public.recon_dim_agents, public.recon_dim_call_reasons,
  public.recon_fact_harmonized_calls,
  public.recon_fact_daily_kpis,
  public.recon_fact_agent_performance
to dashboard_reader;
