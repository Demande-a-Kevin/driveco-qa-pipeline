-- 012_activation_rpcs.sql
-- Fonctions RPC PL/pgSQL pour activation transactionnelle des configs versionnées.
-- Garantissent l'unicité du is_active sans race condition.

create or replace function public.activate_pipeline_config(payload jsonb)
returns public.pipeline_config
language plpgsql
security definer
as $$
declare
  new_row public.pipeline_config;
begin
  update public.pipeline_config set is_active = false where is_active;
  insert into public.pipeline_config (
    version, is_active, coverage_target_pct, phone_line_ids,
    default_date_range_days, focus_note, created_by, notes
  ) values (
    (payload->>'version')::int,
    true,
    nullif(payload->>'coverage_target_pct','')::numeric,
    coalesce(array(select jsonb_array_elements_text(payload->'phone_line_ids')), '{}'::text[]),
    coalesce((payload->>'default_date_range_days')::int, 1),
    nullif(payload->>'focus_note',''),
    payload->>'created_by',
    payload->>'notes'
  ) returning * into new_row;
  return new_row;
end$$;

create or replace function public.activate_rubric(rubric_id uuid)
returns public.rubric_versions
language plpgsql
as $$
declare new_row public.rubric_versions;
begin
  update public.rubric_versions set is_active = (id = rubric_id);
  select * into new_row from public.rubric_versions where id = rubric_id;
  return new_row;
end$$;

create or replace function public.activate_prompt_override(override_id uuid)
returns public.prompt_overrides
language plpgsql
as $$
declare new_row public.prompt_overrides;
begin
  update public.prompt_overrides set is_active = (id = override_id);
  select * into new_row from public.prompt_overrides where id = override_id;
  return new_row;
end$$;
