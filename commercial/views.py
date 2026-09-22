from datetime import timedelta
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.http import Http404, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Sum, Count, Max, F
from django.urls import reverse
from django.utils import timezone
import json

SEUIL_ROTATION_LENTE_JOURS = 14

MAX_TENTATIVES_CONNEXION = 5
FENETRE_BLOCAGE_CONNEXION_SECONDES = 15 * 60  # 15 minutes

# Comptes affichés comme suggestion sur la page de connexion, uniquement en
# mode DEBUG (jamais en production) : mot de passe fixe pour faciliter les
# démos locales. Voir aussi le script de réinitialisation dans admin.py.
COMPTES_DEMO = [
    {'role': 'Chef région', 'email': 'cdr@mail.com', 'mot_de_passe': 'Demo1234!'},
    {'role': 'Commercial', 'email': 'agatheleroux@example.org', 'mot_de_passe': 'Demo1234!'},
]

from .models import (
    Agence, Categorie, ChefRegion, ChefRegionPermission, Client, Commercial,
    CommercialPermissionAgence, LigneVente, Produit, Signalement, Utilisateur, Vendeur, Vente,
)
from .previsions import HORIZON_PAR_DEFAUT, obtenir_prevision_perimetre


# ============================================================
# Authentification (session simple : id_utilisateur stocké côté serveur)
# ============================================================

def rediriger_selon_role(id_utilisateur):
    """Renvoie la page d'accueil adaptée au rôle de cet utilisateur connecté."""
    if ChefRegion.objects.filter(id_chef_region_id=id_utilisateur).exists():
        return redirect('commercial:dashboard_chef_region')
    if Commercial.objects.filter(id_commercial_id=id_utilisateur).exists():
        return redirect('commercial:vue_ensemble_commercial')
    return redirect('commercial:connexion')


def obtenir_ip_client(request):
    return request.META.get('REMOTE_ADDR', 'inconnu')


def vue_connexion(request):
    if request.session.get('id_utilisateur'):
        return rediriger_selon_role(request.session['id_utilisateur'])

    suivant = request.GET.get('next') or request.POST.get('next', '')
    erreur = None
    email_saisi = ''
    erreur_contact = None
    confirmation_contact = None

    if request.method == 'POST' and request.POST.get('form') == 'contact_admin':
        email_contact = request.POST.get('email_contact', '').strip()
        message_contact = request.POST.get('message_contact', '').strip()

        if not email_contact or not message_contact:
            erreur_contact = "Merci de renseigner votre email et de décrire le problème rencontré."
        else:
            utilisateur = Utilisateur.objects.filter(email__iexact=email_contact).first()
            if utilisateur:
                Signalement.objects.create(
                    utilisateur=utilisateur,
                    message=f"[Problème de connexion] {message_contact}",
                )
            # Message volontairement identique que l'email existe ou non,
            # pour ne pas révéler si un compte existe avec cette adresse.
            confirmation_contact = (
                "Si un compte existe avec cet email, votre message a été transmis à "
                "l'administrateur. Vous serez recontacté prochainement."
            )

    elif request.method == 'POST':
        email_saisi = request.POST.get('email', '').strip()
        mot_de_passe = request.POST.get('mot_de_passe', '')

        cle_blocage = f"connexion_echecs:{obtenir_ip_client(request)}"
        nb_echecs = cache.get(cle_blocage, 0)

        if nb_echecs >= MAX_TENTATIVES_CONNEXION:
            erreur = "Trop de tentatives de connexion. Réessayez dans quelques minutes."
        else:
            utilisateur = Utilisateur.objects.filter(email__iexact=email_saisi).first()
            if not utilisateur or not check_password(mot_de_passe, utilisateur.password):
                cache.set(cle_blocage, nb_echecs + 1, FENETRE_BLOCAGE_CONNEXION_SECONDES)
                erreur = "Email ou mot de passe incorrect."
            elif not utilisateur.actif:
                erreur = "Ce compte est désactivé. Contactez un administrateur."
            else:
                cache.delete(cle_blocage)
                request.session.cycle_key()  # évite la fixation de session : nouvel ID après connexion
                request.session['id_utilisateur'] = utilisateur.id_utilisateur
                if suivant:
                    return redirect(suivant)
                return rediriger_selon_role(utilisateur.id_utilisateur)

    return render(request, 'commercial/connexion.html', {
        'erreur': erreur,
        'email_saisi': email_saisi,
        'next': suivant,
        'erreur_contact': erreur_contact,
        'confirmation_contact': confirmation_contact,
        'comptes_demo': COMPTES_DEMO if settings.DEBUG else None,
    })


def vue_deconnexion(request):
    request.session.flush()
    return redirect('commercial:connexion')


