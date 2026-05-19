-- 018_kb_gap_clusters.sql
-- Pré-requis : extension pgvector (déjà activée le 2026-05-18)

create extension if not exists vector;

create table public.kb_gap_embeddings (
  kb_gap_id   bigint primary key references public.kb_gaps(id) on delete cascade,
  embedding   vector(768) not null,
  topic_hash  text not null,
  computed_at timestamptz not null default now()
);
create index kb_gap_embeddings_embedding_idx 
  on public.kb_gap_embeddings using ivfflat (embedding vector_cosine_ops) with (lists = 10);

create table public.kb_gap_clusters (
  id                      uuid primary key default gen_random_uuid(),
  label                   text not null,
  member_gap_ids          bigint[] not null,
  total_frequency         int not null default 0,
  representative_gap_id   bigint references public.kb_gaps(id) on delete set null,
  status                  text not null default 'new' 
                          check (status in ('new', 'in_progress', 'closed')),
  assignee                text,
  notes                   text,
  computed_at             timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  updated_by              text
);
create index kb_gap_clusters_freq_idx   on public.kb_gap_clusters (total_frequency desc);
create index kb_gap_clusters_status_idx on public.kb_gap_clusters (status);

create trigger trg_kb_gap_clusters_touch 
  before update on public.kb_gap_clusters
  for each row execute function public.touch_updated_at();

create or replace view public.v_kb_gap_clusters_active as
select c.*, 
       (select topic from kb_gaps where id = c.representative_gap_id) as representative_topic,
       array_length(member_gap_ids, 1) as member_count
from public.kb_gap_clusters c
where c.status != 'closed'
order by c.total_frequency desc;

grant select on 
  public.kb_gap_embeddings,
  public.kb_gap_clusters,
  public.v_kb_gap_clusters_active
to dashboard_reader;
