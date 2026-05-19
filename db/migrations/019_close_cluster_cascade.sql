-- 019_close_cluster_cascade.sql
-- Quand un cluster passe en 'closed', cascade sur ses kb_gaps membres

create or replace function public.kb_gap_cluster_cascade_close() returns trigger
language plpgsql
as $$
begin
  if NEW.status = 'closed' and (OLD.status is null or OLD.status != 'closed') then
    update public.kb_gaps 
    set status = 'closed', updated_by = NEW.updated_by
    where id = any(NEW.member_gap_ids) and status != 'closed';
  end if;
  return NEW;
end$$;

create trigger trg_kb_gap_cluster_cascade_close
  after update on public.kb_gap_clusters
  for each row execute function public.kb_gap_cluster_cascade_close();