def connexion_chef_region_requise(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        id_utilisateur = request.session.get('id_utilisateur')
        if not id_utilisateur:
            return redirect(f"{reverse('commercial:connexion')}?next={request.path}")
        if not ChefRegion.objects.filter(id_chef_region_id=id_utilisateur).exists():
            if Commercial.objects.filter(id_commercial_id=id_utilisateur).exists():
                return redirect('commercial:vue_ensemble_commercial')
            return redirect('commercial:connexion')
        if not ChefRegionPermission.objects.filter(id_chef_region_id=id_utilisateur).exists():
            # Compte Chef région valide mais sans agence assignée (cas anormal,
            # ex. agence retirée par l'admin) : on évite le plantage plus loin
            # dans la vue et on renvoie un message clair plutôt qu'une 500.
            request.session.flush()
            messages.error(
                request,
                "Votre compte n'est associé à aucune agence. Contactez l'administrateur.",
            )
            return redirect('commercial:connexion')
        return view_func(request, *args, **kwargs)
    return wrapper


def connexion_commercial_requise(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        id_utilisateur = request.session.get('id_utilisateur')
        if not id_utilisateur:
            return redirect(f"{reverse('commercial:connexion')}?next={request.path}")
        if not Commercial.objects.filter(id_commercial_id=id_utilisateur).exists():
            if ChefRegion.objects.filter(id_chef_region_id=id_utilisateur).exists():
                return redirect('commercial:dashboard_chef_region')
            return redirect('commercial:connexion')
        return view_func(request, *args, **kwargs)
    return wrapper


def get_chef_region_connecte(request):
    return get_object_or_404(ChefRegion, id_chef_region_id=request.session.get('id_utilisateur'))


def get_commercial_connecte(request):
    return get_object_or_404(Commercial, id_commercial_id=request.session.get('id_utilisateur'))


def get_agences_commercial(commercial):
    """Agences assignées à ce commercial, triées par nom."""
    return Agence.objects.filter(
        commercialpermissionagence__id_commercial=commercial
    ).select_related('id_region').order_by('nom_agence')


def calcule_tendance(valeur_actuelle, valeur_precedente):
    """Retourne un pourcentage d'évolution (positif ou négatif), ou None si non calculable."""
    if valeur_precedente in (0, None):
        return None
    return round((valeur_actuelle - valeur_precedente) / valeur_precedente * 100)


def date_reference():
    """
    Ancre les périodes ("cette semaine", "30 derniers jours"...) sur la date de la
    dernière vente enregistrée plutôt que sur la date système : si la base ne
    contient pas encore les ventes des jours les plus récents, on évite un
    graphique/KPI vide côté "aujourd'hui" qui n'a simplement pas de données.
    """
    derniere_date = Vente.objects.aggregate(Max('date_vente'))['date_vente__max']
    return derniere_date or timezone.now()


def construire_kpis_agence(agence):
    """
    Calcule toutes les données du dashboard (KPIs semaine, tendance 30j, tops,
    rotation lente) pour une agence donnée. Réutilisé par le dashboard du Chef
    de région (une seule agence, la sienne) et celui du Commercial (une agence
    choisie parmi celles qui lui sont assignées).
    """
    # --- Période : cette semaine (lundi à aujourd'hui) ---
    aujourd_hui = date_reference()
    # Lundi 00:00 (et non "maintenant moins N jours", qui décale l'heure de
    # début — un bug qui rendait "cette semaine" quasi vide chaque lundi,
    # puisque la borne tombait alors exactement sur l'instant présent).
    debut_semaine = aujourd_hui.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=aujourd_hui.weekday())
    debut_semaine_precedente = debut_semaine - timedelta(days=7)

    ventes_semaine = Vente.objects.filter(id_agence=agence, date_vente__gte=debut_semaine)
    ventes_semaine_precedente = Vente.objects.filter(
        id_agence=agence,
        date_vente__gte=debut_semaine_precedente,
        date_vente__lt=debut_semaine,
    )

    # --- KPI 1 : quantité totale vendue (unités) ---
    quantite_totale = LigneVente.objects.filter(
        id_vente__in=ventes_semaine
    ).aggregate(total=Sum('quantite'))['total'] or 0

    quantite_precedente = LigneVente.objects.filter(
        id_vente__in=ventes_semaine_precedente
    ).aggregate(total=Sum('quantite'))['total'] or 0

    tendance_quantite = calcule_tendance(quantite_totale, quantite_precedente)

    # --- KPI 1bis : chiffre d'affaires de la semaine ---
    ca_semaine = LigneVente.objects.filter(
        id_vente__in=ventes_semaine
    ).aggregate(total=Sum(F('prix_unitaire') * F('quantite')))['total'] or 0

    ca_semaine_precedente = LigneVente.objects.filter(
        id_vente__in=ventes_semaine_precedente
    ).aggregate(total=Sum(F('prix_unitaire') * F('quantite')))['total'] or 0

    tendance_ca = calcule_tendance(ca_semaine, ca_semaine_precedente)

    # --- KPI 2 : vendeurs actifs (+ combien ont vendu cette semaine, engagement réel) ---
    nb_vendeurs_actifs = Vendeur.objects.filter(id_agence=agence, actif=True).count()
    nb_vendeurs_engages_semaine = (
        ventes_semaine.values('id_vendeur').distinct().count()
    )

    # --- KPI 3 : clients actifs (+ combien ont été desservis cette semaine) ---
    nb_clients_actifs = Client.objects.filter(id_agence=agence, actif=True).count()
    nb_clients_desservis_semaine = (
        ventes_semaine.values('id_client').distinct().count()
    )

    # --- KPI 4 : nombre de ventes (transactions) cette semaine ---
    nb_ventes_semaine = ventes_semaine.count()
    nb_ventes_semaine_precedente = ventes_semaine_precedente.count()
    tendance_ventes = calcule_tendance(nb_ventes_semaine, nb_ventes_semaine_precedente)

    # --- Tendance générale : quantité vendue ET CA par jour, 30 derniers jours (sans trous) ---
    debut_periode = (aujourd_hui - timedelta(days=29)).date()
    fin_periode = aujourd_hui.date()

    jours_fr = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    mois_fr = [
        'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
        'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
    ]
    date_aujourdhui_fr = (
        f"{jours_fr[aujourd_hui.weekday()]} {aujourd_hui.day} "
        f"{mois_fr[aujourd_hui.month - 1]} {aujourd_hui.year}"
    )

    quantites_par_jour = {}
    ca_par_jour = {}
    jour_courant = debut_periode
    while jour_courant <= fin_periode:
        quantites_par_jour[jour_courant] = 0
        ca_par_jour[jour_courant] = 0.0
        jour_courant += timedelta(days=1)

    lignes_30j = LigneVente.objects.filter(
        id_vente__id_agence=agence,
        id_vente__date_vente__date__gte=debut_periode,
    ).select_related('id_vente')

    for ligne in lignes_30j:
        jour = ligne.id_vente.date_vente.date()
        if jour in quantites_par_jour:
            quantites_par_jour[jour] += ligne.quantite
            ca_par_jour[jour] += float(ligne.prix_unitaire) * ligne.quantite

    jours_tries = sorted(quantites_par_jour.keys())
    labels_graphique = [j.strftime('%d/%m') for j in jours_tries]
    labels_graphique_complet = [f"{jours_fr[j.weekday()]} {j.strftime('%d/%m/%Y')}" for j in jours_tries]
    valeurs_graphique = [quantites_par_jour[j] for j in jours_tries]
    valeurs_graphique_ca = [round(ca_par_jour[j], 2) for j in jours_tries]

    # --- Top 5 vendeurs de la semaine (par quantité vendue) ---
    top_vendeurs_qs = (
        LigneVente.objects.filter(id_vente__in=ventes_semaine)
        .values(
            'id_vente__id_vendeur__id_vendeur',
            'id_vente__id_vendeur__nom_vendeur',
            'id_vente__id_vendeur__prenom_vendeur',
        )
        .annotate(total_quantite=Sum('quantite'))
        .order_by('-total_quantite')[:5]
    )
    max_quantite_vendeur = max([v['total_quantite'] for v in top_vendeurs_qs], default=1)
    top_vendeurs = [
        {
            'nom': f"{v['id_vente__id_vendeur__prenom_vendeur'] or ''} {v['id_vente__id_vendeur__nom_vendeur']}".strip(),
            'quantite': v['total_quantite'],
            'pourcentage': round(v['total_quantite'] / max_quantite_vendeur * 100),
        }
        for v in top_vendeurs_qs
    ]

    # --- Top 5 produits de la semaine (par quantité vendue) ---
    top_produits_qs = (
        LigneVente.objects.filter(id_vente__in=ventes_semaine)
        .values('id_produit__id_produit', 'id_produit__nom_produit')
        .annotate(total_quantite=Sum('quantite'))
        .order_by('-total_quantite')[:5]
    )
    max_quantite_produit = max([p['total_quantite'] for p in top_produits_qs], default=1)
    top_produits = [
        {
            'nom': p['id_produit__nom_produit'],
            'quantite': p['total_quantite'],
            'pourcentage': round(p['total_quantite'] / max_quantite_produit * 100),
        }
        for p in top_produits_qs
    ]

    # --- Produits à rotation lente : produits actifs sans vente depuis SEUIL_ROTATION_LENTE_JOURS jours ---
    seuil_rotation_lente = aujourd_hui - timedelta(days=SEUIL_ROTATION_LENTE_JOURS)

    dernieres_ventes_par_produit = dict(
        LigneVente.objects.filter(id_vente__id_agence=agence)
        .values('id_produit')
        .annotate(derniere_vente=Max('id_vente__date_vente'))
        .values_list('id_produit', 'derniere_vente')
    )

    produits_rotation_lente = []
    for produit in Produit.objects.filter(actif=True):
        derniere_vente = dernieres_ventes_par_produit.get(produit.id_produit)
        if derniere_vente is None:
            produits_rotation_lente.append({
                'nom_produit': produit.nom_produit,
                'jamais_vendu': True,
                'jours_inactif': None,
            })
        elif derniere_vente < seuil_rotation_lente:
            produits_rotation_lente.append({
                'nom_produit': produit.nom_produit,
                'jamais_vendu': False,
                'jours_inactif': (aujourd_hui - derniere_vente).days,
            })

    # Les jamais-vendus d'abord, puis du plus inactif au moins inactif
    produits_rotation_lente.sort(
        key=lambda p: p['jours_inactif'] if p['jours_inactif'] is not None else float('inf'),
        reverse=True,
    )
    produits_rotation_lente = produits_rotation_lente[:8]

    return {
        'agence': agence,
        'date_aujourdhui_fr': date_aujourdhui_fr,
        'quantite_totale': quantite_totale,
        'tendance_quantite': tendance_quantite,
        'ca_semaine': ca_semaine,
        'tendance_ca': tendance_ca,
        'nb_vendeurs_actifs': nb_vendeurs_actifs,
        'nb_vendeurs_engages_semaine': nb_vendeurs_engages_semaine,
        'nb_clients_actifs': nb_clients_actifs,
        'nb_clients_desservis_semaine': nb_clients_desservis_semaine,
        'nb_ventes_semaine': nb_ventes_semaine,
        'tendance_ventes': tendance_ventes,
        'labels_graphique': labels_graphique,
        'labels_graphique_complet': labels_graphique_complet,
        'valeurs_graphique': valeurs_graphique,
        'valeurs_graphique_ca': valeurs_graphique_ca,
        'top_vendeurs': top_vendeurs,
        'top_produits': top_produits,
        'produits_rotation_lente': produits_rotation_lente,
        'seuil_rotation_lente_jours': SEUIL_ROTATION_LENTE_JOURS,
    }


@connexion_chef_region_requise
def dashboard_chef_region(request):
    chef_region = get_chef_region_connecte(request)
    agence = chef_region.chefregionpermission.id_agence

    contexte = construire_kpis_agence(agence)
    contexte.update({
        'chef_region': chef_region,
        'section_active': 'dashboard',
        'url_actualisation': reverse('commercial:dashboard_chef_region_data'),
    })
    return render(request, 'commercial/chef_region/dashboard.html', contexte)


@connexion_chef_region_requise
def dashboard_chef_region_data(request):
    """
    Version JSON de dashboard_chef_region : mêmes données (construire_kpis_agence),
    sans rendu HTML. Utilisée par le JS du dashboard pour s'actualiser
    automatiquement sans recharger la page.
    """
    chef_region = get_chef_region_connecte(request)
    agence = chef_region.chefregionpermission.id_agence
    donnees = construire_kpis_agence(agence)
    donnees.pop('agence', None)  # instance de modèle, non sérialisable en JSON
    return JsonResponse(donnees)


def construire_donnees_vendeurs(vendeurs_qs):
    """
    Calcule les données de performance (quantité, CA, tendance, inactivité) pour
    un ensemble de vendeurs donné. Réutilisé pour la portée région (Chef de
    région) et la portée agence unique (Commercial).
    """
    aujourd_hui = date_reference()
    # Lundi 00:00 (et non "maintenant moins N jours", qui décale l'heure de
    # début — un bug qui rendait "cette semaine" quasi vide chaque lundi,
    # puisque la borne tombait alors exactement sur l'instant présent).
    debut_semaine = aujourd_hui.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=aujourd_hui.weekday())
    debut_semaine_precedente = debut_semaine - timedelta(days=7)
    debut_periode_30j = aujourd_hui - timedelta(days=30)

    quantites_semaine = {
        v['id_vente__id_vendeur']: v['total']
        for v in LigneVente.objects.filter(
            id_vente__id_vendeur__in=vendeurs_qs,
            id_vente__date_vente__gte=debut_semaine,
        ).values('id_vente__id_vendeur').annotate(total=Sum('quantite'))
    }

    quantites_semaine_precedente = {
        v['id_vente__id_vendeur']: v['total']
        for v in LigneVente.objects.filter(
            id_vente__id_vendeur__in=vendeurs_qs,
            id_vente__date_vente__gte=debut_semaine_precedente,
            id_vente__date_vente__lt=debut_semaine,
        ).values('id_vente__id_vendeur').annotate(total=Sum('quantite'))
    }

    # --- CA généré cette semaine, par vendeur ---
    ca_semaine_par_vendeur = {
        v['id_vente__id_vendeur']: v['total_ca']
        for v in LigneVente.objects.filter(
            id_vente__id_vendeur__in=vendeurs_qs,
            id_vente__date_vente__gte=debut_semaine,
        ).values('id_vente__id_vendeur').annotate(
            total_ca=Sum(F('prix_unitaire') * F('quantite'))
        )
    }

    clients_desservis = {
        v['id_vendeur']: v['nb_clients']
        for v in Vente.objects.filter(
            id_vendeur__in=vendeurs_qs,
            date_vente__gte=debut_periode_30j,
        ).values('id_vendeur').annotate(nb_clients=Count('id_client', distinct=True))
    }

    # --- Vendeurs inactifs : dernière vente (toutes dates confondues) par vendeur ---
    seuil_inactivite = aujourd_hui - timedelta(days=SEUIL_ROTATION_LENTE_JOURS)
    dernieres_ventes_par_vendeur = dict(
        Vente.objects.filter(id_vendeur__in=vendeurs_qs)
        .values('id_vendeur')
        .annotate(derniere_vente=Max('date_vente'))
        .values_list('id_vendeur', 'derniere_vente')
    )

    vendeurs_data = []
    for vendeur in vendeurs_qs:
        quantite = quantites_semaine.get(vendeur.id_vendeur, 0)
        quantite_precedente = quantites_semaine_precedente.get(vendeur.id_vendeur, 0)

        derniere_vente = dernieres_ventes_par_vendeur.get(vendeur.id_vendeur)
        jamais_vendu = derniere_vente is None
        jours_inactif = None if jamais_vendu else (aujourd_hui - derniere_vente).days
        inactif = vendeur.actif and (jamais_vendu or derniere_vente < seuil_inactivite)

        vendeurs_data.append({
            'id_vendeur': vendeur.id_vendeur,
            'nom_complet': f"{vendeur.prenom_vendeur or ''} {vendeur.nom_vendeur}".strip(),
            'agence': vendeur.id_agence.nom_agence if vendeur.id_agence else '—',
            'id_agence': vendeur.id_agence_id,
            'type_vendeur': vendeur.id_type_vendeur.libelle_type_vendeur,
            'actif': vendeur.actif,
            'quantite_semaine': quantite,
            'tendance': calcule_tendance(quantite, quantite_precedente),
            'ca_semaine': ca_semaine_par_vendeur.get(vendeur.id_vendeur, 0),
            'nb_clients': clients_desservis.get(vendeur.id_vendeur, 0),
            'inactif': inactif,
            'jamais_vendu': jamais_vendu,
            'jours_inactif': jours_inactif,
        })

    vendeurs_data.sort(key=lambda v: v['quantite_semaine'], reverse=True)
    return vendeurs_data


