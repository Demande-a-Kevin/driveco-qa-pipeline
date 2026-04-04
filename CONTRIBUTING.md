# CONTRIBUTING

## Règles de base

- ne pas committer de secrets, de `.env`, de tokens OAuth, ni de rapports générés
- ne pas modifier la logique métier sans expliquer le risque et le gain
- documenter toute nouvelle variable d'environnement dans `.env.example`
- garder `README.md` à jour quand une commande, un chemin ou un prérequis change
- archiver la version précédente dans `archives/` avant modification d'un fichier sensible de setup ou de config

## Workflow recommandé

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install pre-commit detect-secrets
pre-commit install
```

Avant push :

```bash
python -m compileall .
pre-commit run --all-files
```

## Si tu touches aux secrets

- ne jamais coller une vraie valeur dans le repo, même privé
- si un agent a eu accès à un `.env` réel, régénérer les secrets concernés
- mettre à jour `.env.example` si une variable devient obligatoire

## Si tu touches à l'exécution

- vérifier `setup.sh`
- vérifier `setup_cron.sh`
- vérifier `run_daily_test.sh`
- vérifier les chemins par défaut dans `config.py`
