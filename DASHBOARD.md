# Dashboard

## Reco phase 1

- base de données : Supabase Postgres
- BI : Metabase self-hosted en Docker
- source à connecter : les vues SQL du repo, pas les tables brutes

## Migrations à appliquer

- `db/migrations/001_init.sql`
- `db/migrations/003_voc.sql`
- `db/migrations/004_metrics_agent.sql`
- `db/migrations/005_reliability.sql`
- `db/migrations/006_views.sql`

## Variables utiles

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `SUPABASE_DASHBOARD_ANON_KEY` pour la lecture dashboard si tu décides de l’exposer plus tard
- rôle SQL : `dashboard_reader`

## Dashboards cibles

1. `Overview`
   - vue principale : `v_kpi_trend_daily`
   - query : `select * from public.v_kpi_trend_daily where scope = 'global' order by date desc;`

2. `Agents`
   - vue principale : `v_agent_scorecard_30d`
   - query : `select * from public.v_agent_scorecard_30d order by date desc, total_calls desc;`

3. `KB Gaps`
   - vue principale : `v_kb_gaps_active`
   - query : `select * from public.v_kb_gaps_active order by detected_on desc, frequency desc;`

4. `Anomalies`
   - vue principale : `v_anomaly_feed`
   - query : `select * from public.v_anomaly_feed order by created_at desc;`

5. `Reliability`
   - source : `llm_runs`
   - query : `select started_at, status, raw->'reliability_metrics' as reliability_metrics from public.llm_runs where mode = 'reliability' order by started_at desc;`

6. `Runs Health`
   - source : `llm_runs`
   - query : `select id, started_at, ended_at, mode, model, calls_count, errors_count, status from public.llm_runs order by started_at desc limit 100;`

## Onglets VoC

1. `Voix du client`
   - `select * from public.v_voc_topics_trend_28d order by day desc, mentions desc;`
   - `select * from public.v_voc_entity_sentiment_30d order by day desc, mentions desc;`
   - `select * from public.v_voc_verbatims_pinned order by started_at desc;`

2. `Risques & opportunités`
   - `select * from public.v_voc_weak_signals_active order by frequency desc, detected_on desc;`
   - `select * from public.v_voc_churn_risk_feed_7d order by started_at desc;`
   - `select * from public.v_voc_opportunities_ranked order by opportunity_score desc;`
   - `select * from public.v_voc_competitors_watch order by week_start desc, mentions desc;`

## Metabase Docker

```bash
docker run -d \
  --name metabase \
  -p 3000:3000 \
  metabase/metabase:latest
```

Puis connecter Metabase à Supabase en lecture sur les vues.

## Endpoint santé

Le repo expose un serveur local simple :

```bash
.venv/bin/python health_server.py
```

URL :

```text
GET http://localhost:8788/health
```
