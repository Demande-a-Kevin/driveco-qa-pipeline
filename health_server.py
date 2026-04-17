from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import config
import persistence


def build_health_payload() -> dict:
    latest_run = persistence.fetch_latest_llm_run() or {}
    started_at = latest_run.get("started_at")
    lag_minutes = None
    if started_at:
        try:
            started_dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            lag_minutes = round((datetime.now(timezone.utc) - started_dt).total_seconds() / 60, 1)
        except ValueError:
            lag_minutes = None
    return {
        "status": latest_run.get("status") or "unknown",
        "latest_run": latest_run,
        "lag_minutes": lag_minutes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        payload = build_health_payload()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args):  # noqa: A003
        return


def main() -> None:
    server = HTTPServer(("0.0.0.0", config.HEALTH_PORT), HealthHandler)
    print(f"[health] listening on http://0.0.0.0:{config.HEALTH_PORT}/health")
    server.serve_forever()


if __name__ == "__main__":
    main()
