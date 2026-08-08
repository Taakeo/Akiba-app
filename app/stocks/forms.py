from flask_wtf import FlaskForm
from wtforms import IntegerField, RadioField, SelectField, StringField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional

# Motifs saisissables manuellement — achat/fabrication/vente sont générés
# automatiquement par leurs modules respectifs (§9.2 spec).
MOTIFS_ENTREE_MANUELS = [("retour_client", "Retour client"), ("don", "Don"), ("correction", "Correction")]
MOTIFS_SORTIE_MANUELS = [
    ("perte", "Perte"),
    ("consommation_interne", "Consommation interne"),
    ("don", "Don"),
    ("correction", "Correction"),
]


class AjustementForm(FlaskForm):
    produit_id = SelectField("Produit", coerce=int, validators=[DataRequired()])
    type_mouvement = RadioField(
        "Sens",
        choices=[("entree", "Entrée"), ("sortie", "Sortie")],
        validators=[DataRequired()],
    )
    motif_entree = SelectField("Motif", choices=MOTIFS_ENTREE_MANUELS, validators=[Optional()])
    motif_sortie = SelectField("Motif", choices=MOTIFS_SORTIE_MANUELS, validators=[Optional()])
    quantite = IntegerField("Quantité", validators=[InputRequired(), NumberRange(min=1)])
    commentaire = StringField("Commentaire", validators=[Optional()])


class InventaireForm(FlaskForm):
    type_inventaire = SelectField(
        "Portée",
        choices=[("general", "Général"), ("categorie", "Par catégorie"), ("produit", "Par produit")],
        validators=[DataRequired()],
    )
    categorie_id = SelectField("Catégorie", coerce=int, validators=[Optional()])
    produit_id = SelectField("Produit", coerce=int, validators=[Optional()])
