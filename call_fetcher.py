"""
call_fetcher.py — Récupère les appels depuis le worker Cloudflare (call-history/export).
Fallback : API Aircall directe si le worker est indisponible.
"""
from datetime import datetime
from hashlib import sha256
import time
import requests
import d1_client
import config

_AIRCALL_API_SESSION = requests.Session()
_CALL_DETAILS_CACHE: dict[str, dict | None] = {}
_NUMBER_CALLS_CACHE: dict[str, list[dict]] = {}
_TRANSCRIPT_CACHE: dict[str, str | None] = {}

# Fuseau horaire Paris pour calcul des timestamps minuit/23h59
try:
    from zoneinfo import ZoneInfo as _ZI
    _PARIS_TZ = _ZI("Europe/Paris")
except ImportError:
    try:
        import pytz as _pytz
        _PARIS_TZ = _pytz.timezone("Europe/Paris")
    except ImportError:
        _PARIS_TZ = None  # Fallback : timezone système


def fetch_calls_for_date(date: datetime) -> list[dict]:
    """Retourne tous les appels d'une journée (00:00 → 23:59 heure Paris, timezone explicite)."""
    if _PARIS_TZ is not None:
        try:
            # zoneinfo
            paris_start = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=_PARIS_TZ)
            paris_end   = datetime(date.year, date.month, date.day, 23, 59, 59, tzinfo=_PARIS_TZ)
            ts_from = int(paris_start.timestamp())
            ts_to   = int(paris_end.timestamp())
        except Exception:
            # pytz fallback
            paris_start = _PARIS_TZ.localize(datetime(date.year, date.month, date.day, 0, 0, 0))
            paris_end   = _PARIS_TZ.localize(datetime(date.year, date.month, date.day, 23, 59, 59))
            ts_from = int(paris_start.timestamp())
            ts_to   = int(paris_end.timestamp())
    else:
        # Dernier recours : timezone système (doit être Paris sur Mac de prod)
        ts_from = int(datetime(date.year, date.month, date.day, 0, 0, 0).timestamp())
        ts_to   = int(datetime(date.year, date.month, date.day, 23, 59, 59).timestamp())
    return fetch_calls_range(ts_from, ts_to)


def fetch_calls_range(ts_from: int, ts_to: int) -> list[dict]:
    """Récupère les appels entre deux timestamps unix."""
    calls = d1_client.fetch_call_history(ts_from, ts_to)
    # Normalise les noms de champs (le worker peut renvoyer camelCase ou snake_case)
    return [_normalize_call(c) for c in calls]


def _normalize_call(c: dict) -> dict:
    """
    Uniformise les noms de champs.
    Gère deux formats :
      - Format export worker : clés lisibles ('Call id (internal)', 'duration (in call)', ...)
      - Format DB snake_case  : clés normalisées ('call_id_internal', 'duration_in_call', ...)
    """
    # Conversion "Call start time" → timestamp Unix
    started_raw = (
        c.get("call_started_at") or c.get("callStartedAt")
        or c.get("Call start time") or c.get("datetime (tz offset incl.)")
    )
    call_started_at = _parse_datetime(started_raw)

    from_number = c.get("from_number") or c.get("from") or c.get("fromNumber") or ""
    customer_number = c.get("Customer number") or c.get("customer_number") or c.get("to") or ""
    phone_e164 = _normalize_phone_e164(from_number or customer_number)
    return {
        "call_id_internal": c.get("call_id_internal") or c.get("Call id (internal)") or c.get("id"),
        "call_id":          str(c.get("call_id") or c.get("Call id") or c.get("callId") or ""),
        "user_id":          _parse_int(
            c.get("user_id")
            or c.get("userId")
            or (c.get("user") or {}).get("id") if isinstance(c.get("user"), dict) else None
        ),
        "line_id":          (
            _parse_int(c.get("line_id") or c.get("lineId"))
            or _LINE_NAME_TO_ID.get(c.get("line") or "")
            or _LINE_NAME_TO_ID.get(c.get("line_name") or "")
        ),
        "line_name":        c.get("line_name") or c.get("line") or c.get("lineName", ""),
        "direction":        c.get("direction", ""),
        "answered":         _normalize_answered(c.get("answered") or c.get("Answered", "No")),
        "missed_call_reason": (
            c.get("missed_call_reason") or c.get("missedCallReason")
            or c.get("missed call reason") or ""
        ),
        "duration_total":   c.get("duration_total") or c.get("duration (total)") or c.get("durationTotal") or 0,
        "duration_in_call": c.get("duration_in_call") or c.get("duration (in call)") or c.get("In-call duration") or c.get("durationInCall") or 0,
        "waiting_time":     _parse_wait(
            c.get("waiting_time") or c.get("Waiting time") or c.get("waitingTime") or 0
        ),
        "ivr_branch":       c.get("ivr_branch") or c.get("IVR Branch") or c.get("ivrBranch") or "",
        "ivr_widget":       c.get("ivr_widget") or c.get("IVR Widget") or c.get("ivrWidget") or "",
        "tags":             c.get("tags") or c.get("Tags") or "",
        "team":             c.get("team") or c.get("Team") or "",
        "call_type":        c.get("call_type") or c.get("Call Type") or c.get("callType") or "",
        "recording_url":    c.get("recording_url") or c.get("Recording") or c.get("recordingUrl") or "",
        "user_name":        c.get("user_name") or c.get("user") or c.get("userName") or "",
        "agents_solicited": c.get("agents_solicited") or c.get("agentsSolicited") or "",
        "from_number":      from_number,
        "customer_number":  customer_number,
        "phone_e164":       phone_e164,
        "caller_hash":      _caller_hash(phone_e164),
        "call_started_at":  call_started_at,
        "call_timeline":    c.get("call_timeline") or c.get("Call Timeline") or c.get("callTimeline") or "",
    }


