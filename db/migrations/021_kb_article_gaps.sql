-- F-3 : KB article gaps detection (true missing KB articles, distinct from F-1 coaching patterns)
-- Applied via Supabase MCP on 2026-05-20 to project QA-UCC (fnnxejwvcblwvgruuvbq)
-- Note: unanswered_questions[] stored inside evaluations.raw jsonb (no ALTER needed)
-- Note: calls PK is `id` text (not call_id), llm_runs.id is text (not uuid)

create table if not exists public.call_unanswered_questions (
  id              bigserial primary key,
  call_id         text not null references public.calls(id) on delete cascade,
  question_text   text not null,
  question_hash   text not null,
  raised_at       timestamptz not null,
  llm_run_id      text references public.llm_runs(id),
  inserted_at     timestamptz not null default now()
);
create index if not exists idx_call_unanswered_questions_hash on public.call_unanswered_questions (question_hash);
create index if not exists idx_call_unanswered_questions_raised_at on public.call_unanswered_questions (raised_at desc);

create table if not exists public.kb_articles (
  notion_page_id      text primary key,
  title               text not null,
  body_md             text not null,
  url                 text not null,
  embedding           vector(768),
  last_edited_notion  timestamptz,
  synced_at           timestamptz not null default now()
);
create index if not exists idx_kb_articles_embedding on public.kb_articles using ivfflat (embedding vector_cosine_ops) with (lists = 50);

create table if not exists public.unanswered_question_embeddings (
  question_hash text primary key,
  embedding     vector(768) not null,
  computed_at   timestamptz not null default now()
);

create table if not exists public.kb_article_gap_clusters (
  id                          uuid primary key default gen_random_uuid(),
  label                       text not null,
  member_question_ids         bigint[] not null,
  total_frequency             int not null,
  representative_question_id  bigint,
  status                      text not null default 'missing'
    check (status in ('missing','partial','exists','closed')),
  matched_article_id          text references public.kb_articles(notion_page_id),
  match_similarity            numeric(4,3),
  assignee                    text,
  notes                       text,
  computed_at                 timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  updated_by                  text
);

create or replace function public.touch_kb_article_gap_clusters()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

drop trigger if exists trg_kb_article_gap_clusters_touch on public.kb_article_gap_clusters;
create trigger trg_kb_article_gap_clusters_touch
  before update on public.kb_article_gap_clusters
  for each row execute function public.touch_kb_article_gap_clusters();

create table if not exists public.kb_article_gap_drafts (
  id                uuid primary key default gen_random_uuid(),
  cluster_id        uuid not null references public.kb_article_gap_clusters(id) on delete cascade,
  format            text not null check (format in ('coaching','article_kb','faq')),
  content_markdown  text not null,
  generated_by      text not null,
  generated_at      timestamptz not null default now(),
  status            text not null default 'draft' check (status in ('draft','approved','published')),
  published_at      timestamptz,
  notion_page_id    text,
  edited_by         text,
  edited_at         timestamptz
);
create index if not exists idx_kb_article_gap_drafts_cluster_id on public.kb_article_gap_drafts (cluster_id);

create or replace view public.v_kb_article_gap_clusters_active as
  select c.*,
         q.question_text as representative_question,
         array_length(c.member_question_ids, 1) as member_count
  from public.kb_article_gap_clusters c
  left join public.call_unanswered_questions q on q.id = c.representative_question_id
  where c.status != 'closed'
  order by c.total_frequency desc;

grant select on public.kb_articles to dashboard_reader;
grant select on public.call_unanswered_questions to dashboard_reader;
grant select on public.kb_article_gap_clusters to dashboard_reader;
grant select on public.kb_article_gap_drafts to dashboard_reader;
grant select on public.v_kb_article_gap_clusters_active to dashboard_reader;