@connexion_chef_region_requise
def liste_vendeurs_chef_region(request):
    chef_region = get_chef_region_connecte(request)
    agence_chef = chef_region.chefregionpermission.id_agence
    id_region = agence_chef.id_region_id

    vendeurs_qs = Vendeur.objects.filter(
        id_agence__id_region_id=id_region
    ).select_related('id_agence', 'id_type_vendeur')

    vendeurs_data = construire_donnees_vendeurs(vendeurs_qs)
    agences_region = Agence.objects.filter(id_region_id=id_region)

    context = {
        'chef_region': chef_region,
        'vendeurs_data': vendeurs_data,
        'agences_region': agences_region,
        'seuil_rotation_lente_jours': SEUIL_ROTATION_LENTE_JOURS,
        'section_active': 'vendeurs',
    }
    return render(request, 'commercial/chef_region/vendeurs.html', context)


def construire_donnees_produits(filtre_ventes):
    """
    Calcule les données de performance produit (quantité, CA, tendance, rotation
    lente, séries 30j) pour une portée de ventes donnée.
    `filtre_ventes` est un dict de kwargs ORM appliqué à LigneVente/Vente
    (ex: {'id_vente__id_agence__id_region_id': id_region} pour toute une région,
    ou {'id_vente__id_agence': agence} pour une seule agence).
    Réutilisé par le Chef de région (portée région) et le Commercial (portée agence).
    """
    # --- Produits communs (catalogue global, pas de rattachement à une agence) ---
    produits = Produit.objects.filter(actif=True).select_related('id_categorie')

    aujourd_hui = date_reference()
    # Lundi 00:00 (et non "maintenant moins N jours", qui décale l'heure de
    # début — un bug qui rendait "cette semaine" quasi vide chaque lundi,
    # puisque la borne tombait alors exactement sur l'instant présent).
    debut_semaine = aujourd_hui.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=aujourd_hui.weekday())
    debut_semaine_precedente = debut_semaine - timedelta(days=7)
    debut_periode_30j = aujourd_hui - timedelta(days=30)

    lignes_semaine = LigneVente.objects.filter(
        id_vente__date_vente__gte=debut_semaine, **filtre_ventes
    )
    lignes_semaine_precedente = LigneVente.objects.filter(
        id_vente__date_vente__gte=debut_semaine_precedente,
        id_vente__date_vente__lt=debut_semaine,
        **filtre_ventes,
    )
    lignes_30j = LigneVente.objects.filter(
        id_vente__date_vente__gte=debut_periode_30j, **filtre_ventes
    )

    # --- Quantité vendue cette semaine, par produit ---
    quantites_semaine = {
        l['id_produit']: l['total']
        for l in lignes_semaine.values('id_produit').annotate(total=Sum('quantite'))
    }

    # --- Quantité vendue semaine précédente, par produit (pour la tendance) ---
    quantites_semaine_precedente = {
        l['id_produit']: l['total']
        for l in lignes_semaine_precedente.values('id_produit').annotate(total=Sum('quantite'))
    }

    # --- Chiffre d'affaires cette semaine, par produit ---
    # IMPORTANT : on utilise LigneVente.prix_unitaire (prix historisé au moment de la vente),
    # pas Produit.prix_unitaire (prix courant), pour rester exact même si le prix a changé depuis.
    ca_semaine = {
        l['id_produit']: l['total_ca']
        for l in lignes_semaine.values('id_produit').annotate(
            total_ca=Sum(F('prix_unitaire') * F('quantite'))
        )
    }

    # --- Nombre de vendeurs distincts ayant vendu ce produit sur 30 jours ---
    nb_vendeurs_par_produit = {
        l['id_produit']: l['nb_vendeurs']
        for l in lignes_30j.values('id_produit').annotate(
            nb_vendeurs=Count('id_vente__id_vendeur', distinct=True)
        )
    }

    # --- Rotation lente : dernière vente (toutes dates confondues) par produit, région entière ---
    seuil_rotation_lente = aujourd_hui - timedelta(days=SEUIL_ROTATION_LENTE_JOURS)
    dernieres_ventes_par_produit = dict(
        LigneVente.objects.filter(**filtre_ventes)
        .values('id_produit')
        .annotate(derniere_vente=Max('id_vente__date_vente'))
        .values_list('id_produit', 'derniere_vente')
    )

    # --- Construction de la liste finale ---
    produits_data = []
    for produit in produits:
        quantite = quantites_semaine.get(produit.id_produit, 0)
        quantite_precedente = quantites_semaine_precedente.get(produit.id_produit, 0)

        derniere_vente = dernieres_ventes_par_produit.get(produit.id_produit)
        jamais_vendu = derniere_vente is None
        jours_inactif = None if jamais_vendu else (aujourd_hui - derniere_vente).days
        rotation_lente = jamais_vendu or derniere_vente < seuil_rotation_lente

        produits_data.append({
            'id_produit': produit.id_produit,
            'nom_produit': produit.nom_produit,
            'categorie': produit.id_categorie.nom_categorie if produit.id_categorie else '—',
            'id_categorie': produit.id_categorie_id,
            'prix_unitaire': produit.prix_unitaire,
            'quantite_semaine': quantite,
            'tendance': calcule_tendance(quantite, quantite_precedente),
            'nb_vendeurs': nb_vendeurs_par_produit.get(produit.id_produit, 0),
            'ca_semaine': ca_semaine.get(produit.id_produit, 0),
            'rotation_lente': rotation_lente,
            'jamais_vendu': jamais_vendu,
            'jours_inactif': jours_inactif,
        })

    # Tri par défaut : meilleure performance en premier (par CA, plus parlant que la quantité brute)
    produits_data.sort(key=lambda p: p['ca_semaine'], reverse=True)

    # --- CA total de la région cette semaine (somme de tous les produits) ---
    ca_total_semaine = sum(p['ca_semaine'] for p in produits_data)

    # --- Liste des catégories, pour le filtre dropdown ---
    categories = Categorie.objects.all()

    # ============================================================
    # Séries journalières (30j) pour TOUS les produits
    # → sert au graphe Top 5 ET à la fiche détail au clic
    # ============================================================

    debut_periode_graphe = (aujourd_hui - timedelta(days=29)).date()
    fin_periode_graphe = aujourd_hui.date()

    jours_liste = []
    jour_courant = debut_periode_graphe
    while jour_courant <= fin_periode_graphe:
        jours_liste.append(jour_courant)
        jour_courant += timedelta(days=1)

    labels_graphe_produits = [j.strftime('%d/%m') for j in jours_liste]
    dates_iso = [j.isoformat() for j in jours_liste]
    jour_index = {j: i for i, j in enumerate(jours_liste)}

    # --- Init : une série par produit actif ---
    quantites_jour_par_produit = {p.id_produit: [0] * len(jours_liste) for p in produits}
    ca_jour_par_produit = {p.id_produit: [0.0] * len(jours_liste) for p in produits}

    # --- Une seule boucle sur les 30j pour remplir toutes les séries ---
    for ligne in lignes_30j.select_related('id_vente'):
        jour = ligne.id_vente.date_vente.date()
        idx = jour_index.get(jour)
        if idx is not None and ligne.id_produit_id in quantites_jour_par_produit:
            quantites_jour_par_produit[ligne.id_produit_id][idx] += ligne.quantite
            ca_jour_par_produit[ligne.id_produit_id][idx] += float(ligne.prix_unitaire) * ligne.quantite

    # --- Top 5 (par quantité totale sur 30j), dérivé des séries déjà calculées ---
    totaux_par_produit = {pid: sum(vals) for pid, vals in quantites_jour_par_produit.items()}
    top_produits_ids = sorted(totaux_par_produit, key=totaux_par_produit.get, reverse=True)[:5]

    noms_produits = {p.id_produit: p.nom_produit for p in produits}

    graphe_top_produits = {
        'labels': labels_graphe_produits,
        'produits': [
            {
                'nom': noms_produits[pid],
                'quantites': quantites_jour_par_produit[pid],
                'ca': [round(c, 2) for c in ca_jour_par_produit[pid]],
            }
            for pid in top_produits_ids
        ],
    }

    # --- Détail par produit, pour la fiche modal au clic ---
    detail_produits = {
        'labels': labels_graphe_produits,
        'dates_iso': dates_iso,
        'produits': {
            str(p.id_produit): {
                'nom': p.nom_produit,
                'categorie': p.id_categorie.nom_categorie if p.id_categorie else '—',
                'prix_unitaire': str(p.prix_unitaire),
                'quantites': quantites_jour_par_produit[p.id_produit],
                'ca': [round(c, 2) for c in ca_jour_par_produit[p.id_produit]],
            }
            for p in produits
        },
    }

    return {
        'produits_data': produits_data,
        'categories': categories,
        'ca_total_semaine': ca_total_semaine,
        'graphe_top_produits_json': json.dumps(graphe_top_produits),
        'detail_produits_json': json.dumps(detail_produits),
        'seuil_rotation_lente_jours': SEUIL_ROTATION_LENTE_JOURS,
    }


