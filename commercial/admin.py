import re
import secrets
import string

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Agence,
    ChefRegion,
    ChefRegionPermission,
    Commercial,
    CommercialPermission,
    CommercialPermissionAgence,
    Signalement,
    Utilisateur,
)


# ------------------------------------------------------------------
# Utilitaires communs : génération d'identifiant et de mot de passe
# ------------------------------------------------------------------

def generate_next_id(prefix: str) -> str:
    """
    Génère le prochain id_utilisateur pour un préfixe donné (ex: 'UCR', 'UCO').
    Convention : PREFIX + index sur 4 chiffres (ex: UCR0001), déjà utilisée
    par generate_fake_data.py.
    """
    existing_ids = Utilisateur.objects.filter(
        id_utilisateur__startswith=prefix
    ).values_list('id_utilisateur', flat=True)

    pattern = re.compile(rf'^{re.escape(prefix)}(\d+)$')
    max_index = 0
    for existing_id in existing_ids:
        match = pattern.match(existing_id)
        if match:
            max_index = max(max_index, int(match.group(1)))

    return f"{prefix}{max_index + 1:04d}"


def generate_temp_password(length: int = 12) -> str:
    """Génère un mot de passe temporaire aléatoire (cryptographiquement sûr)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def reset_password_action(get_utilisateur):
    """
    Fabrique une action d'admin "Réinitialiser le mot de passe" pour un ModelAdmin
    dont les objets exposent leur Utilisateur lié via `get_utilisateur(obj)`.
    Génère un nouveau mot de passe temporaire par objet sélectionné et l'affiche
    une seule fois (même logique que la création).
    """
    def reset_password(self, request, queryset):
        for obj in queryset:
            utilisateur = get_utilisateur(obj)
            new_password = generate_temp_password()
            utilisateur.password = make_password(new_password)
            utilisateur.save(update_fields=['password'])
            self.message_user(
                request,
                f"{utilisateur.id_utilisateur} ({utilisateur.prenom} {utilisateur.nom}) : "
                f"nouveau mot de passe temporaire : {new_password} — à noter maintenant, "
                f"il ne sera plus jamais affiché.",
                level=messages.WARNING,
            )
    reset_password.short_description = "Réinitialiser le mot de passe (génère un nouveau mot de passe temporaire)"
    return reset_password


# ------------------------------------------------------------------
# Chef région
# ------------------------------------------------------------------

class AgenceChoiceField(forms.ModelChoiceField):
    """ModelChoiceField dont le libellé signale quand une agence est déjà prise."""
    occupees = {}  # {agence_id: Utilisateur du chef région qui la détient déjà}

    def label_from_instance(self, obj):
        label = str(obj)
        occupant = self.occupees.get(obj.pk)
        if occupant:
            label = f"{label} — déjà assignée à {occupant.prenom} {occupant.nom}"
        return label


class ChefRegionForm(forms.ModelForm):
    nom = forms.CharField(max_length=100, label="Nom")
    prenom = forms.CharField(max_length=60, label="Prénom", required=False)
    email = forms.EmailField(max_length=200, label="Email")
    actif = forms.BooleanField(
        required=False,
        initial=True,
        label="Actif",
        help_text="Décocher pour désactiver ce compte (bloque sa connexion à l'application).",
    )
    agence = AgenceChoiceField(
        queryset=Agence.objects.none(),
        label="Agence",
        required=True,
        help_text=(
            "Un chef région ne peut être associé qu'à une seule agence. Si vous "
            "choisissez une agence déjà assignée à un autre chef région (utile en cas "
            "d'erreur d'affectation), elle lui sera automatiquement retirée."
        ),
    )

    class Meta:
        model = ChefRegion
        fields = []  # id_chef_region (PK OneToOne) est assigné dans save_model

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance') or self.instance

        if instance and instance.pk:
            utilisateur = instance.id_chef_region
            self.fields['nom'].initial = utilisateur.nom
            self.fields['prenom'].initial = utilisateur.prenom
            self.fields['email'].initial = utilisateur.email
            self.fields['actif'].initial = utilisateur.actif
            try:
                self.fields['agence'].initial = instance.chefregionpermission.id_agence
            except ChefRegionPermission.DoesNotExist:
                pass

        # Toutes les agences sont sélectionnables, y compris celles déjà prises par un
        # autre chef région : le libellé prévient l'admin, et la réaffectation retire
        # automatiquement l'agence à son détenteur actuel (gérée dans save_model).
        permissions_existantes = ChefRegionPermission.objects.exclude(
            id_chef_region=instance.pk if instance and instance.pk else None
        ).select_related('id_chef_region__id_chef_region')
        self.fields['agence'].occupees = {
            p.id_agence_id: p.id_chef_region.id_chef_region for p in permissions_existantes
        }
        self.fields['agence'].queryset = Agence.objects.order_by('nom_agence')


class ChefRegionAdmin(admin.ModelAdmin):
    form = ChefRegionForm
    list_display = ('id_chef_region', 'get_nom_complet', 'get_email', 'get_id_agence', 'get_actif')
    search_fields = ('id_chef_region__nom', 'id_chef_region__prenom', 'id_chef_region__email')
    actions = ['reset_password']

    reset_password = reset_password_action(lambda obj: obj.id_chef_region)

    def get_nom_complet(self, obj):
        return f"{obj.id_chef_region.prenom or ''} {obj.id_chef_region.nom}".strip()
    get_nom_complet.short_description = "Nom"

    def get_email(self, obj):
        return obj.id_chef_region.email
    get_email.short_description = "Email"

    def get_actif(self, obj):
        return obj.id_chef_region.actif
    get_actif.short_description = "Actif"
    get_actif.boolean = True

    def get_id_agence(self, obj):
        try:
            return obj.chefregionpermission.id_agence
        except ChefRegionPermission.DoesNotExist:
            return "—"
    get_id_agence.short_description = "Agence"

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            if not change:
                new_id = generate_next_id("UCR")
                temp_password = generate_temp_password()
                utilisateur = Utilisateur.objects.create(
                    id_utilisateur=new_id,
                    nom=form.cleaned_data['nom'],
                    prenom=form.cleaned_data['prenom'],
                    email=form.cleaned_data['email'],
                    password=make_password(temp_password),
                    date_prise_poste=timezone.now(),
                    actif=form.cleaned_data['actif'],
                )
                obj.id_chef_region = utilisateur
                obj.save()

                self.message_user(
                    request,
                    f"Chef région créé : {utilisateur.id_utilisateur} ({utilisateur.prenom} {utilisateur.nom}).",
                    level=messages.SUCCESS,
                )
                self.message_user(
                    request,
                    f"Mot de passe temporaire : {temp_password} — à noter maintenant, il ne sera plus jamais affiché.",
                    level=messages.WARNING,
                )
            else:
                utilisateur = obj.id_chef_region
                utilisateur.nom = form.cleaned_data['nom']
                utilisateur.prenom = form.cleaned_data['prenom']
                utilisateur.email = form.cleaned_data['email']
                utilisateur.actif = form.cleaned_data['actif']
                utilisateur.save()
                obj.save()

            agence = form.cleaned_data['agence']

            # Si cette agence est déjà assignée à un AUTRE chef région, on la lui retire
            # (réaffectation) : ce chef région-là se retrouve sans agence.
            ancienne_permission = ChefRegionPermission.objects.filter(
                id_agence=agence
            ).exclude(id_chef_region=obj).select_related('id_chef_region__id_chef_region').first()
            if ancienne_permission:
                ancien_utilisateur = ancienne_permission.id_chef_region.id_chef_region
                ancienne_permission.delete()
                self.message_user(
                    request,
                    f"L'agence {agence} a été retirée à {ancien_utilisateur.prenom} {ancien_utilisateur.nom} "
                    f"(qui se retrouve sans agence assignée) pour être réaffectée à ce chef région.",
                    level=messages.WARNING,
                )

            ChefRegionPermission.objects.update_or_create(
                id_chef_region=obj,
                defaults={'id_agence': agence},
            )


admin.site.register(ChefRegion, ChefRegionAdmin)


# ------------------------------------------------------------------
# Commercial
# ------------------------------------------------------------------

class CommercialForm(forms.ModelForm):
    nom = forms.CharField(max_length=100, label="Nom")
    prenom = forms.CharField(max_length=60, label="Prénom", required=False)
    email = forms.EmailField(max_length=200, label="Email")
    actif = forms.BooleanField(
        required=False,
        initial=True,
        label="Actif",
        help_text="Décocher pour désactiver ce compte (bloque sa connexion à l'application).",
    )
    agences = forms.ModelMultipleChoiceField(
        queryset=Agence.objects.all().order_by('nom_agence'),
        label="Agences",
        required=True,
        widget=admin.widgets.FilteredSelectMultiple("agences", is_stacked=False),
        help_text="Un commercial peut avoir accès à plusieurs agences.",
    )

    class Meta:
        model = Commercial
        fields = []  # id_commercial (PK OneToOne) est assigné dans save_model

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance') or self.instance

        if instance and instance.pk:
            utilisateur = instance.id_commercial
            self.fields['nom'].initial = utilisateur.nom
            self.fields['prenom'].initial = utilisateur.prenom
            self.fields['email'].initial = utilisateur.email
            self.fields['actif'].initial = utilisateur.actif
            self.fields['agences'].initial = Agence.objects.filter(
                commercialpermissionagence__id_commercial=instance
            )


class CommercialAdmin(admin.ModelAdmin):
    form = CommercialForm
    list_display = ('id_commercial', 'get_nom_complet', 'get_email', 'get_agences', 'get_actif')
    actions = ['reset_password']

    reset_password = reset_password_action(lambda obj: obj.id_commercial)
    search_fields = ('id_commercial__nom', 'id_commercial__prenom', 'id_commercial__email')

    class Media:
        # Nécessaire pour que le widget FilteredSelectMultiple s'affiche correctement
        # hors des champs déclarés directement sur le modèle (jQuery + SelectFilter2).
        js = ('admin/js/vendor/jquery/jquery.min.js', 'admin/js/jquery.init.js')

    def get_nom_complet(self, obj):
        return f"{obj.id_commercial.prenom or ''} {obj.id_commercial.nom}".strip()
    get_nom_complet.short_description = "Nom"

    def get_email(self, obj):
        return obj.id_commercial.email
    get_email.short_description = "Email"

    def get_actif(self, obj):
        return obj.id_commercial.actif
    get_actif.short_description = "Actif"
    get_actif.boolean = True

    def get_agences(self, obj):
        agences = Agence.objects.filter(commercialpermissionagence__id_commercial=obj)
        return ", ".join(a.nom_agence or a.id_agence for a in agences) or "—"
    get_agences.short_description = "Agences"

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            if not change:
                new_id = generate_next_id("UCO")
                temp_password = generate_temp_password()
                utilisateur = Utilisateur.objects.create(
                    id_utilisateur=new_id,
                    nom=form.cleaned_data['nom'],
                    prenom=form.cleaned_data['prenom'],
                    email=form.cleaned_data['email'],
                    password=make_password(temp_password),
                    date_prise_poste=timezone.now(),
                    actif=form.cleaned_data['actif'],
                )
                obj.id_commercial = utilisateur
                obj.save()
                CommercialPermission.objects.create(id_commercial=obj)

                self.message_user(
                    request,
                    f"Commercial créé : {utilisateur.id_utilisateur} ({utilisateur.prenom} {utilisateur.nom}).",
                    level=messages.SUCCESS,
                )
                self.message_user(
                    request,
                    f"Mot de passe temporaire : {temp_password} — à noter maintenant, il ne sera plus jamais affiché.",
                    level=messages.WARNING,
                )
            else:
                utilisateur = obj.id_commercial
                utilisateur.nom = form.cleaned_data['nom']
                utilisateur.prenom = form.cleaned_data['prenom']
                utilisateur.email = form.cleaned_data['email']
                utilisateur.actif = form.cleaned_data['actif']
                utilisateur.save()
                obj.save()
                CommercialPermission.objects.get_or_create(id_commercial=obj)

            self._sync_agences(obj, form.cleaned_data['agences'])

    def _sync_agences(self, commercial, selected_agences):
        selected_ids = set(a.pk for a in selected_agences)
        existing_qs = CommercialPermissionAgence.objects.filter(id_commercial=commercial)
        existing_ids = set(existing_qs.values_list('id_agence_id', flat=True))

        to_add = selected_ids - existing_ids
        to_remove = existing_ids - selected_ids

        for agence_id in to_add:
            CommercialPermissionAgence.objects.create(id_commercial=commercial, id_agence_id=agence_id)
        if to_remove:
            existing_qs.filter(id_agence_id__in=to_remove).delete()


admin.site.register(Commercial, CommercialAdmin)


# ------------------------------------------------------------------
# Signalement (ex: incohérence d'infos personnelles signalée par un utilisateur)
# ------------------------------------------------------------------

class SignalementAdmin(admin.ModelAdmin):
    list_display = ('id', 'get_utilisateur_lien', 'get_message_court', 'date_signalement', 'traite')
    list_filter = ('traite', 'date_signalement')
    list_editable = ('traite',)
    search_fields = ('utilisateur__nom', 'utilisateur__prenom', 'utilisateur__email', 'message')
    readonly_fields = ('get_utilisateur_lien', 'message', 'date_signalement')
    fields = ('get_utilisateur_lien', 'message', 'date_signalement', 'traite')
    date_hierarchy = 'date_signalement'

    def get_message_court(self, obj):
        return (obj.message[:80] + '…') if len(obj.message) > 80 else obj.message
    get_message_court.short_description = "Message"

    def get_utilisateur_lien(self, obj):
        """
        Lien cliquable vers la fiche d'édition (Chef région ou Commercial) de
        l'utilisateur concerné, pour corriger directement ses infos depuis le signalement.
        """
        utilisateur = obj.utilisateur
        label = f"{utilisateur.prenom or ''} {utilisateur.nom}".strip() or utilisateur.id_utilisateur

        try:
            cible = utilisateur.chefregion
            url_name = 'admin:commercial_chefregion_change'
        except ChefRegion.DoesNotExist:
            try:
                cible = utilisateur.commercial
                url_name = 'admin:commercial_commercial_change'
            except Commercial.DoesNotExist:
                return label  # aucun rôle connu (ni chef région, ni commercial) : pas de lien

        url = reverse(url_name, args=[cible.pk])
        return format_html('<a href="{}">{}</a>', url, label)
    get_utilisateur_lien.short_description = "Utilisateur"

    def has_add_permission(self, request):
        # Les signalements sont créés depuis l'interface Chef de région, pas depuis l'admin.
        return False


admin.site.register(Signalement, SignalementAdmin)


admin.site.site_header = "Provixa"
admin.site.site_title = "Provixa"
admin.site.index_header = "Provixa"
