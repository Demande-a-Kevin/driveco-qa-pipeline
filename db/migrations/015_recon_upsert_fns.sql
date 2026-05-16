-- 015_recon_upsert_fns.sql
-- Helper PL/pgSQL pour DELETE atomique avant un bulk INSERT côté Python.
-- L'orchestration (INSERT) reste côté Python (recon_import.py) via COPY.

create or replace function public.recon_delete_fact_period(
  table_name text,
  period_start date,
  period_end date
) returns int
language plpgsql
as $$
declare deleted_count int;
begin
  if table_name not in ('recon_fact_harmonized_calls',
                        'recon_fact_daily_kpis',
                        'recon_fact_agent_performance') then
    raise exception 'unauthorized table_name: %', table_name;
  end if;
  execute format(
    'delete from public.%I where interaction_date between $1 and $2',
    table_name
  ) using period_start, period_end;
  get diagnostics deleted_count = row_count;
  return deleted_count;
end$$;