def construire_contexte_previsions(filtre_ventes, horizon=HORIZON_PAR_DEFAUT):
    """
    Calcule le contexte de prévision des ventes (graphique + top produits)
    pour un périmètre donné (agence ou région), en s'appuyant sur le
    modèle XGBoost entraîné dans ml_prediction (voir commercial/previsions.py
    pour la logique de prévision et la répartition par périmètre).
    """
    donnees = obtenir_prevision_perimetre(filtre_ventes, horizon=horizon)

    jours_fr = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    par_jour = donnees['par_jour']
    labels_prevision = [row.date_vente.strftime('%d/%m') for row in par_jour.itertuples()]
    labels_prevision_complet = [
        f"{jours_fr[row.date_vente.weekday()]} {row.date_vente.strftime('%d/%m/%Y')}"
        for row in par_jour.itertuples()
    ]
    valeurs_prevision = [int(v) for v in par_jour['quantite_predite']]

    noms_produits = dict(Produit.objects.filter(actif=True).values_list('id_produit', 'nom_produit'))
    top_produits_prevus_qs = donnees['par_produit'].head(10)
    max_quantite_prevue = int(top_produits_prevus_qs.max()) if len(top_produits_prevus_qs) else 1
    top_produits_prevus = [
        {
            'nom': noms_produits.get(pid, pid),
            'quantite_predite': int(qte),
            'pourcentage': round(int(qte) / max_quantite_prevue * 100),
        }
        for pid, qte in top_produits_prevus_qs.items()
    ]

    return {
        'horizon_jours': horizon,
        'date_depart_prevision': donnees['date_depart'],
        'labels_prevision': labels_prevision,
        'labels_prevision_complet': labels_prevision_complet,
        'valeurs_prevision': valeurs_prevision,
        'total_prevu_horizon': donnees['total_horizon'],
        'moyenne_prevue_jour': round(donnees['total_horizon'] / horizon) if horizon else 0,
        'top_produits_prevus': top_produits_prevus,
        'poids_perimetre_pct': round(donnees['poids_perimetre'] * 100, 1),
    }


