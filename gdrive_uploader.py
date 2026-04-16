"""
gdrive_uploader.py — Upload de fichiers vers Google Drive.
Premier lancement : ouvre une page web pour auth OAuth2 (une seule fois).
Token ensuite mis en cache dans gdrive_token.json.

Dossier cible : UCC AircallQuality Analysis (ID configuré dans .env)
"""
import os
import json
from pathlib import Path
from datetime import datetime

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False

import config

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Sous-dossiers dans Google Drive par type de rapport
SUBFOLDER_NAMES = {
    "daily":   "Rapports quotidiens",
    "weekly":  "Rapports hebdomadaires",
    "monthly": "Rapports mensuels",
    "benchmark": "Benchmarks Ollama",
    "logs":    "Logs",
}


def _get_service():
    """Retourne un service Drive authentifié. Lance le flow OAuth si nécessaire."""
    creds = None
    token_path = Path(config.GDRIVE_TOKEN_FILE)
    creds_path = Path(config.GDRIVE_CREDENTIALS_FILE)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                print(f"[gdrive] ⚠️  Fichier credentials manquant : {creds_path}")
                print("         Télécharge-le depuis Google Cloud Console → APIs & Services → Credentials")
                print("         et place-le à cet emplacement.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def _get_or_create_subfolder(service, parent_id: str, folder_name: str) -> str:
    """Retourne l'ID d'un sous-dossier (le crée s'il n'existe pas)."""
    q = (
        f"'{parent_id}' in parents "
        f"and name = '{folder_name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    results = service.files().list(q=q, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def upload_report(file_path: Path, report_type: str = "daily") -> str | None:
    """
    Upload un rapport Markdown vers Google Drive.
    Retourne l'URL du fichier uploadé, ou None si échec.
    """
    if config.DISABLE_EXTERNAL_PUBLISH:
        print("[gdrive] ℹ️  Upload Drive désactivé par config")
        return None
    if not GDRIVE_AVAILABLE:
        print("[gdrive] ❌ google-api-python-client non installé — skipping Drive upload")
        return None

    service = _get_service()
    if not service:
        return None

    try:
        parent_id = config.GDRIVE_FOLDER_ID
        subfolder_name = SUBFOLDER_NAMES.get(report_type, "Autres")
        subfolder_id = _get_or_create_subfolder(service, parent_id, subfolder_name)

        file_metadata = {
            "name": file_path.name,
            "parents": [subfolder_id],
        }
        media = MediaFileUpload(str(file_path), mimetype="text/markdown", resumable=False)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        link = uploaded.get("webViewLink", "")
        print(f"[gdrive] ✅ Uploadé → {link}")
        return link

    except Exception as e:
        print(f"[gdrive] ❌ Erreur upload : {e}")
        return None


def upload_log(log_path: Path) -> str | None:
    """Upload un fichier de log vers le sous-dossier Logs."""
    return upload_report(log_path, report_type="logs")
