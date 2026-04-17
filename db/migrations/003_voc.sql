create table if not exists public.voc_taxonomy (
    id text primary key,
    axis text not null,
    code text unique not null,
    label text not null,
    category text,
    active boolean not null default true,
    version text not null
);

create table if not exists public.voc_extracts (
    evaluation_id text primary key references public.evaluations(id) on delete cascade,
    effort_score smallint,
    satisfaction_signal text,
    churn_risk_signal text,
    expansion_signal boolean default false,
    taxonomy_version text,
    raw jsonb not null default '{}'::jsonb
);

create table if not exists public.topic_mentions (
    id text primary key,
    evaluation_id text not null references public.evaluations(id) on delete cascade,
    topic_code text not null,
    sentiment text,
    severity numeric(3,1),
    quote text,
    detected_at timestamptz not null default now()
);

create table if not exists public.entity_perceptions (
    id text primary key,
    evaluation_id text not null references public.evaluations(id) on delete cascade,
    entity_code text not null,
    aspect_code text not null,
    sentiment text,
    quote text
);

create table if not exists public.verbatims (
    id text primary key,
    evaluation_id text not null references public.evaluations(id) on delete cascade,
    quote text not null,
    timestamp_s integer,
    speaker text,
    topic_code text,
    sentiment text,
    pinned boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists public.competitor_mentions (
    id text primary key,
    evaluation_id text not null references public.evaluations(id) on delete cascade,
    competitor_name text not null,
    context_quote text,
    sentiment text
);

create table if not exists public.voc_signals (
    id text primary key,
    type text not null,
    detected_on date not null,
    description text not null,
    source_call_ids text[] not null default '{}',
    frequency integer not null default 1,
    severity numeric(3,1),
    status text not null default 'new',
    owner text,
    first_seen date,
    last_seen date,
    tags text[] not null default '{}'
);

create index if not exists idx_topic_mentions_topic_code on public.topic_mentions(topic_code);
create index if not exists idx_entity_perceptions_entity_code on public.entity_perceptions(entity_code);
create index if not exists idx_verbatims_created_at on public.verbatims(created_at);
create index if not exists idx_voc_signals_detected_on on public.voc_signals(detected_on);