@connexion_chef_region_requise
def analyses_chef_region(request):
    """Prévision des ventes (14 prochains jours) pour la région du Chef
    connecté, via le modèle XGBoost entraîné dans ml_prediction."""
    chef_region = get_chef_region_connecte(request)
    agence_chef = chef_region.chefregionpermission.id_agence
    id_region = agence_chef.id_region_id
    region = agence_chef.id_region

    contexte = construire_contexte_previsions({'id_vente__id_agence__id_region_id': id_region})
    contexte.update({
        'chef_region': chef_region,
        'agence': agence_chef,
        'region': region,
        'section_active': 'analyses',
    })
    return render(request, 'commercial/chef_region/analyses.html', contexte)


@connexion_chef_region_requise
def liste_produits_chef_region(request):
    chef_region = get_chef_region_connecte(request)
    agence_chef = chef_region.chefregionpermission.id_agence
    id_region = agence_chef.id_region_id

    donnees = construire_donnees_produits({'id_vente__id_agence__id_region_id': id_region})

    context = {
        'chef_region': chef_region,
        'section_active': 'produits',
        **donnees,
    }
    return render(request, 'commercial/chef_region/produits.html', context)


@connexion_chef_region_requise
def parametres_chef_region(request):
    chef_region = get_chef_region_connecte(request)
    utilisateur = chef_region.id_chef_region

    try:
        agence = chef_region.chefregionpermission.id_agence
    except ChefRegionPermission.DoesNotExist:
        agence = None

    if request.method == 'POST' and request.POST.get('form') == 'securite':
        ancien = request.POST.get('ancien_mot_de_passe', '')
        nouveau = request.POST.get('nouveau_mot_de_passe', '')
        confirmation = request.POST.get('confirmation_mot_de_passe', '')

        if not check_password(ancien, utilisateur.password):
            messages.error(request, "Le mot de passe actuel est incorrect.")
        elif len(nouveau) < 8:
            messages.error(request, "Le nouveau mot de passe doit contenir au moins 8 caractères.")
        elif nouveau != confirmation:
            messages.error(request, "La confirmation ne correspond pas au nouveau mot de passe.")
        else:
            utilisateur.password = make_password(nouveau)
            utilisateur.save(update_fields=['password'])
            messages.success(request, "Mot de passe mis à jour avec succès.")

        return redirect('commercial:parametres_chef_region')

    if request.method == 'POST' and request.POST.get('form') == 'signalement':
        message_signalement = request.POST.get('message', '').strip()

        if not message_signalement:
            messages.error(request, "Veuillez décrire l'incohérence avant d'envoyer le signalement.")
        else:
            Signalement.objects.create(utilisateur=utilisateur, message=message_signalement)
            messages.success(
                request,
                "Votre signalement a bien été envoyé à l'administrateur. Il sera traité prochainement.",
            )

        return redirect('commercial:parametres_chef_region')

    context = {
        'chef_region': chef_region,
        'utilisateur': utilisateur,
        'agence': agence,
        'section_active': 'parametres',
    }
    return render(request, 'commercial/chef_region/parametres.html', context)