def _parse_int(val) -> int | None:
    """Convertit en int — gère les strings retournées par le worker ('785174' → 785174)."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# Mapping nom de ligne Aircall → line_id numérique
# Le worker /call-history/export renvoie 'line' (nom texte), pas 'line_id'
_LINE_NAME_TO_ID: dict[str, int] = {
    "Ligne Assistance Utilisateurs - N° OVH": 785174,
    "Ligne MES/Maintenance - N° OVH": 785175,
    "DRIVECO - UCC Transfer": 1214611,
    "NEW - Ligne assistance Utilisateurs - Belgique": 1075934,
    "NEW - Ligne assistance Utilisateurs - Italy": 1075935,
    "NEW - Ligne assistance Utilisateurs - Spain": 1075937,
}


def _normalize_answered(val) -> str:
    """Normalise 'answered' vers 'Yes'/'No'."""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if str(val).strip().lower() in ("yes", "true", "1"):
        return "Yes"
    return "No"


def _parse_datetime(val) -> int:
    """Convertit une date string ou timestamp vers int Unix."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    from datetime import datetime
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(str(val), fmt).timestamp())
        except ValueError:
            continue
    return 0


def _parse_wait(val) -> int:
    """Convertit le waiting_time (peut être 'HH:MM:SS' ou un int) en secondes."""
    if isinstance(val, int):
        return val
    if isinstance(val, str) and ":" in val:
        parts = val.split(":")
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (IndexError, ValueError):
            return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _normalize_phone_e164(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = f"33{digits[1:]}"
    return f"+{digits}"


def _caller_hash(phone_e164: str) -> str:
    if not phone_e164:
        return ""
    return sha256(phone_e164.encode("utf-8")).hexdigest()[:12]


def fetch_transcript(call_id: str) -> str | None:
    """
    Récupère le transcript Aircall AI pour un appel.
    Essaie d'abord l'endpoint /transcription (Aircall AI), puis le détail de l'appel.
    Retourne une chaîne formatée [Agent]/[Client]: texte, ou None si absent.
    """
    cache_key = str(call_id or "").strip()
    if not cache_key:
        return None
    if cache_key in _TRANSCRIPT_CACHE:
        return _TRANSCRIPT_CACHE[cache_key]
    if not config.AIRCALL_API_ID or not config.AIRCALL_API_TOKEN:
        return None
    auth = (config.AIRCALL_API_ID, config.AIRCALL_API_TOKEN)

    def _get_json(url: str, max_attempts: int = 5):
        delay = 1.0
        for attempt in range(max_attempts):
            try:
                resp = _AIRCALL_API_SESSION.get(url, auth=auth, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        sleep_seconds = max(1.0, float(retry_after))
                    except (TypeError, ValueError):
                        sleep_seconds = delay
                    time.sleep(sleep_seconds)
                    delay = min(delay * 2, 8.0)
                    continue
            except Exception:
                return None
            break
        return None

    call_details = fetch_call_details(cache_key)

    # Endpoint direct Aircall AI (prioritaire)
    data = _get_json(f"{config.AIRCALL_BASE_URL}/calls/{cache_key}/transcription")
    if data:
        formatted = _format_transcript(data.get("transcription") or data, call_details=call_details)
        if formatted:
            _TRANSCRIPT_CACHE[cache_key] = formatted
            return formatted

    # Fallback : détail de l'appel (champ call.transcription)
    if call_details:
        transcription = call_details.get("transcription")
        if transcription:
            formatted = _format_transcript(transcription, call_details=call_details)
            _TRANSCRIPT_CACHE[cache_key] = formatted
            return formatted

    _TRANSCRIPT_CACHE[cache_key] = None
    return None


def _normalize_digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _infer_speaker_label(utterance: dict, call_details: dict | None = None) -> str:
    speaker = str(utterance.get("speaker") or utterance.get("participant_type") or "").strip().lower()
    if speaker in {"agent", "operator", "internal"}:
        return "Agent"
    if speaker in {"customer", "client"}:
        return "Client"

    utterance_digits = _normalize_digits(utterance.get("phone_number"))
    if utterance_digits and utterance_digits in config.INTERNAL_PHONE_BLACKLIST:
        return "Agent"

    if call_details:
        customer_digits = _normalize_digits(call_details.get("raw_digits"))
        number_digits = _normalize_digits((call_details.get("number") or {}).get("digits"))
        if utterance_digits and customer_digits and utterance_digits == customer_digits:
            return "Client"
        if utterance_digits and number_digits and utterance_digits == number_digits:
            return "Agent"
    return "Client" if speaker == "external" else "Agent"


def _is_boilerplate_utterance(text: str) -> bool:
    compact = " ".join(str(text or "").strip().lower().split())
    if not compact:
        return True
    markers = (
        "afin de faciliter votre prise en charge",
        "un agent va prendre votre appel",
        "merci de patienter",
        "en installant notre application",
        "vous bénéficierez également de fonctionnalités pratiques",
        "historique complet de vos recharges",
        "réservation de bornes et l'autocharge",
        "en scannant simplement le q r code",
        "avec votre compte drive eco",
        "sur l'ensemble de notre réseau",
        "application drive eco",
        "vous pourrez recharger votre véhicule",
        "drive eco",
        "vos recharges",
        "fonctionnalités",
        "de notre réseau",
    )
    return any(marker in compact for marker in markers)


def _extract_utterances(data) -> list[dict]:
    if not data:
        return []
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, dict):
            utterances = content.get("utterances") or content.get("transcript")
            if isinstance(utterances, list):
                return utterances
        utterances = data.get("transcript") or data.get("utterances")
        if isinstance(utterances, list):
            return utterances
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _should_drop_fragment(text: str) -> bool:
    compact = " ".join(str(text or "").strip().split())
    if not compact:
        return True
    words = compact.split()
    if len(words) >= 3:
        return False
    lowered = compact.lower()
    keep_short = {
        "oui", "non", "d'accord", "ok", "allo", "allô", "bonjour", "merci",
    }
    if lowered in keep_short:
        return False
    return len(compact) <= 8


def _merge_transcript_lines(lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[list[str]] = []
    for label, content in lines:
        content = " ".join(content.split())
        if not content or _should_drop_fragment(content):
            continue
        if merged and merged[-1][0] == label:
            merged[-1][1] = f"{merged[-1][1]} {content}".strip()
        else:
            merged.append([label, content])
    return [(label, content) for label, content in merged if content]


def _format_transcript(data, call_details: dict | None = None) -> str | None:
    """
    Convertit la réponse Aircall AI en texte lisible.
    Format Aircall AI : {"transcript": [{"content": "...", "speaker": "agent|customer", ...}]}
    """
    if not data:
        return None
    # Si c'est déjà une string, on la retourne directement
    if isinstance(data, str):
        return data.strip() or None

    utterances = _extract_utterances(data)

    if not utterances:
        return None

    lines: list[tuple[str, str]] = []
    for u in utterances:
        content = (u.get("content") or u.get("text") or "").strip()
        if not content or _is_boilerplate_utterance(content):
            continue
        label = _infer_speaker_label(u, call_details=call_details)
        lines.append((label, content))

    lines = _merge_transcript_lines(lines)

    return "\n".join(f"[{label}] {content}" for label, content in lines) if lines else None


def fetch_sample_with_transcripts(calls: list[dict], max_samples: int = 10) -> list[dict]:
    """
    Legacy — conservé pour compatibilité.
    Sélectionne un échantillon et enrichit avec les transcripts.
    """
    escalations = [c for c in calls if "escalation" in (c.get("tags") or "").lower()]
    abandoned   = [c for c in calls if (c.get("call_type") or "").lower() == "abandoned"]
    rest = sorted(
        [c for c in calls if c not in escalations and c not in abandoned],
        key=lambda x: x.get("duration_in_call") or 0,
        reverse=True,
    )
    sample = (escalations + abandoned + rest)[:max_samples]
    return enrich_with_transcripts(sample, max_with_transcript=max_samples)


def enrich_with_transcripts(calls: list[dict], max_with_transcript: int | None = None) -> list[dict]:
    """
    Enrichit les appels avec leur transcript Aircall AI.
    Si max_with_transcript est défini, limite l'enrichissement aux N premiers appels.
    Sinon, tente un transcript sur tous les appels fournis.
    Transcripts tronqués à 2 500 chars.
    """
    quota = len(calls) if max_with_transcript is None else max(0, int(max_with_transcript))
    for i, call in enumerate(calls):
        if i < quota:
            raw = fetch_transcript(str(call.get("call_id", "")))
            call["transcript"] = raw[:max(500, config.OLLAMA_TRANSCRIPT_MAX_CHARS)] if raw else None
        else:
            call["transcript"] = None
    return calls


def _extract_agent_identity_from_details(details: dict | None) -> tuple[int | None, str | None]:
    if not isinstance(details, dict):
        return None, None
    candidates = [
        details.get("user"),
        details.get("agent"),
        (details.get("assigned_to") or {}).get("user") if isinstance(details.get("assigned_to"), dict) else None,
        details,
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        user_id = _parse_int(
            candidate.get("id")
            or candidate.get("user_id")
            or candidate.get("userId")
            or (candidate.get("user") or {}).get("id") if isinstance(candidate.get("user"), dict) else None
        )
        user_name = (
            candidate.get("name")
            or candidate.get("full_name")
            or candidate.get("user_name")
            or candidate.get("userName")
            or None
        )
        if not user_name and (candidate.get("first_name") or candidate.get("last_name")):
            user_name = f"{candidate.get('first_name') or ''} {candidate.get('last_name') or ''}".strip() or None
        if user_id is not None or user_name:
            return user_id, user_name
    return None, None


def enrich_with_agent_identity(calls: list[dict], max_missing_lookup: int = 25) -> list[dict]:
    """
    S'assure que `user_id` et `user_name` sont présents.
    Priorité aux données worker ; fallback ponctuel vers l'API Aircall `calls/{id}`.
    """
    lookups = 0
    for call in calls:
        if call.get("user_id") is not None and call.get("user_name"):
            continue
        if lookups >= max_missing_lookup:
            break
        details = fetch_call_details(call.get("call_id"))
        lookups += 1
        user_id, user_name = _extract_agent_identity_from_details(details)
        if call.get("user_id") is None and user_id is not None:
            call["user_id"] = user_id
        if not call.get("user_name") and user_name:
            call["user_name"] = user_name
    return calls


def _aircall_auth():
    if not config.AIRCALL_API_ID or not config.AIRCALL_API_TOKEN:
        return None
    return (config.AIRCALL_API_ID, config.AIRCALL_API_TOKEN)


def _aircall_get(path: str, params: dict | None = None) -> dict:
    auth = _aircall_auth()
    if not auth:
        raise RuntimeError("missing_aircall_credentials")
    resp = _AIRCALL_API_SESSION.get(
        f"{config.AIRCALL_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
        auth=auth,
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_call_details(call_id: str | int) -> dict | None:
    cache_key = str(call_id or "").strip()
    if not cache_key:
        return None
    if cache_key in _CALL_DETAILS_CACHE:
        return _CALL_DETAILS_CACHE[cache_key]
    try:
        data = _aircall_get(f"calls/{cache_key}", params={"fetch_call_timeline": "true"})
        call = data.get("call") if isinstance(data, dict) else None
        _CALL_DETAILS_CACHE[cache_key] = call or None
    except Exception:
        _CALL_DETAILS_CACHE[cache_key] = None
    return _CALL_DETAILS_CACHE[cache_key]


def fetch_calls_by_number(number: str, from_ts: int | None = None, to_ts: int | None = None,
                          per_page: int = 50) -> list[dict]:
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    if not digits:
        return []
    cache_key = f"{digits}:{from_ts or ''}:{to_ts or ''}:{per_page}"
    if cache_key in _NUMBER_CALLS_CACHE:
        return _NUMBER_CALLS_CACHE[cache_key]

    params = {"per_page": min(max(per_page, 1), 50)}
    if from_ts is not None:
        params["from"] = int(from_ts)
    if to_ts is not None:
        params["to"] = int(to_ts)

    calls: list[dict] = []
    try:
        for page in range(1, 4):
            payload = dict(params)
            payload["page"] = page
            data = _aircall_get("calls", params=payload)
            batch = data.get("calls") or []
            for call in batch:
                raw_digits = "".join(ch for ch in str(call.get("raw_digits") or "") if ch.isdigit())
                line_digits = "".join(ch for ch in str((call.get("number") or {}).get("digits") or "") if ch.isdigit())
                if digits not in {raw_digits, line_digits}:
                    continue
                calls.append(call)
            if len(batch) < params["per_page"]:
                break
    except Exception:
        calls = []

    _NUMBER_CALLS_CACHE[cache_key] = calls
    return calls


def summarize_transfer_context(call: dict) -> dict:
    """
    Estime le temps avant transfert en rapprochant l'appel UCC d'un éventuel appel
    ultérieur sur la ligne de transfert ou vers la cible transférée.
    """
    base_call_id = call.get("call_id_internal") or call.get("call_id")
    base_started = int(call.get("call_started_at") or 0)
    base_total = int(call.get("duration_total") or call.get("duration_in_call") or 0)
    base_ended = base_started + base_total if base_started and base_total else 0
    customer_number = call.get("from_number") or call.get("customer_number")
    if not base_call_id or not base_started or not customer_number:
        return {}

    details = fetch_call_details(base_call_id)
    if not details:
        return {}

    transferred_to = details.get("transferred_to") or {}
    transfer_target_name = (
        transferred_to.get("name")
        or (transferred_to.get("user") or {}).get("name")
        or None
    )
    transfer_target_number_id = (
        transferred_to.get("number_id")
        or (transferred_to.get("number") or {}).get("id")
        or None
    )

    related_calls = fetch_calls_by_number(
        customer_number,
        from_ts=max(0, base_started - 300),
        to_ts=base_ended + 900 if base_ended else base_started + 900,
    )
    transfer_call = None
    for related in related_calls:
        related_id = str(related.get("id") or related.get("call_id") or "").strip()
        if not related_id or related_id == str(base_call_id):
            continue
        related_started = int(related.get("started_at") or 0)
        related_number_id = (related.get("number") or {}).get("id")
        if related_started < base_started:
            continue
        if transfer_target_number_id and related_number_id == transfer_target_number_id:
            transfer_call = related
            break
        if related_number_id == config.AIRCALL_UCC_TRANSFER_LINE_ID:
            transfer_call = related
            break

    summary = {
        "transfer_detected": bool(transferred_to or transfer_call),
        "transfer_target_name": transfer_target_name,
        "transfer_call_id": transfer_call.get("id") if transfer_call else None,
        "transfer_call_started_at": transfer_call.get("started_at") if transfer_call else None,
        "pre_transfer_seconds": None,
        "post_transfer_seconds": None,
    }
    if transfer_call and transfer_call.get("started_at"):
        transfer_started = int(transfer_call.get("started_at") or 0)
        if transfer_started > base_started:
            summary["pre_transfer_seconds"] = max(0, transfer_started - base_started)
            if base_ended:
                summary["post_transfer_seconds"] = max(0, base_ended - transfer_started)
    return summary
