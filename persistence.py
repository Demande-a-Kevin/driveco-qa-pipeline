from __future__ import annotations

import json
import logging
import re
from hashlib import sha256
from datetime import datetime, timezone
from typing import Any

import call_classifier
import config
import rubric
import voc_taxonomy
from rapidfuzz import fuzz

try:
    from supabase import Client, create_client
    SUPABASE_AVAILABLE = True
except ImportError:  # pragma: no cover - dépendance optionnelle au runtime
    Client = Any  # type: ignore[assignment]
    SUPABASE_AVAILABLE = False


log = logging.getLogger(__name__)
_CLIENT: Client | None = None
_WARNED_DISABLED = False
_VOC_TAXONOMY_SEEDED = False
_SCHEMA_SUPPORT_CACHE: dict[tuple[str, str], bool] = {}


def is_enabled() -> bool:
    return bool(SUPABASE_AVAILABLE and config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _warn_disabled_once() -> None:
    global _WARNED_DISABLED
    if _WARNED_DISABLED:
        return
    if not SUPABASE_AVAILABLE:
        log.info("[persistence] Supabase désactivé: dépendance `supabase` absente")
    elif not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        log.info("[persistence] Supabase désactivé: SUPABASE_URL / SUPABASE_SERVICE_KEY absents")
    _WARNED_DISABLED = True


def client() -> Client | None:
    global _CLIENT
    if not is_enabled():
        _warn_disabled_once()
        return None
    if _CLIENT is None:
        _CLIENT = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _CLIENT


def _seed_voc_taxonomy_once() -> None:
    global _VOC_TAXONOMY_SEEDED
    if _VOC_TAXONOMY_SEEDED:
        return
    supa = client()
    if supa is None:
        return
    rows = []
    for axis in ("topics", "entities", "aspects"):
        for item in voc_taxonomy.axis_items(axis):
            rows.append(
                {
                    "id": f"{axis}:{item['code']}",
                    "axis": axis,
                    "code": item["code"],
                    "label": item.get("label") or item["code"],
                    "category": axis,
                    "active": True,
                    "version": voc_taxonomy.taxonomy_version(),
                }
            )
    if rows and _execute_upsert("voc_taxonomy", rows, on_conflict="code"):
        _VOC_TAXONOMY_SEEDED = True


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return normalized.strip("-") or "unknown"


def canonical_call_id(call: dict) -> str | None:
    value = call.get("call_id_internal") or call.get("call_id")
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def canonical_aircall_id(call: dict) -> str | None:
    value = call.get("call_id") or call.get("call_id_internal")
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def canonical_agent_id(call: dict) -> str | None:
    user_id = call.get("user_id")
    if user_id is not None and str(user_id).strip():
        return f"aircall:{user_id}"
    user_name = str(call.get("user_name") or "").strip()
    if user_name:
        return f"name:{_slug(user_name)}"
    return None


def canonical_caller_hash(call: dict) -> str | None:
    phone = str(call.get("phone_e164") or call.get("from_number") or call.get("customer_number") or "").strip()
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    normalized = f"+{digits}"
    return sha256(normalized.encode("utf-8")).hexdigest()[:12]


def build_llm_run_id(mode: str, target_date: datetime) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{mode}:{target_date.strftime('%Y-%m-%d')}:{stamp}"


def _iso_from_unix(ts: Any) -> str | None:
    try:
        numeric = int(ts)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _scope_from_call(call: dict) -> str:
    return call_classifier.get_quality_scope(call.get("classified_type")) or "other"


def _is_transferred(call: dict) -> bool:
    return call.get("classified_type") in {"warm_transfer", "ucc_transfer_handled", "ucc_transfer_missed"}


def build_diarization(transcript: str) -> list[dict]:
    rows = []
    for line in str(transcript or "").splitlines():
        text = line.strip()
        if not text:
            continue
        match = re.match(r"^\[(Agent|Client)\]\s*(.*)$", text)
        if match:
            speaker, content = match.groups()
            rows.append({"speaker": speaker.lower(), "text": content.strip()})
        else:
            rows.append({"speaker": "unknown", "text": text})
    return rows


def _model_version(model_name: str | None) -> str | None:
    text = str(model_name or "").strip()
    if not text:
        return None
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _execute_upsert(table: str, payload: dict | list[dict], on_conflict: str) -> bool:
    supa = client()
    if supa is None:
        return False
    try:
        supa.table(table).upsert(payload, on_conflict=on_conflict).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("[persistence] upsert %s échoué: %s", table, exc)
        return False


def _supports_column(table: str, column: str) -> bool:
    cache_key = (table, column)
    if cache_key in _SCHEMA_SUPPORT_CACHE:
        return _SCHEMA_SUPPORT_CACHE[cache_key]
    supa = client()
    if supa is None:
        _SCHEMA_SUPPORT_CACHE[cache_key] = False
        return False
    try:
        supa.table(table).select(column).limit(1).execute()
        _SCHEMA_SUPPORT_CACHE[cache_key] = True
    except Exception:
        _SCHEMA_SUPPORT_CACHE[cache_key] = False
    return _SCHEMA_SUPPORT_CACHE[cache_key]


def _table_exists(table: str) -> bool:
    return _supports_column(table, "id")


def _execute_delete(table: str, **filters) -> bool:
    supa = client()
    if supa is None:
        return False
    try:
        query = supa.table(table).delete()
        for key, value in filters.items():
            query = query.eq(key, value)
        query.execute()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("[persistence] delete %s échoué: %s", table, exc)
        return False


def _call_rgpd_opt_out(call: dict) -> bool:
    for key in ("rgpd_opt_out", "opt_out", "privacy_opt_out", "transcript_opt_out"):
        value = call.get(key)
        if isinstance(value, bool) and value:
            return True
        if str(value or "").strip().lower() in {"1", "true", "yes", "oui"}:
            return True
    return False


def _execute_select(table: str, columns: str = "*", limit: int | None = None, order: tuple[str, bool] | None = None, **filters) -> list[dict]:
    supa = client()
    if supa is None:
        return []
    try:
        query = supa.table(table).select(columns)
        for key, value in filters.items():
            if isinstance(value, tuple) and len(value) == 2:
                operator, operand = value
                if operator == "gte":
                    query = query.gte(key, operand)
                elif operator == "lte":
                    query = query.lte(key, operand)
                elif operator == "lt":
                    query = query.lt(key, operand)
                elif operator == "gt":
                    query = query.gt(key, operand)
                elif operator == "neq":
                    query = query.neq(key, operand)
                else:
                    query = query.eq(key, operand)
            else:
                query = query.eq(key, value)
        if order is not None:
            column, desc = order
            query = query.order(column, desc=desc)
        if limit is not None:
            query = query.limit(limit)
        response = query.execute()
        return list(response.data or [])
    except Exception as exc:  # noqa: BLE001
        log.warning("[persistence] select %s échoué: %s", table, exc)
        return []


def upsert_agent(call: dict) -> str | None:
    agent_id = canonical_agent_id(call)
    if not agent_id:
        return None
    name = str(call.get("user_name") or "").strip() or "[No associated user]"
    row = {
        "id": agent_id,
        "aircall_user_id": call.get("user_id"),
        "name": name,
        "team": call.get("team") or None,
        "active": True,
    }
    if not _execute_upsert("agents", row, on_conflict="id"):
        return None
    return agent_id


def upsert_call(call: dict) -> str | None:
    call_id = canonical_call_id(call)
    aircall_id = canonical_aircall_id(call)
    if not call_id or not aircall_id:
        return None
    row = {
        "id": call_id,
        "aircall_id": aircall_id,
        "started_at": _iso_from_unix(call.get("call_started_at")),
        "direction": call.get("direction") or None,
        "duration_s": int(call.get("duration_in_call") or 0),
        "scope": _scope_from_call(call),
        "ivr_branch": call.get("ivr_branch") or None,
        "answered": str(call.get("answered") or "").strip().lower() == "yes",
        "transferred": _is_transferred(call),
        "agent_id": upsert_agent(call),
        "raw": _json_safe(call),
    }
    if _supports_column("calls", "caller_hash"):
        row["caller_hash"] = canonical_caller_hash(call)
    if not _execute_upsert("calls", row, on_conflict="id"):
        return None
    return call_id


def save_transcript(call: dict) -> bool:
    transcript = str(call.get("transcript") or "").strip()
    if not transcript:
        return False
    call_id = upsert_call(call)
    if not call_id:
        return False
    row = {
        "call_id": call_id,
        "language": call.get("language") or None,
        "text": transcript,
        "diarization": build_diarization(transcript),
        "source": "aircall_ai",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return _execute_upsert("transcripts", row, on_conflict="call_id")


def _soft_skill_rows(evaluation_id: str, evaluation: dict) -> list[dict]:
    criteria_scores = evaluation.get("criteria_scores") or {}
    rows = []
    for criterion in rubric.rubric_criteria():
        key = criterion["key"]
        rows.append(
            {
                "evaluation_id": evaluation_id,
                "criterion": key,
                "score": criteria_scores.get(key),
                "weight": float(criterion["weight"]),
                "citation": None,
            }
        )
    return rows


def _issue_rows(evaluation_id: str, evaluation: dict) -> list[dict]:
    rows = []
    for idx, item in enumerate(evaluation.get("improvement_items") or []):
        rows.append(
            {
                "id": f"issue:{evaluation_id}:{idx}",
                "evaluation_id": evaluation_id,
                "type": "improvement",
                "severity": "warning",
                "description": item.get("text"),
                "citation": item.get("citation"),
                "kb_reference": item.get("kb_reference"),
            }
        )
    base_idx = len(rows)
    for offset, item in enumerate(evaluation.get("alerts") or []):
        rows.append(
            {
                "id": f"issue:{evaluation_id}:{base_idx + offset}",
                "evaluation_id": evaluation_id,
                "type": "alert",
                "severity": item.get("level"),
                "description": item.get("message"),
                "citation": None,
                "kb_reference": None,
            }
        )
    return rows


def save_evaluation(call: dict, evaluation: dict) -> str | None:
    call_id = upsert_call(call)
    if not call_id:
        return None
    evaluation_id = f"eval:{call_id}"
    llm_meta = evaluation.get("_llm_meta") or {}
    row = {
        "id": evaluation_id,
        "call_id": call_id,
        "model_name": evaluation.get("_model"),
        "model_version": _model_version(evaluation.get("_model")),
        "rubric_version": evaluation.get("rubric_version") or rubric.rubric_version(),
        "score_global": evaluation.get("score_global"),
        "duration_ms": evaluation.get("duration_ms"),
        "tokens_in": llm_meta.get("input_tokens"),
        "tokens_out": llm_meta.get("output_tokens"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw": _json_safe(evaluation),
    }
    if _supports_column("evaluations", "resolution_status"):
        row["resolution_status"] = evaluation.get("resolution_status")
    _execute_upsert("evaluations", row, on_conflict="call_id")
    _execute_delete("soft_skills", evaluation_id=evaluation_id)
    soft_skill_rows = _soft_skill_rows(evaluation_id, evaluation)
    if soft_skill_rows:
        _execute_upsert("soft_skills", soft_skill_rows, on_conflict="evaluation_id,criterion")
    _execute_delete("issues", evaluation_id=evaluation_id)
    issue_rows = _issue_rows(evaluation_id, evaluation)
    if issue_rows:
        _execute_upsert("issues", issue_rows, on_conflict="id")
    save_voc_extract(evaluation_id, call, evaluation.get("voc_extract"))
    return evaluation_id


def save_voc_extract(evaluation_id: str, call: dict, voc_extract: dict | None) -> bool:
    if not evaluation_id or not voc_extract:
        return False
    _seed_voc_taxonomy_once()
    if _call_rgpd_opt_out(call):
        log.info("[persistence] verbatims VoC ignorés pour opt-out RGPD call_id=%s", canonical_call_id(call))
    row = {
        "evaluation_id": evaluation_id,
        "effort_score": voc_extract.get("effort_score"),
        "satisfaction_signal": voc_extract.get("satisfaction_signal"),
        "churn_risk_signal": voc_extract.get("churn_risk_signal"),
        "expansion_signal": voc_extract.get("expansion_signal"),
        "taxonomy_version": voc_extract.get("taxonomy_version") or voc_taxonomy.taxonomy_version(),
        "raw": _json_safe(voc_extract),
    }
    _execute_upsert("voc_extracts", row, on_conflict="evaluation_id")

    _execute_delete("topic_mentions", evaluation_id=evaluation_id)
    topic_rows = []
    for idx, item in enumerate(voc_extract.get("topics") or []):
        topic_rows.append(
            {
                "id": f"topic:{evaluation_id}:{idx}",
                "evaluation_id": evaluation_id,
                "topic_code": item.get("topic_code"),
                "sentiment": item.get("sentiment"),
                "severity": item.get("severity"),
                "quote": None if _call_rgpd_opt_out(call) else item.get("quote"),
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if _supports_column("topic_mentions", "product_area"):
            topic_rows[-1]["product_area"] = item.get("product_area") or voc_taxonomy.product_area_for_topic(item.get("topic_code") or "")
    if topic_rows:
        _execute_upsert("topic_mentions", topic_rows, on_conflict="id")

    _execute_delete("entity_perceptions", evaluation_id=evaluation_id)
    entity_rows = []
    for idx, item in enumerate(voc_extract.get("entity_perceptions") or []):
        entity_rows.append(
            {
                "id": f"entity:{evaluation_id}:{idx}",
                "evaluation_id": evaluation_id,
                "entity_code": item.get("entity_code"),
                "aspect_code": item.get("aspect_code"),
                "sentiment": item.get("sentiment"),
                "quote": None if _call_rgpd_opt_out(call) else item.get("quote"),
            }
        )
    if entity_rows:
        _execute_upsert("entity_perceptions", entity_rows, on_conflict="id")

    _execute_delete("verbatims", evaluation_id=evaluation_id)
    verbatim_rows = []
    if not _call_rgpd_opt_out(call):
        for idx, item in enumerate(voc_extract.get("verbatim_quotes") or []):
            verbatim_rows.append(
                {
                    "id": f"verbatim:{evaluation_id}:{idx}",
                    "evaluation_id": evaluation_id,
                    "quote": item.get("quote"),
                    "timestamp_s": item.get("timestamp_s"),
                    "speaker": item.get("speaker"),
                    "topic_code": item.get("topic_code"),
                    "sentiment": item.get("sentiment"),
                    "pinned": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    if verbatim_rows:
        _execute_upsert("verbatims", verbatim_rows, on_conflict="id")

    _execute_delete("competitor_mentions", evaluation_id=evaluation_id)
    competitor_rows = []
    for idx, item in enumerate(voc_extract.get("competitor_mentions") or []):
        competitor_rows.append(
            {
                "id": f"competitor:{evaluation_id}:{idx}",
                "evaluation_id": evaluation_id,
                "competitor_name": item.get("competitor_name"),
                "context_quote": None if _call_rgpd_opt_out(call) else item.get("context_quote"),
                "sentiment": item.get("sentiment"),
            }
        )
    if competitor_rows:
        _execute_upsert("competitor_mentions", competitor_rows, on_conflict="id")
    _persist_voc_signals(evaluation_id, call, voc_extract)
    _persist_best_practices(evaluation_id, call, voc_extract)
    return True


def _signal_similarity(a: str, b: str) -> float:
    return fuzz.ratio(str(a or "").strip().lower(), str(b or "").strip().lower()) / 100.0


def _find_existing_signal(signal_type: str, description: str) -> dict | None:
    candidates = _execute_select(
        "voc_signals",
        columns="id,type,description,frequency,source_call_ids,first_seen,last_seen,severity,status,tags",
        limit=50,
        order=("last_seen", True),
        type=signal_type,
    )
    best = None
    best_score = 0.0
    for row in candidates:
        score = _signal_similarity(row.get("description"), description)
        if score >= 0.85 and score > best_score:
            best = row
            best_score = score
    return best


def _upsert_voc_signal(signal_type: str, description: str, call_id: str, detected_on: str, tags: list[str] | None = None) -> bool:
    cleaned = re.sub(r"\s+", " ", str(description or "").strip())
    if not cleaned or not call_id:
        return False
    existing = _find_existing_signal(signal_type, cleaned)
    if existing:
        already_present = call_id in (existing.get("source_call_ids") or [])
        source_call_ids = list(dict.fromkeys([*(existing.get("source_call_ids") or []), call_id]))
        row = {
            "id": existing["id"],
            "type": signal_type,
            "detected_on": existing.get("detected_on") or detected_on,
            "description": existing.get("description") or cleaned,
            "source_call_ids": source_call_ids,
            "frequency": int(existing.get("frequency") or 1) if already_present else int(existing.get("frequency") or 1) + 1,
            "severity": existing.get("severity"),
            "status": existing.get("status") or "new",
            "first_seen": existing.get("first_seen") or detected_on,
            "last_seen": detected_on,
            "tags": list(dict.fromkeys([*(existing.get("tags") or []), *(tags or [])])),
        }
        return _execute_upsert("voc_signals", row, on_conflict="id")
    signal_id = f"voc_signal:{signal_type}:{sha256(cleaned.lower().encode('utf-8')).hexdigest()[:16]}"
    row = {
        "id": signal_id,
        "type": signal_type,
        "detected_on": detected_on,
        "description": cleaned,
        "source_call_ids": [call_id],
        "frequency": 1,
        "severity": None,
        "status": "new",
        "first_seen": detected_on,
        "last_seen": detected_on,
        "tags": tags or [],
    }
    return _execute_upsert("voc_signals", row, on_conflict="id")


def _persist_voc_signals(evaluation_id: str, call: dict, voc_extract: dict) -> None:
    call_id = canonical_call_id(call)
    if not call_id:
        return
    detected_on = datetime.now(timezone.utc).date().isoformat()
    for item in voc_extract.get("product_ideas") or []:
        _upsert_voc_signal("product_idea", item, call_id, detected_on, tags=["produit"])
    for item in voc_extract.get("unmet_needs") or []:
        _upsert_voc_signal("unmet_need", item, call_id, detected_on, tags=["cx"])
    if voc_extract.get("expansion_signal"):
        _upsert_voc_signal("opportunity", "Signal d'expansion ou recommandation détecté", call_id, detected_on, tags=["cx", "produit"])


def _persist_best_practices(evaluation_id: str, call: dict, voc_extract: dict) -> None:
    if not _table_exists("agent_best_practices"):
        return
    _execute_delete("agent_best_practices", evaluation_id=evaluation_id)
    rows = []
    agent_id = canonical_agent_id(call)
    for idx, item in enumerate(voc_extract.get("best_practice_moments") or []):
        rows.append(
            {
                "id": f"best_practice:{evaluation_id}:{idx}",
                "evaluation_id": evaluation_id,
                "quote": item.get("quote"),
                "agent_id": agent_id,
                "topic_code": item.get("topic_code"),
            }
        )
    if rows:
        _execute_upsert("agent_best_practices", rows, on_conflict="id")


def purge_expired_verbatims() -> bool:
    supa = client()
    if supa is None:
        return False
    cutoff = datetime.now(timezone.utc).timestamp() - (config.VOC_VERBATIM_RETENTION_DAYS * 86400)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    try:
        supa.table("verbatims").delete().lt("created_at", cutoff_iso).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("[persistence] purge verbatims échouée: %s", exc)
        return False


def save_daily_snapshot(snapshot_date: datetime, scope: str, metrics: dict) -> bool:
    row = {
        "date": snapshot_date.strftime("%Y-%m-%d"),
        "scope": scope,
        "agent_id": str(metrics.get("agent_id") or ""),
        "total_calls": metrics.get("calls_presented"),
        "pickup_rate": metrics.get("pickup_rate_pct"),
        "abandon_rate": metrics.get("abandon_rate_pct"),
        "avg_handle_time": metrics.get("avg_duration_seconds"),
        "repeat_caller_rate": metrics.get("repeat_caller_rate_pct"),
        "avg_soft_score": metrics.get("avg_soft_score"),
        "kb_compliance_rate": metrics.get("kb_compliance_rate_pct"),
        "warm_transfer_success_rate": metrics.get("warm_transfer_success_rate_pct"),
        "coverage_pct": metrics.get("coverage_pct"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    if _supports_column("daily_kpi_snapshot", "fcr_rate"):
        row["fcr_rate"] = metrics.get("fcr_rate_pct")
    return _execute_upsert("daily_kpi_snapshot", row, on_conflict="date,scope,agent_id")


def save_llm_run(run: dict) -> bool:
    row = {
        "id": run.get("id"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "mode": run.get("mode"),
        "model": run.get("model"),
        "calls_count": run.get("calls_count"),
        "errors_count": run.get("errors_count"),
        "tokens_total": run.get("tokens_total"),
        "status": run.get("status") or "unknown",
        "raw": _json_safe(run.get("raw") or {}),
        "trigger_source": run.get("trigger_source") or "cron",
        "triggered_by": run.get("triggered_by"),
        "params": _json_safe(run.get("params") or {}),
        "logs_excerpt": run.get("logs_excerpt"),
        "pipeline_config_id": run.get("pipeline_config_id"),
        "rubric_version_id": run.get("rubric_version_id"),
        "prompt_override_id": run.get("prompt_override_id"),
    }
    if not row["id"] or not row["started_at"]:
        return False
    return _execute_upsert("llm_runs", row, on_conflict="id")


def save_kb_gaps(gaps: list[dict], detected_on: datetime) -> int:
    if not gaps:
        return 0
    _execute_delete("kb_gaps", detected_on=detected_on.strftime("%Y-%m-%d"))
    rows = []
    for gap in gaps:
        rows.append(
            {
                "detected_on": detected_on.strftime("%Y-%m-%d"),
                "topic": gap.get("topic"),
                "frequency": int(gap.get("frequency") or 0),
                "example_call_ids": gap.get("example_call_ids") or [],
                "status": gap.get("status") or "new",
            }
        )
    if not rows:
        return 0
    return len(rows) if _execute_upsert("kb_gaps", rows, on_conflict="detected_on,topic") else 0


def save_anomaly_event(event: dict) -> bool:
    row = {
        "id": event.get("id"),
        "detected_on": event.get("detected_on"),
        "scope": event.get("scope") or "global",
        "agent_id": str(event.get("agent_id") or ""),
        "metric": event.get("metric"),
        "z_score": event.get("z_score"),
        "current_value": event.get("current_value"),
        "baseline_mean": event.get("baseline_mean"),
        "baseline_stddev": event.get("baseline_stddev"),
        "representative_call_ids": event.get("representative_call_ids") or [],
        "context": _json_safe(event.get("context") or {}),
        "status": event.get("status") or "new",
    }
    if not row["id"] or not row["detected_on"] or not row["metric"]:
        return False
    return _execute_upsert("anomaly_events", row, on_conflict="id")


def save_shadow_runs(rows: list[dict]) -> int:
    payload = []
    for row in rows or []:
        if not row.get("id") or not row.get("call_id"):
            continue
        payload.append(
            {
                "id": row.get("id"),
                "call_id": row.get("call_id"),
                "evaluation_id": row.get("evaluation_id"),
                "primary_model": row.get("primary_model"),
                "shadow_model": row.get("shadow_model"),
                "primary_score": row.get("primary_score"),
                "shadow_score": row.get("shadow_score"),
                "delta_score": row.get("delta_score"),
                "raw": _json_safe(row.get("raw") or {}),
            }
        )
    if not payload:
        return 0
    return len(payload) if _execute_upsert("shadow_runs", payload, on_conflict="id") else 0


def fetch_daily_snapshots(scope: str, days: int = 14, agent_id: str = "") -> list[dict]:
    cutoff = datetime.now(timezone.utc).date().toordinal() - max(1, int(days))
    cutoff_date = datetime.fromordinal(cutoff).strftime("%Y-%m-%d")
    columns = "date,scope,agent_id,pickup_rate,abandon_rate,avg_soft_score,total_calls,avg_handle_time,repeat_caller_rate,kb_compliance_rate,warm_transfer_success_rate,coverage_pct"
    if _supports_column("daily_kpi_snapshot", "fcr_rate"):
        columns += ",fcr_rate"
    return _execute_select(
        "daily_kpi_snapshot",
        columns=columns,
        order=("date", False),
        scope=scope,
        agent_id=str(agent_id or ""),
        date=("gte", cutoff_date),
    )


def fetch_raw_evaluations_by_call_ids(call_ids: list[str]) -> dict[str, dict]:
    """Retourne `{call_id: raw_evaluation}` pour les call_ids déjà évalués.
    Permet au weekly de réutiliser les évaluations produites par les dailies
    sans repayer le temps Ollama. Clé = `call_id` Supabase (cf. upsert_call)."""
    if not call_ids or not is_enabled():
        return {}
    client_ = client()
    if not client_:
        return {}
    unique_ids = list({cid for cid in call_ids if cid})
    if not unique_ids:
        return {}
    result: dict[str, dict] = {}
    # Supabase `in_` filter : chunk prudent pour éviter les URLs trop longues.
    chunk = 100
    try:
        for i in range(0, len(unique_ids), chunk):
            batch = unique_ids[i:i + chunk]
            rows = (
                client_.table("evaluations")
                .select("call_id,raw")
                .in_("call_id", batch)
                .execute()
                .data
                or []
            )
            for row in rows:
                raw = row.get("raw")
                if isinstance(raw, dict) and row.get("call_id"):
                    result[row["call_id"]] = raw
    except Exception as exc:  # noqa: BLE001
        log.warning("[persistence] fetch_raw_evaluations_by_call_ids KO: %s", exc)
        return {}
    return result


def fetch_recent_anomaly_events(limit: int = 20) -> list[dict]:
    return _execute_select("anomaly_events", columns="*", limit=limit, order=("created_at", True))


def fetch_latest_llm_run() -> dict | None:
    rows = _execute_select("llm_runs", columns="id,started_at,ended_at,mode,model,calls_count,errors_count,tokens_total,status,raw", limit=1, order=("started_at", True))
    return rows[0] if rows else None


def fetch_llm_run_for_date(mode: str, target_date: datetime) -> dict | None:
    """Return the most recent llm_runs row for `mode` on `target_date` (UTC day), or None.

    Used by the weekly guard to verify that Sunday's daily completed before
    the Monday weekly kicks off.
    """
    supa = client()
    if supa is None:
        return None
    try:
        prefix = f"{mode}:{target_date.strftime('%Y-%m-%d')}:"
        response = (
            supa.table("llm_runs")
            .select("id,started_at,ended_at,mode,status,calls_count,errors_count")
            .like("id", f"{prefix}%")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        log.warning(f"fetch_llm_run_for_date failed: {exc}")
        return None


def fetch_view_rows(view_name: str, columns: str = "*", limit: int | None = None, order: tuple[str, bool] | None = None, **filters) -> list[dict]:
    return _execute_select(view_name, columns=columns, limit=limit, order=order, **filters)


def persist_calls(calls: list[dict]) -> int:
    saved = 0
    for call in calls or []:
        if upsert_call(call):
            saved += 1
    return saved


def persist_transcripts(calls: list[dict]) -> int:
    saved = 0
    for call in calls or []:
        if save_transcript(call):
            saved += 1
    return saved


def persist_evaluations(source_calls: list[dict], evaluations: list[dict]) -> int:
    call_index = {}
    for call in source_calls or []:
        call_id = canonical_call_id(call)
        if call_id:
            call_index[call_id] = call
    saved = 0
    for evaluation in evaluations or []:
        call_id = str(evaluation.get("call_id") or "").strip()
        source_call = call_index.get(call_id)
        if source_call and save_evaluation(source_call, evaluation):
            saved += 1
    return saved


# ---- Active runtime config helpers (QA-UCC) ----
# Utilisés par runtime_config.load_runtime_config() au boot de la pipeline.
# Retournent None si la table est vide ou si Supabase indisponible.

def fetch_active_pipeline_config() -> dict | None:
    """Retourne la row pipeline_config active ou None."""
    supa = client()
    if supa is None:
        return None
    try:
        r = supa.table("pipeline_config").select("*").eq("is_active", True).limit(1).execute()
    except Exception as exc:  # pragma: no cover - défensif
        log.warning("[persistence] fetch_active_pipeline_config failed: %s", exc)
        return None
    return r.data[0] if r.data else None


def fetch_active_rubric() -> dict | None:
    """Retourne la row rubric_versions active ou None."""
    supa = client()
    if supa is None:
        return None
    try:
        r = (
            supa.table("rubric_versions")
            .select("id,version,criteria,yaml_source")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # pragma: no cover - défensif
        log.warning("[persistence] fetch_active_rubric failed: %s", exc)
        return None
    return r.data[0] if r.data else None


def fetch_active_prompt_override() -> dict | None:
    """Retourne la row prompt_overrides active ou None."""
    supa = client()
    if supa is None:
        return None
    try:
        r = (
            supa.table("prompt_overrides")
            .select("id,override_text,baseline_sha,active_until")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # pragma: no cover - défensif
        log.warning("[persistence] fetch_active_prompt_override failed: %s", exc)
        return None
    return r.data[0] if r.data else None


def fetch_llm_run(run_id: str):
    """Retourne la row llm_runs pour un id donné, ou None."""
    supa = client()
    if supa is None:
        return None
    try:
        r = supa.table("llm_runs").select("*").eq("id", run_id).limit(1).execute()
    except Exception as exc:  # pragma: no cover - défensif
        log.warning("[persistence] fetch_llm_run failed: %s", exc)
        return None
    return r.data[0] if r.data else None