# ============================================================
# Espace Commercial (accès à plusieurs agences)
# ============================================================

def verifier_acces_agence_commercial(commercial, id_agence):
    """Renvoie l'Agence si le commercial y a accès, sinon lève Http404."""
    agence = get_object_or_404(Agence.objects.select_related('id_region'), id_agence=id_agence)
    a_acces = CommercialPermissionAgence.objects.filter(id_commercial=commercial, id_agence=agence).exists()
    if not a_acces:
        raise Http404("Vous n'avez pas accès à cette agence.")
    return agence


@connexion_commercial_requise
def dashboard_agence_commercial(request, id_agence):
    commercial = get_commercial_connecte(request)
    agence = verifier_acces_agence_commercial(commercial, id_agence)

    contexte = construire_kpis_agence(agence)
    contexte.update({
        'commercial': commercial,
        'agences_commercial': get_agences_commercial(commercial),
        'agence_active_id': agence.id_agence,
        'section_active': 'agence_dashboard',
        'url_actualisation': reverse('commercial:dashboard_agence_commercial_data', args=[agence.id_agence]),
    })
    return render(request, 'commercial/espace_commercial/dashboard.html', contexte)


@connexion_commercial_requise
def dashboard_agence_commercial_data(request, id_agence):
    """Version JSON de dashboard_agence_commercial (voir dashboard_chef_region_data)."""
    commercial = get_commercial_connecte(request)
    agence = verifier_acces_agence_commercial(commercial, id_agence)
    donnees = construire_kpis_agence(agence)
    donnees.pop('agence', None)
    return JsonResponse(donnees)


