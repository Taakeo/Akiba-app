from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, MultipleFileField
from wtforms import DateField, IntegerField, RadioField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

DOCUMENTS_AUTORISES = ["pdf", "jpg", "jpeg", "png", "webp"]


class AchatForm(FlaskForm):
    nom = StringField("Nom de l'achat", validators=[Optional(), Length(max=150)])
    # RadioField (pas SelectField) : ce champ est affiché en pilules cliquables
    # dans le template, pas en menu déroulant — un SelectField y produirait des
    # balises <option> orphelines (texte dupliqué, aucun input cliquable).
    type_achat = RadioField(
        "Type d'achat",
        choices=[("stock", "Achat de stock"), ("depense", "Dépense générale")],
        validators=[DataRequired()],
    )
    fournisseur_id = SelectField("Fournisseur", coerce=int, validators=[Optional()])
    date_achat = DateField("Date", validators=[DataRequired()], default=date.today)

    poste_id = SelectField("Poste", coerce=int, validators=[DataRequired()])
    projet_id = SelectField("Projet", coerce=int, validators=[Optional()])
    categorie_id = SelectField("Catégorie", coerce=int, validators=[DataRequired()])
    sous_categorie_id = SelectField("Sous-catégorie", coerce=int, validators=[Optional()])

    produit_id = SelectField("Produit", coerce=int, validators=[Optional()])
    quantite = IntegerField("Quantité", validators=[Optional(), NumberRange(min=1)])
    prix_unitaire = IntegerField("Prix unitaire", validators=[Optional(), NumberRange(min=0)])
    # InputRequired (pas Optional) uniquement pertinent pour une dépense
    # générale — un achat de stock calcule son montant depuis
    # quantité×prix_unitaire (voir la route) et laisse ce champ vide, d'où
    # la validation conditionnelle faite dans la route plutôt qu'ici (retour
    # utilisateur du 08/08/2026 : le montant d'une dépense ne doit plus
    # jamais être facultatif).
    montant_total = IntegerField("Montant de la dépense", validators=[Optional(), NumberRange(min=0)])

    # Choix explicite obligatoire entre le tiroir physique PDV et le Compte
    # Akiba — même patron que MouvementCaisseForm.origine (retour
    # utilisateur du 08/08/2026) : détermine les moyens de paiement proposés
    # et si le tiroir doit s'ouvrir à l'enregistrement.
    origine = RadioField(
        "Compte à débiter",
        choices=[("pdv", "Caisse PDV (tiroir physique)"), ("coffre_fort", "Compte Akiba (coffre-fort)")],
        validators=[DataRequired()],
    )
    moyen_paiement_id = SelectField("Moyen de paiement", coerce=int, validators=[DataRequired()])
    observations = TextAreaField("Observations", validators=[Optional()])

    documents = MultipleFileField(
        "Pièces jointes (facture, devis, photo, bon de livraison)",
        validators=[FileAllowed(DOCUMENTS_AUTORISES, "Formats acceptés : PDF, JPG, PNG, WEBP.")],
    )


class AchatModifierForm(FlaskForm):
    """Édition d'un achat déjà enregistré : type, produit, quantité, prix et
    moyen de paiement ne sont plus modifiables (stock et caisse déjà mis à
    jour en conséquence) — seul le classement/la traçabilité peut être
    corrigé, comme pour la fabrication."""

    nom = StringField("Nom de l'achat", validators=[Optional(), Length(max=150)])
    fournisseur_id = SelectField("Fournisseur", coerce=int, validators=[Optional()])
    date_achat = DateField("Date", validators=[DataRequired()])
    poste_id = SelectField("Poste", coerce=int, validators=[DataRequired()])
    projet_id = SelectField("Projet", coerce=int, validators=[Optional()])
    categorie_id = SelectField("Catégorie", coerce=int, validators=[DataRequired()])
    sous_categorie_id = SelectField("Sous-catégorie", coerce=int, validators=[Optional()])
    observations = TextAreaField("Observations", validators=[Optional()])
    documents = MultipleFileField(
        "Pièces jointes (facture, devis, photo, bon de livraison)",
        validators=[FileAllowed(DOCUMENTS_AUTORISES, "Formats acceptés : PDF, JPG, PNG, WEBP.")],
    )


class AchatRecurrentForm(FlaskForm):
    nom = StringField("Nom du modèle (ex. Bois de chauffe, Wifi, Bouffe cantine)", validators=[DataRequired()])
    type_achat = SelectField(
        "Type d'achat",
        choices=[("stock", "Achat de stock"), ("depense", "Dépense générale")],
        validators=[DataRequired()],
    )
    fournisseur_id = SelectField("Fournisseur", coerce=int, validators=[Optional()])
    poste_id = SelectField("Poste", coerce=int, validators=[DataRequired()])
    projet_id = SelectField("Projet", coerce=int, validators=[Optional()])
    categorie_id = SelectField("Catégorie", coerce=int, validators=[DataRequired()])
    sous_categorie_id = SelectField("Sous-catégorie", coerce=int, validators=[Optional()])
    produit_id = SelectField("Produit", coerce=int, validators=[Optional()])
    quantite_habituelle = IntegerField("Quantité habituelle", validators=[Optional(), NumberRange(min=1)])
    prix_unitaire_habituel = IntegerField("Prix unitaire habituel", validators=[Optional(), NumberRange(min=0)])
    montant_habituel = IntegerField("Montant habituel (dépense)", validators=[Optional(), NumberRange(min=0)])
    moyen_paiement_id = SelectField("Moyen de paiement habituel", coerce=int, validators=[Optional()])
