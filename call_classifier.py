"""
call_classifier.py — Classifie chaque appel selon son type métier Driveco.
Basé sur le schema real de aircall_call_history.
"""
import config

# IDs des lignes Aircall (depuis config.py)
UCC_LINE_IDS          = config.UCC_LINE_IDS         # {785174, 1214611}
BACKUP_LINE_IDS       = config.BACKUP_LINE_IDS       # {785175}
UCC_TRANSFER_LINE_ID  = config.AIRCALL_UCC_TRANSFER_LINE_ID  # 1214611
ASSISTANCE_LINE_ID    = config.AIRCALL_ASSISTANCE_LINE_ID    # 785174
UCC_QA_TYPES          = {"ucc_handled", "warm_transfer"}
DRIVECO_QA_TYPES      = {"ucc_transfer_handled", "b2b_direct", "driveco_direct"}


def classify_call(call: dict) -> str:
    """
    Retourne le type d'appel parmi :
      deflector | b2b_direct | abandoned | ucc_overflow | warm_transfer |
      ucc_handled | ucc_transfer_handled | maintenance_direct | driveco_direct

    ucc_transfer_handled : appel reçu sur la ligne 1214611 (UCC Transfer)
        → Driveco Care répond à un transfert chaud initié par l'UCC.
        → Permet d'évaluer la partie Driveco Care du warm transfer.
    """
    ivr           = (call.get("ivr_branch") or "").lower()
    missed_reason = (call.get("missed_call_reason") or "").lower()
    call_type     = (call.get("call_type") or "").lower()
    answered      = (call.get("answered") or "No")
    line_id       = call.get("line_id")
    tags          = (call.get("tags") or "").lower()

    # Appels sur la ligne transfert UCC → Driveco Care (1214611)
    # Classifiés séparément pour mesurer la qualité de la prise en charge Care post-transfert
    if line_id == UCC_TRANSFER_LINE_ID:
        if answered == "Yes":
            return "ucc_transfer_handled"
        # Transfert chaud non décroché par Care → alerte
        return "ucc_transfer_missed"

    if "key_3" in ivr or "deflect" in ivr:
        return "deflector"
    if "key_2" in ivr or "b2b" in ivr:
        return "b2b_direct"
    if call_type == "abandoned":
        return "abandoned"
    if missed_reason == "timeout":
        return "ucc_overflow"
    if line_id in BACKUP_LINE_IDS:
        return "maintenance_direct"
    if "escalation" in tags:
        return "warm_transfer"
    if answered == "Yes" and line_id == ASSISTANCE_LINE_ID:
        return "ucc_handled"
    return "driveco_direct"


def classify_all(calls: list[dict]) -> list[dict]:
    """Classifie in-place et retourne la liste enrichie."""
    for call in calls:
        call["classified_type"] = classify_call(call)
    return calls


def filter_ucc_calls(calls: list[dict]) -> list[dict]:
    """
    Filtre pour ne garder que les appels pertinents pour l'analyse QA UCC :
    - ucc_handled : appels traités par l'UCC sur la ligne principale
    - warm_transfer : transferts initiés depuis l'UCC (tag escalation)
    Exclut : côté Driveco Care, maintenance, deflector, b2b_direct.
    """
    return [c for c in calls if c.get("classified_type") in UCC_QA_TYPES]


def filter_driveco_calls(calls: list[dict]) -> list[dict]:
    """
    Appels QA côté Driveco Care :
    - ucc_transfer_handled : appels reçus après transfert UCC
    - b2b_direct / driveco_direct : appels pris directement par Driveco
    On garde uniquement les appels décrochés, réellement analysables sur transcript.
    """
    return [
        c for c in calls
        if c.get("classified_type") in DRIVECO_QA_TYPES
        and c.get("answered") == "Yes"
    ]


def filter_qa_calls(calls: list[dict]) -> list[dict]:
    """
    Scope QA global = UCC + Driveco Care, sans doublons.
    """
    ordered = filter_ucc_calls(calls) + filter_driveco_calls(calls)
    seen = set()
    out = []
    for call in ordered:
        call_id = str(call.get("call_id_internal") or call.get("call_id") or "").strip()
        if call_id and call_id in seen:
            continue
        if call_id:
            seen.add(call_id)
        out.append(call)
    return out


def get_quality_scope(classified_type: str | None) -> str | None:
    """
    Retourne le périmètre QA métier pour un type d'appel.
    """
    if classified_type in UCC_QA_TYPES:
        return "ucc"
    if classified_type in DRIVECO_QA_TYPES:
        return "driveco"
    return None
