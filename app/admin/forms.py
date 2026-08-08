from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import BooleanField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional

PHOTO_FORMATS_AUTORISES = ["jpg", "jpeg", "png", "webp"]


class FournisseurForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=150)])
    telephone = StringField("Téléphone", validators=[Optional(), Length(max=50)])
    email = StringField("E-mail", validators=[Optional(), Length(max=120)])
    adresse = TextAreaField("Adresse", validators=[Optional()])
    observations = TextAreaField("Note", validators=[Optional()])


class CompteFinancierForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    devise = SelectField("Devise", choices=[("Ar", "Ariary (Ar)"), ("€", "Euro (€)")], validators=[DataRequired()])
    is_caisse_physique = BooleanField("Tiroir-caisse physique du PDV (ouverture/clôture de session)")
    is_compte_akiba = BooleanField("Compte Akiba (reçoit le prélèvement à chaque clôture de caisse)")
    visible_tableau_bord = BooleanField("Visible dans le bloc « Comptes » du tableau de bord", default=True)


class AjustementCompteForm(FlaskForm):
    nouveau_solde = IntegerField("Solde réel du compte", validators=[InputRequired()])
    motif = TextAreaField(
        "Motif",
        validators=[DataRequired(message="Le motif est obligatoire pour tracer cette correction.")],
    )


class MoyenPaiementForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    compte_financier_id = SelectField("Compte financier (où l'argent atterrit)", coerce=int, validators=[DataRequired()])
    ouvre_tiroir = BooleanField("Ouvre le tiroir-caisse (impulsion imprimante)")
    is_default = BooleanField("Présélectionné par défaut au PDV et dans les formulaires")
    visible_pdv = BooleanField(
        "Proposé à l'encaissement du PDV (décocher pour un moyen réservé aux achats/mouvements, ex. Compte Akiba)",
        default=True,
    )


class PosteForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    icon = StringField("Icône (Material Symbols)", validators=[Optional(), Length(max=50)], default="storefront")


class ProjetForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])


class CategorieForm(FlaskForm):
    poste_id = SelectField("Poste", coerce=int, validators=[DataRequired()])
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    icon = StringField("Icône (Material Symbols)", validators=[Optional(), Length(max=50)], default="category")
    ordre = IntegerField("Ordre d'affichage", validators=[Optional(), NumberRange(min=0)], default=0)


class SousCategorieForm(FlaskForm):
    categorie_id = SelectField("Catégorie", coerce=int, validators=[DataRequired()])
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])


class ProduitForm(FlaskForm):
    name = StringField("Nom du produit", validators=[DataRequired(), Length(max=200)])
    poste_id = SelectField("Poste", coerce=int, validators=[DataRequired()])
    projet_id = SelectField("Projet", coerce=int, validators=[Optional()])
    categorie_id = SelectField("Catégorie", coerce=int, validators=[DataRequired()])
    sous_categorie_id = SelectField("Sous-catégorie", coerce=int, validators=[Optional()])
    fournisseur_principal_id = SelectField("Fournisseur principal", coerce=int, validators=[Optional()])
    unite = StringField("Unité", validators=[Optional(), Length(max=30)], default="unité")
    prix_achat = IntegerField("Prix d'achat", validators=[Optional(), NumberRange(min=0)])
    prix_reference = IntegerField("Prix de référence", validators=[Optional(), NumberRange(min=0)])
    stock_illimite = BooleanField("Stock illimité (ex. visite guidée, service sans stock physique)")
    prix_libre = BooleanField("Prix libre à la vente (montant saisi à chaque ajout au panier, ex. Pourboire)")
    seuil_alerte = IntegerField("Seuil d'alerte de stock", validators=[Optional(), NumberRange(min=0)])
    stock_quantite = IntegerField("Stock actuel", validators=[InputRequired(), NumberRange(min=0)], default=0)
    code_barres = StringField("Code-barres", validators=[Optional(), Length(max=64)])
    photo = FileField(
        "Photo du produit",
        validators=[FileAllowed(PHOTO_FORMATS_AUTORISES, "Formats acceptés : JPG, PNG ou WEBP.")],
    )


class ImportProduitsForm(FlaskForm):
    fichier = FileField(
        "Fichier Excel",
        validators=[
            FileRequired("Choisissez un fichier .xlsx à importer."),
            FileAllowed(["xlsx"], "Formats accepté : XLSX (le modèle téléchargeable ci-dessus)."),
        ],
    )


class ParametresImprimanteForm(FlaskForm):
    nom_imprimante = StringField(
        "Nom de l'imprimante (tel qu'installée dans Windows)",
        validators=[DataRequired(), Length(max=150)],
    )


class TypeTarifForm(FlaskForm):
    label = StringField("Nom du tarif", validators=[DataRequired(), Length(max=80)])


class ParametresLegauxForm(FlaskForm):
    raison_sociale = StringField("Nom / raison sociale", validators=[DataRequired(), Length(max=200)])
    adresse = TextAreaField("Adresse", validators=[Optional()])
    telephone = StringField("Téléphone", validators=[Optional(), Length(max=50)])
    email = StringField("E-mail", validators=[Optional(), Length(max=120)])
    nif = StringField("NIF", validators=[Optional(), Length(max=50)])
    stat = StringField("STAT", validators=[Optional(), Length(max=50)])
    rcs = StringField("RCS / registre de commerce", validators=[Optional(), Length(max=50)])


class ParametresRHForm(FlaskForm):
    quota_conges_defaut = IntegerField(
        "Quota de congés payés par défaut (jours/an)",
        validators=[DataRequired(), NumberRange(min=0)],
    )


class TauxChangeForm(FlaskForm):
    ariary_pour_un_euro = IntegerField(
        "Ariary pour 1 euro",
        validators=[DataRequired(), NumberRange(min=1)],
    )


class RabaisTarifForm(FlaskForm):
    pourcentage_rabais = IntegerField(
        "Pourcentage de rabais", validators=[Optional(), NumberRange(min=0, max=100)]
    )
    rabais_actif = BooleanField("Rabais actif", validators=[Optional()])


class ProfileForm(FlaskForm):
    # Les permissions ne passent pas par un champ WTForms classique : rendues
    # comme des cases à cocher indépendantes dans le template
    # (name="permissions", plusieurs valeurs), lues via request.form.getlist()
    # côté route — un profil peut avoir 0, 1 ou N droits, une liste WTForms
    # à choix fixes n'apporterait rien ici.
    name = StringField("Nom du profil", validators=[DataRequired(), Length(max=80)])
    icon = StringField("Icône (Material Symbols)", validators=[Optional(), Length(max=50)], default="badge")


class SubProfileForm(FlaskForm):
    # Pas de champ PIN ici : le code est généré aléatoirement à la création
    # (voir app/models/user.py::generer_pin) et affiché une seule fois.
    profile_id = SelectField("Profil", coerce=int, validators=[DataRequired()])
    full_name = StringField("Nom complet", validators=[DataRequired(), Length(max=120)])
