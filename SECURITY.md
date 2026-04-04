# SECURITY

## Risques identifiés

- un `.env` réel a été visible par un agent IA
- des IDs internes étaient hardcodés dans `config.py`
- il n'y avait pas de garde-fou Git pour éviter un commit de secret

## Action recommandée maintenant

Régénérer au minimum :
- `ANTHROPIC_API_KEY`
- `SLACK_BOT_TOKEN`
- `NOTION_API_KEY`
- toute auth Cloudflare réellement utilisée côté prod
- tout token Google Drive OAuth si un fichier token réel a été exposé
- les credentials Aircall si le `.env` réel contenait `AIRCALL_API_ID` et `AIRCALL_API_TOKEN`

## Ce qui peut attendre

- `CF_ACCOUNT_ID`
- `CF_D1_DATABASE_ID`
- `NOTION_KB_PAGE_ID`
- `NOTION_REPORTS_PAGE_ID`
- `SLACK_CHANNEL_ID`

Ces valeurs sont internes et sensibles d'un point de vue cartographie, mais ce ne sont pas des secrets d'authentification.
