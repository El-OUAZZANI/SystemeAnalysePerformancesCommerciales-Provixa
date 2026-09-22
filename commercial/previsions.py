"""
previsions.py

Pont entre le module ml_prediction (modèle XGBoost déjà entraîné et
validé, voir ml_prediction/comparer_modeles.py et
ml_prediction/model_validationcroisee.py) et l'application Django.

Recharge le modèle sauvegardé (ml_prediction/models/xgboost_model.joblib)
et calcule des prévisions de ventes futures, jour par jour, avec la même
logique récursive que ml_prediction/predire_ventes.py (les prédictions
d'un jour deviennent l'historique pour calculer les lags/moyennes du
jour suivant). Les données d'historique sont lues via l'ORM Django
plutôt que via une connexion pyodbc séparée.

Portée du modèle : il a été entraîné sur les ventes agrégées PAR PRODUIT,
TOUTES AGENCES CONFONDUES (voir ml_prediction/feature_engineering.py :
l'agrégation journalière ne filtre jamais par agence). Pour donner une
prévision à l'échelle d'une agence ou d'une région, on utilise une
approche descendante (« top-down forecasting ») : on prévoit le volume
national, puis on le répartit au prorata du poids historique récent de
l'agence/région dans les ventes totales. C'est une pratique reconnue en
prévision hiérarchique (les agrégats de haut niveau sont plus stables et
mieux estimés que des séries locales avec peu de données), plus fiable
ici qu'un modèle entraîné séparément sur le peu d'historique d'une seule
agence.
"""

import os
from datetime import timedelta

import joblib
import numpy as np
import pandas as pd
from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from .models import LigneVente

MODEL_PATH = os.path.join(settings.BASE_DIR, 'ml_prediction', 'models', 'xgboost_model.joblib')

LAGS = [1, 7, 14, 28]
FENETRES_ROULANTES = [7, 14, 28]

HORIZON_PAR_DEFAUT = 14
CACHE_TTL_SECONDES = 3600  # 1h : recalcul coûteux (relit tout l'historique + boucle jour par jour)
JOURS_REFERENCE_POIDS = 60  # période récente utilisée pour estimer le poids d'une agence/région

_modele_bundle = None


def _charger_modele():
    global _modele_bundle
    if _modele_bundle is None:
        _modele_bundle = joblib.load(MODEL_PATH)
    return _modele_bundle


# ============================================================
# HISTORIQUE (national, tous produits/toutes agences)
# ============================================================

def _historique_quotidien_par_produit():
    """Quantité vendue par jour et par produit, TOUTES agences confondues,
    avec une ligne par jour même sans vente (0) — même logique que
    feature_engineering.agreger_par_jour_produit + completer_jours_manquants,
    mais sans le prix (non utilisé par les features du modèle)."""
    lignes = LigneVente.objects.select_related('id_vente').values_list(
        'id_vente__date_vente', 'id_produit_id', 'quantite'
    )
    df = pd.DataFrame(list(lignes), columns=['date_vente', 'id_produit', 'quantite'])
    df['date_vente'] = pd.to_datetime(df['date_vente']).dt.normalize()

    agg = df.groupby(['date_vente', 'id_produit'])['quantite'].sum().reset_index()

    date_min, date_max = agg['date_vente'].min(), agg['date_vente'].max()
    toutes_dates = pd.date_range(date_min, date_max, freq='D')
    produits = agg['id_produit'].unique()
    index_complet = pd.MultiIndex.from_product([toutes_dates, produits], names=['date_vente', 'id_produit'])

    complet = (
        agg.set_index(['date_vente', 'id_produit'])
        .reindex(index_complet, fill_value=0)
        .reset_index()
    )
    return complet


def _construire_features_jour(date, historiques):
    lignes = []
    for id_produit, serie in historiques.items():
        ligne = {'date_vente': date, 'id_produit': id_produit}
        for lag in LAGS:
            ligne[f'lag_{lag}'] = serie[-lag] if len(serie) >= lag else 0
        for fenetre in FENETRES_ROULANTES:
            valeurs = serie[-fenetre:]
            ligne[f'rolling_mean_{fenetre}'] = float(np.mean(valeurs)) if valeurs else 0.0
            ligne[f'rolling_std_{fenetre}'] = float(np.std(valeurs, ddof=1)) if len(valeurs) >= 2 else 0.0
        lignes.append(ligne)

    df_jour = pd.DataFrame(lignes)
    df_jour['jour_semaine'] = date.weekday()
    df_jour['est_weekend'] = int(date.weekday() in (5, 6))
    df_jour['jour_mois'] = date.day
    df_jour['mois'] = date.month
    df_jour['trimestre'] = (date.month - 1) // 3 + 1
    df_jour['semaine_annee'] = date.isocalendar()[1]
    df_jour['jour_annee'] = date.timetuple().tm_yday
    df_jour['est_debut_mois'] = int(date.day <= 5)
    df_jour['est_fin_mois'] = int(date.day >= 25)
    return df_jour


