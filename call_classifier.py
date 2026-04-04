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
    - ucc_transfer_handled : appels transférés et traités par Driveco Care
    - warm_transfer : transferts initiés depuis l'UCC (tag escalation)
    Exclut : maintenance, deflector, b2b_direct (hors scope QA UCC).
    """
    ucc_types = {"ucc_handled", "ucc_transfer_handled", "warm_transfer"}
    return [c for c in calls if c.get("classified_type") in ucc_types]
