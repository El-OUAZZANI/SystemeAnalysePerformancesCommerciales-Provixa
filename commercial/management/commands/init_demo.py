"""
Commande de mode démo : recrée le schéma SQLite et le repeuple avec des
données factices (agences, produits, ventes...) à chaque démarrage du
serveur. Voir provixa.settings.MODE_DEMO (DJANGO_MODE_DEMO=true) et le
Start Command Render.

Ne fait jamais rien en dehors du mode démo, pour ne jamais risquer de
toucher à la base SQL Server de production/locale.
"""

import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from faker import Faker

from commercial.models import (
    Agence, Categorie, Client, ChefRegion, ChefRegionPermission, Commercial,
    CommercialPermission, CommercialPermissionAgence, LigneVente, Produit,
    Region, Typevendeur, Utilisateur, Vendeur, Vente,
)

# Ordre de création respectant les dépendances de clés étrangères
# (la suppression se fait dans l'ordre inverse).
MODELES_EN_ORDRE = [
    Region, Categorie, Typevendeur, Agence, Utilisateur, ChefRegion,
    ChefRegionPermission, Commercial, CommercialPermission,
    CommercialPermissionAgence, Client, Vendeur, Produit, Vente, LigneVente,
]

NOMS_REGIONS = ['Agadir', 'Casasud', 'El Jadida', 'Fès-Meknès', 'Marrakech', 'Nador', 'Tanger']
CATEGORIES = ['Alimentaire', 'Boissons', 'Hygiène & Beauté', 'Entretien', 'Épicerie']
PRODUITS_PAR_CATEGORIE = {
    'Alimentaire': ['Riz 1kg', 'Pâtes 500g', 'Huile de tournesol 1L', 'Sucre 1kg', 'Farine 1kg', 'Conserve de thon'],
    'Boissons': ["Eau minérale 1.5L", "Jus d'orange 1L", 'Soda cola 1.5L', 'Thé vert 25 sachets', 'Café moulu 250g', 'Lait UHT 1L'],
    'Hygiène & Beauté': ['Savon liquide 500ml', 'Shampoing 400ml', 'Dentifrice 75ml', 'Déodorant', 'Gel douche 500ml', 'Papier toilette x6'],
    'Entretien': ['Lessive liquide 2L', 'Eau de javel 1L', 'Nettoyant multi-usage', 'Éponges x5', 'Liquide vaisselle 500ml', 'Sacs poubelle x20'],
    'Épicerie': ['Chocolat en tablette', 'Biscuits assortiment', 'Confiture 400g', 'Miel 250g', 'Olives 500g', 'Épices mélangées'],
}

# Comptes affichés sur la page de connexion (voir COMPTES_DEMO dans
# commercial/views.py) : doivent exister avec ce mot de passe pour que la
# suggestion fonctionne réellement sur le déploiement de démo.
EMAIL_CHEF_REGION_DEMO = 'cdr@mail.com'
EMAIL_COMMERCIAL_DEMO = 'agatheleroux@example.org'
MOT_DE_PASSE_DEMO = 'Demo1234!'

NB_JOURS_HISTORIQUE = 60
NB_VENDEURS_PAR_AGENCE = 4
NB_CLIENTS_PAR_AGENCE = 12
NB_COMMERCIAUX = 8