def _previsions_recursives(horizon):
    bundle = _charger_modele()
    features = bundle['features']
    model = bundle['model']

    df_historique = _historique_quotidien_par_produit()
    date_depart = df_historique['date_vente'].max()

    historiques = {
        id_produit: list(groupe.sort_values('date_vente')['quantite'])
        for id_produit, groupe in df_historique.groupby('id_produit')
    }

    toutes_predictions = []
    for i in range(1, horizon + 1):
        date_jour = date_depart + pd.Timedelta(days=i)
        df_jour = _construire_features_jour(date_jour, historiques)

        X = df_jour[features].fillna(0)
        y_pred = np.clip(model.predict(X), a_min=0, a_max=None)
        df_jour['quantite_predite'] = np.round(y_pred).astype(int)

        toutes_predictions.append(df_jour[['date_vente', 'id_produit', 'quantite_predite']])
        for id_produit, quantite in zip(df_jour['id_produit'], df_jour['quantite_predite']):
            historiques[id_produit].append(quantite)

    return pd.concat(toutes_predictions, ignore_index=True), date_depart


def obtenir_prevision_globale(horizon=HORIZON_PAR_DEFAUT):
    """Prévision NATIONALE (toutes agences), mise en cache : coûteuse à
    recalculer (relit tout l'historique + une boucle jour par jour)."""
    cle = f"prevision_globale_v1_h{horizon}"
    donnees = cache.get(cle)
    if donnees is not None:
        return donnees

    df_predictions, date_depart = _previsions_recursives(horizon)

    par_jour = (
        df_predictions.groupby('date_vente')['quantite_predite']
        .sum()
        .reset_index()
        .sort_values('date_vente')
    )
    par_produit = (
        df_predictions.groupby('id_produit')['quantite_predite']
        .sum()
        .sort_values(ascending=False)
    )

    donnees = {
        'date_depart': date_depart,
        'par_jour': par_jour,
        'par_produit': par_produit,
        'total_horizon': int(par_jour['quantite_predite'].sum()),
    }
    cache.set(cle, donnees, CACHE_TTL_SECONDES)
    return donnees


# ============================================================
# RÉPARTITION PAR PÉRIMÈTRE (agence / région) — top-down forecasting
# ============================================================

def _poids_historique(filtre_ventes, jours=JOURS_REFERENCE_POIDS):
    """Part (0-1) des ventes nationales (en quantité) attribuable à ce
    périmètre, sur les `jours` derniers jours — sert à répartir la
    prévision nationale au prorata."""
    depuis = timezone.now() - timedelta(days=jours)

    quantite_perimetre = LigneVente.objects.filter(
        id_vente__date_vente__gte=depuis, **filtre_ventes
    ).aggregate(total=Sum('quantite'))['total'] or 0

    quantite_nationale = LigneVente.objects.filter(
        id_vente__date_vente__gte=depuis
    ).aggregate(total=Sum('quantite'))['total'] or 0

    if not quantite_nationale:
        return 0.0
    return quantite_perimetre / quantite_nationale


def obtenir_prevision_perimetre(filtre_ventes, horizon=HORIZON_PAR_DEFAUT):
    """
    Prévision pour un périmètre restreint (agence ou région), dérivée de
    la prévision nationale au prorata du poids historique récent de ce
    périmètre (voir docstring du module).
    `filtre_ventes` : kwargs ORM appliqués à LigneVente, ex.
    {'id_vente__id_agence': agence} ou {'id_vente__id_agence__id_region_id': id_region}.
    """
    globale = obtenir_prevision_globale(horizon)
    poids = _poids_historique(filtre_ventes)

    par_jour = globale['par_jour'].copy()
    par_jour['quantite_predite'] = (par_jour['quantite_predite'] * poids).round().astype(int)

    par_produit = (globale['par_produit'] * poids).round().astype(int)
    par_produit = par_produit[par_produit > 0].sort_values(ascending=False)

    return {
        'date_depart': globale['date_depart'],
        'poids_perimetre': poids,
        'par_jour': par_jour,
        'par_produit': par_produit,
        'total_horizon': int(par_jour['quantite_predite'].sum()),
    }
