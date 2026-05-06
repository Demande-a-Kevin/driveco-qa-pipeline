-- 010_findings_workflow.sql
alter table public.kb_gaps
  add column if not exists assignee   text,
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists updated_by text;

alter table public.voc_signals
  add column if not exists assignee   text,
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists updated_by text;

alter table public.anomaly_events
  add column if not exists assignee   text,
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists updated_by text;

create table public.finding_notes (
  id              uuid primary key default gen_random_uuid(),
  finding_type    text not null check (finding_type in ('kb_gap','voc_signal','anomaly_event')),
  finding_id      text not null,
  body            text not null,
  created_at      timestamptz not null default now(),
  created_by      text
);
create index finding_notes_lookup on public.finding_notes (finding_type, finding_id);

create or replace function public.touch_updated_at() returns trigger as $$
begin new.updated_at := now(); return new; end;
$$ language plpgsql;

drop trigger if exists trg_kb_gaps_touch        on public.kb_gaps;
drop trigger if exists trg_voc_signals_touch    on public.voc_signals;
drop trigger if exists trg_anomaly_events_touch on public.anomaly_events;

create trigger trg_kb_gaps_touch         before update on public.kb_gaps
  for each row execute function public.touch_updated_at();
create trigger trg_voc_signals_touch     before update on public.voc_signals
  for each row execute function public.touch_updated_at();
create trigger trg_anomaly_events_touch  before update on public.anomaly_events
  for each row execute function public.touch_updated_at();

grant select on public.finding_notes to dashboard_reader;
