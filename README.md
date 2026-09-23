# Provixa

Système d'analyse des performances commerciales — application Django avec tableaux de bord (chef de région / commercial), prévisions de ventes par Machine Learning (XGBoost) et gestion multi-agences.

**Démo en ligne : [systemeanalyseperformancescommerciales.onrender.com](https://systemeanalyseperformancescommerciales.onrender.com)**

> La démo tourne sur une base SQLite régénérée avec des données factices à chaque démarrage du serveur : toute action (création, modification, suppression) y est temporaire et disparaît au redémarrage suivant.

## Comptes de démonstration

Affichés directement sur la page de connexion :

| Rôle | Email | Mot de passe |
|---|---|---|
| Chef région | `cdr@mail.com` | `Demo1234!` |
| Commercial | `agatheleroux@example.org` | `Demo1234!` |

## Fonctionnalités

- Tableaux de bord par rôle : chef de région (une agence) et commercial (plusieurs agences)
- Suivi du chiffre d'affaires, des ventes, des produits et des vendeurs, avec comparaison à la semaine précédente
- Détection des produits à rotation lente et des vendeurs inactifs
- Prévisions de ventes à horizon 14 jours (modèle XGBoost) avec répartition par agence/région
- Authentification avec verrouillage anti-bruteforce et formulaire de contact administrateur

## Stack technique

- **Backend** : Django 6
- **Base de données** : SQL Server (production/local) ou SQLite (mode démo)
- **Machine Learning** : XGBoost, pandas, numpy, joblib
- **Frontend** : Bootstrap 5, Chart.js
- **Déploiement** : Render (Gunicorn + WhiteNoise)

## Installation locale

Prérequis : Python 3.12+, SQL Server (Express suffit) avec le pilote ODBC 17.

```bash
python -m venv env
env\Scripts\activate          # Windows
pip install -r requirements.txt

# Configurer provixa/settings.py : HOST de DATABASES vers votre instance SQL Server

python manage.py migrate
python manage.py runserver
```

## Mode démo (SQLite, sans SQL Server)

Pour lancer le projet sans base SQL Server, avec des données générées automatiquement :

```bash
set DJANGO_MODE_DEMO=true      # Windows (PowerShell : $env:DJANGO_MODE_DEMO="true")
python manage.py migrate --run-syncdb
python manage.py init_demo
python manage.py runserver
```

## Déploiement (Render)

- **Build Command** : `pip install -r requirements.txt && python manage.py collectstatic --noinput`
- **Start Command** : `python manage.py migrate --run-syncdb --noinput && python manage.py init_demo && gunicorn provixa.wsgi:application --bind 0.0.0.0:$PORT`
- **Variables d'environnement** : `DJANGO_MODE_DEMO=true`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, `DJANGO_ALLOWED_HOSTS`