@connexion_commercial_requise
def previsions_agence_commercial(request, id_agence):
    """Prévision des ventes (14 prochains jours) pour une agence donnée,
    via le modèle XGBoost entraîné dans ml_prediction."""
    commercial = get_commercial_connecte(request)
    agence = verifier_acces_agence_commercial(commercial, id_agence)

    contexte = construire_contexte_previsions({'id_vente__id_agence': agence})
    contexte.update({
        'commercial': commercial,
        'agence': agence,
        'agences_commercial': get_agences_commercial(commercial),
        'agence_active_id': agence.id_agence,
        'section_active': 'agence_previsions',
    })
    return render(request, 'commercial/espace_commercial/previsions.html', contexte)


@connexion_commercial_requise
def vendeurs_agence_commercial(request, id_agence):
    commercial = get_commercial_connecte(request)
    agence = verifier_acces_agence_commercial(commercial, id_agence)

    vendeurs_qs = Vendeur.objects.filter(id_agence=agence).select_related('id_agence', 'id_type_vendeur')
    vendeurs_data = construire_donnees_vendeurs(vendeurs_qs)

    context = {
        'commercial': commercial,
        'agence': agence,
        'agences_commercial': get_agences_commercial(commercial),
        'agence_active_id': agence.id_agence,
        'vendeurs_data': vendeurs_data,
        'seuil_rotation_lente_jours': SEUIL_ROTATION_LENTE_JOURS,
        'section_active': 'agence_vendeurs',
    }
    return render(request, 'commercial/espace_commercial/vendeurs.html', context)


@connexion_commercial_requise
def produits_agence_commercial(request, id_agence):
    commercial = get_commercial_connecte(request)
    agence = verifier_acces_agence_commercial(commercial, id_agence)

    donnees = construire_donnees_produits({'id_vente__id_agence': agence})

    context = {
        'commercial': commercial,
        'agence': agence,
        'agences_commercial': get_agences_commercial(commercial),
        'agence_active_id': agence.id_agence,
        'section_active': 'agence_produits',
        **donnees,
    }
    return render(request, 'commercial/espace_commercial/produits.html', context)


