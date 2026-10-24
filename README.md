# Momentum Trader

Application Django de trading algorithmique : stratégie momentum 12-1 sur un univers de 50 actions du S&P 500, données de marché via Massive, exécution des ordres sur Alpaca via SnapTrade.

## Démarrage

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
Copy-Item .env.example .env   # puis renseigner les clés
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py create_default_superuser
.venv\Scripts\python.exe manage.py backfill_data   # ~10 min (limite Massive : 5 req/min)
.venv\Scripts\python.exe manage.py runserver
```

- Application : http://localhost:8000
- Admin : http://localhost:8000/admin (identifiants `ADMIN_*` du `.env`)

## Structure

```
momentum_trader/        configuration Django (settings, urls)
trading/                actions, prix, scores momentum, signaux, rééquilibrages
  services/
    massive_client.py       données de marché (cache, rate limit, grouped_daily)
    momentum_calculator.py  momentum 12-1, quintiles, univers d'actions
    snaptrade_client.py     OAuth SnapTrade, sync des positions, ordres
    strategy_engine.py      signaux et rééquilibrage
  management/commands/
    backfill_data.py              historique de prix + scores momentum
    create_default_superuser.py   super-utilisateur local
portfolio/              portefeuilles, positions, trades, métriques
templates/              base.html, trading/, portfolio/
```

## Pages

| URL | Page |
| --- | --- |
| `/` | Dashboard (top/bottom 10, rééquilibrages, portefeuilles) |
| `/momentum/` | Scores momentum par date de calcul |
| `/signals/` | Signaux de trading (filtre `?type=buy` / `?type=sell`) |
| `/portfolios/` | Portefeuilles, création en 3 étapes avec connexion SnapTrade |

## Variables d'environnement

Voir `.env.example`. Avec une clé SnapTrade **Personal** (client id `PERS-…`), l'API ne permet pas d'enregistrer d'utilisateur : renseigner alors `SNAPTRADE_USER_ID` et `SNAPTRADE_USER_SECRET`.

## Tests

```powershell
.venv\Scripts\python.exe manage.py test
```
