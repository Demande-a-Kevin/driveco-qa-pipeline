"""
d1_client.py — Requête la base Cloudflare D1 via les endpoints du worker.
Utilise l'auth Basic Aircall (API_ID:API_TOKEN) — pas besoin de CF_API_TOKEN séparé.
Worker URL : https://airall-webhook.lecointremaui.workers.dev
"""
import requests
import config

_SESSION = requests.Session()
_SESSION.headers.update({"Authorization": config.CF_WORKER_AUTH})


def _worker_get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{config.CF_WORKER_URL.rstrip('/')}{endpoint}"
    resp = _SESSION.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _worker_post(endpoint: str, json_body: dict) -> dict:
    url = f"{config.CF_WORKER_URL.rstrip('/')}{endpoint}"
    resp = _SESSION.post(url, json=json_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_call_history(ts_from: int, ts_to: int) -> list[dict]:
    """
    Récupère l'historique des appels via /call-history/export.
    Le worker retourne {"columns": [...], "rows": [{col: val, ...}, ...]}.
    ts_from / ts_to : timestamps Unix (secondes).
    """
    data = _worker_get("/call-history/export", params={"from": ts_from, "to": ts_to})
    if isinstance(data, list):
        return data
    # Format columnar du worker : rows est déjà une liste de dicts
    return data.get("rows", data.get("calls", data.get("data", [])))


def fetch_stats(ts_from: int, ts_to: int) -> dict:
    """Récupère les stats agrégées via /stats."""
    return _worker_get("/stats", params={"from": ts_from, "to": ts_to})


def query(sql: str, params: list | None = None) -> list[dict]:
    """
    Exécute une requête SQL SELECT via le worker (endpoint /query).
    Retourne une liste de dicts. Silencieux si l'endpoint n'existe pas.
    """
    try:
        body = {"sql": sql}
        if params:
            body["params"] = params
        data = _worker_post("/query", body)
        if isinstance(data, list):
            return data
        return data.get("rows", data.get("results", []))
    except Exception:
        return []


def execute(sql: str, params: list | None = None) -> bool:
    """
    Exécute une requête SQL INSERT/UPDATE via le worker (endpoint /execute).
    Retourne True si succès. Silencieux si l'endpoint n'existe pas.
    """
    try:
        body = {"sql": sql}
        if params:
            body["params"] = params
        _worker_post("/execute", body)
        return True
    except Exception:
        return False


def health_check() -> bool:
    """Vérifie que le worker répond correctement."""
    try:
        _worker_get("/call-history/health")
        return True
    except Exception:
        return False
