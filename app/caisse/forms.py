from flask_wtf import FlaskForm
from wtforms import IntegerField, RadioField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional


class OuvertureCaisseForm(FlaskForm):
    # InputRequired (pas DataRequired) : DataRequired traite 0 comme "absent" car
    # falsy en Python, ce qui bloquerait une ouverture de caisse à fond nul.
    fond_ouverture = IntegerField(
        "Fond de caisse initial",
        validators=[InputRequired(message="Le fond de caisse est obligatoire."), NumberRange(min=0)],
        default=0,
    )


class FermetureCaisseForm(FlaskForm):
    fond_reel = IntegerField(
        "Contenu réel du tiroir",
        validators=[InputRequired(message="Le montant compté est obligatoire."), NumberRange(min=0)],
    )
    # Ce qui est physiquement prélevé du tiroir pour rejoindre le Compte
    # Akiba — le reste sert de fond d'ouverture suggéré pour la prochaine
    # session (retour utilisateur du 08/08/2026). InputRequired (pas
    # DataRequired) : 0 est une valeur valide (tout laissé dans le tiroir).
    montant_preleve = IntegerField(
        "Montant prélevé (vers le Compte Akiba)",
        validators=[InputRequired(message="Indiquez ce qui est prélevé, même 0."), NumberRange(min=0)],
    )
    commentaire = TextAreaField("Commentaire de clôture", validators=[Optional()])


class TauxChangeCaisseForm(FlaskForm):
    ariary_pour_un_euro = IntegerField("Ariary pour 1 euro", validators=[InputRequired(), NumberRange(min=1)])


class MouvementCaisseForm(FlaskForm):
    type_mouvement = RadioField(
        "Type",
        choices=[("entree", "Entrée d'argent"), ("sortie", "Sortie d'argent")],
        validators=[DataRequired()],
    )
    # Choix explicite obligatoire entre le tiroir physique de ce poste et un
    # compte Akiba (banque, mobile money...) — évite qu'un mouvement soit
    # enregistré sur le mauvais compte sans que personne s'en rende compte
    # (retour utilisateur : aucune distinction visible auparavant, un simple
    # menu déroulant mélangeant tous les moyens).
    origine = RadioField(
        "Origine",
        choices=[("pdv", "Caisse PDV (tiroir physique)"), ("coffre_fort", "Compte Akiba (coffre-fort)")],
        validators=[DataRequired()],
    )
    montant = IntegerField("Montant", validators=[InputRequired(), NumberRange(min=1)])
    moyen_paiement_id = SelectField("Moyen de paiement", coerce=int, validators=[DataRequired()])
    motif = StringField("Motif", validators=[DataRequired(message="Le motif est obligatoire.")])
