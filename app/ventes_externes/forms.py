from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class VenteExterneForm(FlaskForm):
    # Les deux modes demandés : une fiche client existante recherchée dans la
    # liste (client_id) OU un client de passage en texte libre (client_nom),
    # exactement comme au PDV — validation du choix fait dans la route (au
    # moins l'un des deux, jamais les deux à la fois n'est imposé ici pour
    # rester simple : client_id prime s'il est renseigné).
    client_id = SelectField("Client enregistré", coerce=int, validators=[Optional()])
    client_nom = StringField("Ou client de passage (texte libre)", validators=[Optional(), Length(max=150)])

    date_vente = DateField("Date", validators=[DataRequired()], default=date.today)

    poste_id = SelectField("Poste", coerce=int, validators=[DataRequired()])
    projet_id = SelectField("Projet", coerce=int, validators=[Optional()])
    categorie_id = SelectField("Catégorie", coerce=int, validators=[DataRequired()])
    sous_categorie_id = SelectField("Sous-catégorie", coerce=int, validators=[Optional()])

    # Renseigné seulement si l'objet vendu est un produit catalogué (déduit
    # alors le stock, comme une vente PDV) — laissé vide pour un objet non
    # catalogué (meuble...) ou une entrée libre (don, financement).
    produit_id = SelectField("Produit catalogué (facultatif)", coerce=int, validators=[Optional()])
    quantite = IntegerField("Quantité", validators=[Optional(), NumberRange(min=1)])
    prix_unitaire = IntegerField("Prix unitaire", validators=[Optional(), NumberRange(min=0)])
    montant_total = IntegerField("Montant total", validators=[Optional(), NumberRange(min=0)])

    moyen_paiement_id = SelectField("Moyen de paiement", coerce=int, validators=[DataRequired()])
    observations = TextAreaField(
        "Observations",
        validators=[Optional()],
        description="Utile pour préciser la nature de la rentrée (don, financement, objet vendu...).",
    )
