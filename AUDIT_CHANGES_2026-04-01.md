# Audit Changes 2026-04-01

Corrections appliquées dans cette copie de travail :

- `.gitignore` durci pour caches Python, fichiers de couverture, variantes `.env`, fichiers VS Code et baseline de scan de secrets
- `.env.example` complété avec toutes les variables lues par `config.py`
- `.env.template` réaligné sur `.env.example` pour éviter une doc contradictoire
- `config.py` nettoyé des IDs hardcodés et des chemins implicites vers `Claude`
- `requirements.txt` complété avec `pytz`, import optionnel réel du code
- `setup.sh` rendu reproductible avec `.venv`, `.env.example` et logs repo-locaux
- `setup_cron.sh` aligné avec `.venv` et `qa-driveco-data/logs`
- `run_daily_test.sh` rendu portable, avec date par défaut = hier
- `README.md` réécrit pour qu'un tiers puisse installer, configurer et lancer le pipeline
- `CONTRIBUTING.md` ajouté pour les futurs contributeurs
- `SECURITY.md` ajouté avec la marche à suivre de rotation de secrets
- `.pre-commit-config.yaml` ajouté pour limiter les commits accidentels de secrets
- `.github/workflows/ci.yml` ajouté pour vérifier install + imports + compilation
- `.github/ISSUE_TEMPLATE/bug_report.md` ajouté
- `.vscode/extensions.json` ajouté pour outillage minimal

Archive des versions remplacées :
- `archives/2026-04-01-pre-audit/`