class Command(BaseCommand):
    help = "Recrée le schéma et génère des données de démonstration (mode démo SQLite uniquement)."

    def handle(self, *args, **options):
        if not settings.MODE_DEMO:
            raise CommandError(
                "init_demo ne peut tourner qu'en mode démo (DJANGO_MODE_DEMO=true) "
                "pour ne jamais toucher à une base de production."
            )

        fake = Faker('fr_FR')

        self._recreer_schema()
        with transaction.atomic():
            self._peupler(fake)

        self.stdout.write(self.style.SUCCESS("Données de démonstration générées."))

    def _recreer_schema(self):
        with connection.schema_editor() as editor:
            tables_existantes = set(connection.introspection.table_names())
            for modele in reversed(MODELES_EN_ORDRE):
                if modele._meta.db_table in tables_existantes:
                    editor.delete_model(modele)
            for modele in MODELES_EN_ORDRE:
                editor.create_model(modele)

    def _peupler(self, fake):
        regions = [
            Region.objects.create(id_region=i + 1, nom_region=nom)
            for i, nom in enumerate(NOMS_REGIONS)
        ]
        agences = [
            Agence.objects.create(
                id_agence=f'AG{i + 1:02d}',
                nom_agence=f'Agence {region.nom_region}',
                id_region=region,
                actif=True,
            )
            for i, region in enumerate(regions)
        ]

        categories = {
            nom: Categorie.objects.create(id_categorie=f'CAT{i + 1:02d}', nom_categorie=nom)
            for i, nom in enumerate(CATEGORIES)
        }
        produits = []
        compteur = 1
        for nom_categorie, noms_produits in PRODUITS_PAR_CATEGORIE.items():
            for nom_produit in noms_produits:
                produits.append(Produit.objects.create(
                    id_produit=f'PR{compteur:03d}',
                    nom_produit=nom_produit,
                    id_categorie=categories[nom_categorie],
                    prix_unitaire=round(random.uniform(8, 180), 2),
                    actif=True,
                    date_creation=timezone.now(),
                ))
                compteur += 1

        types_vendeur = [
            Typevendeur.objects.create(libelle_type_vendeur='Sédentaire'),
            Typevendeur.objects.create(libelle_type_vendeur='Itinérant'),
        ]

        vendeurs_par_agence = {}
        clients_par_agence = {}
        compteur_vendeur = 1
        compteur_client = 1
        for agence in agences:
            vendeurs = []
            for _ in range(NB_VENDEURS_PAR_AGENCE):
                vendeurs.append(Vendeur.objects.create(
                    id_vendeur=f'VD{compteur_vendeur:04d}',
                    nom_vendeur=fake.last_name(),
                    prenom_vendeur=fake.first_name(),
                    id_type_vendeur=random.choice(types_vendeur),
                    id_agence=agence,
                    email=fake.unique.email(),
                    actif=True,
                ))
                compteur_vendeur += 1
            vendeurs_par_agence[agence.id_agence] = vendeurs

            clients = []
            for _ in range(NB_CLIENTS_PAR_AGENCE):
                clients.append(Client.objects.create(
                    id_client=f'CL{compteur_client:04d}',
                    prenom_client=fake.first_name(),
                    nom_client=fake.last_name(),
                    id_agence=agence,
                    ville=agence.id_region.nom_region,
                    actif=True,
                ))
                compteur_client += 1
            clients_par_agence[agence.id_agence] = clients

        self._creer_comptes(fake, agences)

        self._creer_ventes(fake, agences, vendeurs_par_agence, clients_par_agence, produits)

    def _creer_comptes(self, fake, agences):
        mot_de_passe_hache = make_password(MOT_DE_PASSE_DEMO)

        for i, agence in enumerate(agences):
            email = EMAIL_CHEF_REGION_DEMO if i == 0 else fake.unique.email()
            utilisateur = Utilisateur.objects.create(
                id_utilisateur=f'UCR{i + 1:04d}',
                nom=fake.last_name(),
                prenom=fake.first_name(),
                email=email,
                password=mot_de_passe_hache,
                date_prise_poste=timezone.now() - timedelta(days=random.randint(100, 800)),
                actif=True,
            )
            chef = ChefRegion.objects.create(id_chef_region=utilisateur)
            ChefRegionPermission.objects.create(id_chef_region=chef, id_agence=agence)

        for i in range(NB_COMMERCIAUX):
            email = EMAIL_COMMERCIAL_DEMO if i == 0 else fake.unique.email()
            utilisateur = Utilisateur.objects.create(
                id_utilisateur=f'UCO{i + 1:04d}',
                nom=fake.last_name(),
                prenom=fake.first_name(),
                email=email,
                password=mot_de_passe_hache,
                date_prise_poste=timezone.now() - timedelta(days=random.randint(50, 700)),
                actif=True,
            )
            commercial = Commercial.objects.create(id_commercial=utilisateur)
            CommercialPermission.objects.create(id_commercial=commercial)
            # Le compte de démo a accès à toutes les agences ; les autres, à un sous-ensemble.
            agences_assignees = agences if i == 0 else random.sample(agences, k=random.randint(2, len(agences)))
            for agence in agences_assignees:
                CommercialPermissionAgence.objects.create(id_commercial=commercial, id_agence=agence)

    def _creer_ventes(self, fake, agences, vendeurs_par_agence, clients_par_agence, produits):
        aujourd_hui = timezone.now()
        compteur_vente = 1
        lignes_a_creer = []

        for jours_ecoules in range(NB_JOURS_HISTORIQUE, -1, -1):
            jour = aujourd_hui - timedelta(days=jours_ecoules)
            for agence in agences:
                for _ in range(random.randint(0, 5)):
                    vendeur = random.choice(vendeurs_par_agence[agence.id_agence])
                    client = random.choice(clients_par_agence[agence.id_agence])
                    heure_vente = jour.replace(
                        hour=random.randint(8, 19), minute=random.randint(0, 59),
                        second=random.randint(0, 59), microsecond=0,
                    )
                    vente = Vente.objects.create(
                        id_vente=f'V{compteur_vente:06d}',
                        id_client=client,
                        date_vente=heure_vente,
                        id_vendeur=vendeur,
                        id_agence=agence,
                    )
                    compteur_vente += 1
                    for produit in random.sample(produits, k=random.randint(1, 4)):
                        lignes_a_creer.append(LigneVente(
                            id_vente=vente,
                            id_produit=produit,
                            prix_unitaire=produit.prix_unitaire,
                            quantite=random.randint(1, 10),
                        ))

        LigneVente.objects.bulk_create(lignes_a_creer, batch_size=500)
