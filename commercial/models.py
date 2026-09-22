# This is an auto-generated Django model module.
from django.conf import settings
from django.db import models

# La collation SQL Server French_CI_AS n'existe pas sous SQLite (mode démo) :
# on ne la fixe que pour la connexion SQL Server habituelle.
COLLATION_FR = None if settings.MODE_DEMO else 'French_CI_AS'

class Utilisateur(models.Model):
    """Table de base pour tous les utilisateurs"""
    id_utilisateur = models.CharField(primary_key=True, max_length=30, db_collation=COLLATION_FR)
    nom = models.CharField(max_length=100, db_collation=COLLATION_FR)
    prenom = models.CharField(max_length=60, db_collation=COLLATION_FR, blank=True, null=True)
    email = models.EmailField(unique=True, max_length=200, db_collation=COLLATION_FR)
    password = models.CharField(max_length=255, db_collation=COLLATION_FR)
    telephone = models.CharField(max_length=30, db_collation=COLLATION_FR, blank=True, null=True)
    date_prise_poste = models.DateTimeField(blank=True, null=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'Utilisateur'

    def __str__(self):
        return f"{self.prenom} {self.nom}"


class Region(models.Model):
    id_region = models.IntegerField(primary_key=True)
    nom_region = models.CharField(unique=True, max_length=100, db_collation=COLLATION_FR)

    class Meta:
        managed = False
        db_table = 'Region'

    def __str__(self):
        return self.nom_region


class Agence(models.Model):
    id_agence = models.CharField(primary_key=True, max_length=30, db_collation=COLLATION_FR)
    nom_agence = models.CharField(max_length=100, db_collation=COLLATION_FR, blank=True, null=True)
    id_region = models.ForeignKey('Region', on_delete=models.PROTECT, db_column='id_region')
    adresse = models.CharField(max_length=255, db_collation=COLLATION_FR, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    actif = models.BooleanField(default=True)

    def __str__(self):
        if self.nom_agence:
            return f"{self.nom_agence}/{self.id_region.nom_region}"
        return self.id_region.nom_region

    class Meta:
        managed = False
        db_table = 'Agence'


class ChefRegion(models.Model):
    """Chef de région - correspond à une agence"""
    id_chef_region = models.OneToOneField('Utilisateur',on_delete=models.CASCADE,db_column='id_chef_region',primary_key=True)

    class Meta:
        managed = False
        db_table = 'Chef_Region'
        verbose_name = "Chef région"
        verbose_name_plural = "Chefs région"

    def __str__(self):
        return f"Chef {self.id_chef_region.nom}"


class ChefRegionPermission(models.Model):
    id_chef_region = models.OneToOneField('ChefRegion', models.DO_NOTHING, db_column='id_chef_region', primary_key=True)
    id_agence = models.OneToOneField('Agence', models.DO_NOTHING, db_column='id_agence')

    class Meta:
        managed = False
        db_table = 'Chef_Region_Permission'


class Categorie(models.Model):
    id_categorie = models.CharField(primary_key=True, max_length=30, db_collation=COLLATION_FR)
    nom_categorie = models.CharField(unique=True, max_length=100, db_collation=COLLATION_FR)

    class Meta:
        managed = False
        db_table = 'Categorie'

    def __str__(self):
        return self.nom_categorie


class Commercial(models.Model):
    """Commercial - agent commercial d'une agence"""
    id_commercial = models.OneToOneField(
        'Utilisateur', 
        on_delete=models.CASCADE, 
        db_column='id_commercial', 
        primary_key=True
    )

    class Meta:
        managed = False
        db_table = 'Commercial'
        verbose_name = "Utilisateur commercial"
        verbose_name_plural = "Commerciaux"

    def __str__(self):
        return f"Commercial {self.id_commercial.nom}"


class CommercialPermission(models.Model):
    id_commercial = models.OneToOneField(
        Commercial, 
        on_delete=models.CASCADE, 
        db_column='id_commercial', 
        primary_key=True
    )

    class Meta:
        managed = False
        db_table = 'Commercial_Permission'


class CommercialPermissionAgence(models.Model):
    pk = models.CompositePrimaryKey('id_commercial', 'id_agence')
    id_commercial = models.ForeignKey(
        'Commercial', 
        on_delete=models.PROTECT, 
        db_column='id_commercial'
    )
    id_agence = models.ForeignKey(
        'Agence', 
        on_delete=models.PROTECT, 
        db_column='id_agence'
    )

    class Meta:
        managed = False
        db_table = 'Commercial_Permission_Agence'


class Client(models.Model):
    id_client = models.CharField(primary_key=True, max_length=30, db_collation=COLLATION_FR)
    prenom_client = models.CharField(max_length=100, db_collation=COLLATION_FR, blank=True, null=True)
    nom_client = models.CharField(max_length=100, db_collation=COLLATION_FR)
    id_agence = models.ForeignKey(Agence, on_delete=models.PROTECT, db_column='id_agence', blank=True, null=True)
    ville = models.CharField(max_length=50, db_collation=COLLATION_FR, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    code_categorie = models.CharField(max_length=30, db_collation=COLLATION_FR, blank=True, null=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'Client'

    def __str__(self):
        return f"{self.nom_client}"


class Typevendeur(models.Model):
    id_type_vendeur = models.AutoField(primary_key=True)
    libelle_type_vendeur = models.CharField(max_length=50, db_collation=COLLATION_FR)

    class Meta:
        managed = False
        db_table = 'TypeVendeur'

    def __str__(self):
        return self.libelle_type_vendeur


class Vendeur(models.Model):
    id_vendeur = models.CharField(primary_key=True, max_length=30, db_collation=COLLATION_FR)
    nom_vendeur = models.CharField(max_length=100, db_collation=COLLATION_FR)
    prenom_vendeur = models.CharField(max_length=60, db_collation=COLLATION_FR, blank=True, null=True)
    id_type_vendeur = models.ForeignKey(Typevendeur, on_delete=models.PROTECT, db_column='id_type_vendeur')
    id_agence = models.ForeignKey(Agence, on_delete=models.PROTECT, db_column='id_agence', blank=True, null=True)
    email = models.EmailField(unique=True, max_length=200, db_collation=COLLATION_FR, blank=True, null=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'Vendeur'

    def __str__(self):
        return f"{self.nom_vendeur}"


class Produit(models.Model):
    id_produit = models.CharField(primary_key=True, max_length=30, db_collation=COLLATION_FR)
    nom_produit = models.CharField(unique=True, max_length=100, db_collation=COLLATION_FR)
    id_categorie = models.ForeignKey(Categorie, on_delete=models.PROTECT, db_column='id_categorie')
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=500, db_collation=COLLATION_FR, blank=True, null=True)
    chemin_image = models.CharField(max_length=500, db_collation=COLLATION_FR, blank=True, null=True)
    date_creation = models.DateTimeField(blank=True, null=True)
    actif = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'Produit'

    def __str__(self):
        return self.nom_produit


class LigneVente(models.Model):
    id_ligne = models.AutoField(primary_key=True)
    id_vente = models.ForeignKey('Vente', on_delete=models.PROTECT, db_column='id_vente')
    id_produit = models.ForeignKey('Produit', on_delete=models.PROTECT, db_column='id_produit')
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=6)
    quantite = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'Ligne_vente'


class Vente(models.Model):
    id_vente = models.CharField(primary_key=True, max_length=30, db_collation=COLLATION_FR)
    id_client = models.ForeignKey(Client, on_delete=models.PROTECT, db_column='id_client')
    date_vente = models.DateTimeField()
    id_vendeur = models.ForeignKey(Vendeur, on_delete=models.PROTECT, db_column='id_vendeur')
    id_agence = models.ForeignKey(Agence, on_delete=models.PROTECT, db_column='id_agence')

    class Meta:
        managed = False
        db_table = 'Vente'

    def __str__(self):
        return f"Vente {self.id_vente}"


class Signalement(models.Model):
    """
    Signalement envoyé par un utilisateur (ex: chef de région) à l'admin,
    par exemple en cas d'incohérence dans ses informations personnelles.
    Contrairement aux autres modèles de ce fichier, cette table est gérée
    par Django (pas de table préexistante côté SQL Server) : une migration
    Django crée réellement la table en base.
    """
    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.CASCADE,
        db_column='id_utilisateur',
        related_name='signalements',
    )
    message = models.TextField(verbose_name="Message")
    date_signalement = models.DateTimeField(auto_now_add=True, verbose_name="Date")
    traite = models.BooleanField(default=False, verbose_name="Traité")

    class Meta:
        db_table = 'Signalement'
        verbose_name = "Signalement"
        verbose_name_plural = "Signalements"
        ordering = ['-date_signalement']

    def __str__(self):
        return f"Signalement de {self.utilisateur} ({self.date_signalement:%d/%m/%Y})"