@connexion_commercial_requise
def vue_ensemble_commercial(request):
    commercial = get_commercial_connecte(request)
    agences = get_agences_commercial(commercial)

    aujourd_hui = date_reference()
    # Lundi 00:00 (et non "maintenant moins N jours", qui décale l'heure de
    # début — un bug qui rendait "cette semaine" quasi vide chaque lundi,
    # puisque la borne tombait alors exactement sur l'instant présent).
    debut_semaine = aujourd_hui.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=aujourd_hui.weekday())
    debut_semaine_precedente = debut_semaine - timedelta(days=7)
    seuil_inactivite = aujourd_hui - timedelta(days=SEUIL_ROTATION_LENTE_JOURS)

    # --- Catalogue produits actifs, commun à toutes les agences (chargé une seule fois) ---
    produits_actifs_ids = list(Produit.objects.filter(actif=True).values_list('id_produit', flat=True))

    comparaison = []
    for agence in agences:
        ventes_semaine = Vente.objects.filter(id_agence=agence, date_vente__gte=debut_semaine)
        ventes_semaine_precedente = Vente.objects.filter(
            id_agence=agence,
            date_vente__gte=debut_semaine_precedente,
            date_vente__lt=debut_semaine,
        )

        ca_semaine = LigneVente.objects.filter(id_vente__in=ventes_semaine).aggregate(
            total=Sum(F('prix_unitaire') * F('quantite'))
        )['total'] or 0
        ca_semaine_precedente = LigneVente.objects.filter(id_vente__in=ventes_semaine_precedente).aggregate(
            total=Sum(F('prix_unitaire') * F('quantite'))
        )['total'] or 0
        quantite_semaine = LigneVente.objects.filter(
            id_vente__in=ventes_semaine
        ).aggregate(total=Sum('quantite'))['total'] or 0

        # --- Produits en rotation lente dans cette agence (actifs, sans vente depuis le seuil) ---
        dernieres_ventes_produit = dict(
            LigneVente.objects.filter(id_vente__id_agence=agence)
            .values('id_produit')
            .annotate(derniere_vente=Max('id_vente__date_vente'))
            .values_list('id_produit', 'derniere_vente')
        )
        nb_produits_rotation_lente = sum(
            1 for pid in produits_actifs_ids
            if dernieres_ventes_produit.get(pid) is None or dernieres_ventes_produit[pid] < seuil_inactivite
        )

        # --- Vendeurs inactifs dans cette agence (actifs, sans vente depuis le seuil) ---
        vendeurs_actifs = Vendeur.objects.filter(id_agence=agence, actif=True)
        dernieres_ventes_vendeur = dict(
            Vente.objects.filter(id_vendeur__in=vendeurs_actifs)
            .values('id_vendeur')
            .annotate(derniere_vente=Max('date_vente'))
            .values_list('id_vendeur', 'derniere_vente')
        )
        nb_vendeurs_inactifs = sum(
            1 for vendeur in vendeurs_actifs
            if dernieres_ventes_vendeur.get(vendeur.id_vendeur) is None
            or dernieres_ventes_vendeur[vendeur.id_vendeur] < seuil_inactivite
        )

        comparaison.append({
            'id_agence': agence.id_agence,
            'nom_agence': agence.nom_agence or agence.id_agence,
            'region': agence.id_region.nom_region,
            'ca_semaine': float(ca_semaine),
            'tendance_ca': calcule_tendance(ca_semaine, ca_semaine_precedente),
            'quantite_semaine': quantite_semaine,
            'nb_ventes_semaine': ventes_semaine.count(),
            'nb_produits_rotation_lente': nb_produits_rotation_lente,
            'nb_vendeurs_inactifs': nb_vendeurs_inactifs,
        })

    comparaison.sort(key=lambda a: a['ca_semaine'], reverse=True)
    ca_total_semaine = sum(a['ca_semaine'] for a in comparaison)
    meilleure_agence = comparaison[0] if comparaison else None
    agence_a_surveiller = max(
        comparaison,
        key=lambda a: a['nb_produits_rotation_lente'] + a['nb_vendeurs_inactifs'],
        default=None,
    )
    if agence_a_surveiller and (
        agence_a_surveiller['nb_produits_rotation_lente'] + agence_a_surveiller['nb_vendeurs_inactifs'] == 0
    ):
        agence_a_surveiller = None

    context = {
        'commercial': commercial,
        'agences_commercial': agences,
        'comparaison': comparaison,
        'ca_total_semaine': ca_total_semaine,
        'meilleure_agence': meilleure_agence,
        'agence_a_surveiller': agence_a_surveiller,
        'seuil_rotation_lente_jours': SEUIL_ROTATION_LENTE_JOURS,
        'section_active': 'vue_ensemble',
    }
    return render(request, 'commercial/espace_commercial/vue_ensemble.html', context)


@connexion_commercial_requise
def parametres_commercial(request):
    commercial = get_commercial_connecte(request)
    utilisateur = commercial.id_commercial
    agences = get_agences_commercial(commercial)

    if request.method == 'POST' and request.POST.get('form') == 'securite':
        ancien = request.POST.get('ancien_mot_de_passe', '')
        nouveau = request.POST.get('nouveau_mot_de_passe', '')
        confirmation = request.POST.get('confirmation_mot_de_passe', '')

        if not check_password(ancien, utilisateur.password):
            messages.error(request, "Le mot de passe actuel est incorrect.")
        elif len(nouveau) < 8:
            messages.error(request, "Le nouveau mot de passe doit contenir au moins 8 caractères.")
        elif nouveau != confirmation:
            messages.error(request, "La confirmation ne correspond pas au nouveau mot de passe.")
        else:
            utilisateur.password = make_password(nouveau)
            utilisateur.save(update_fields=['password'])
            messages.success(request, "Mot de passe mis à jour avec succès.")

        return redirect('commercial:parametres_commercial')

    if request.method == 'POST' and request.POST.get('form') == 'signalement':
        message_signalement = request.POST.get('message', '').strip()

        if not message_signalement:
            messages.error(request, "Veuillez décrire l'incohérence avant d'envoyer le signalement.")
        else:
            Signalement.objects.create(utilisateur=utilisateur, message=message_signalement)
            messages.success(
                request,
                "Votre signalement a bien été envoyé à l'administrateur. Il sera traité prochainement.",
            )

        return redirect('commercial:parametres_commercial')

    context = {
        'commercial': commercial,
        'utilisateur': utilisateur,
        'agences_commercial': agences,
        'section_active': 'parametres',
    }
    return render(request, 'commercial/espace_commercial/parametres.html', context)