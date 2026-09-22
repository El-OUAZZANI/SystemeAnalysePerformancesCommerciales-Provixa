from django import template

register = template.Library()


@register.filter(name='montant_fr')
def montant_fr(valeur, decimales=2):
    """
    Formate un nombre à la française : espace comme séparateur de milliers,
    virgule comme séparateur décimal (ex: 12345.6 -> "12 345,60").
    Utilisé pour l'affichage des montants (CA, prix) dans les templates.
    """
    try:
        valeur = float(valeur)
        decimales = int(decimales)
    except (TypeError, ValueError):
        return valeur

    texte = f"{valeur:,.{decimales}f}"  # ex: "12,345.60" (convention US)
    entier, _, decimale = texte.partition('.')
    entier = entier.replace(',', ' ')  # espace insécable comme séparateur de milliers
    return f"{entier},{decimale}" if decimales else entier
