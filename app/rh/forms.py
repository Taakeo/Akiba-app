from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateField, IntegerField, RadioField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError

from ..models import FREQUENCES_REMUNERATION, TYPES_ABSENCE, TYPES_CONTRAT, TYPES_REMUNERATION


class SalarieForm(FlaskForm):
    nom = StringField("Nom complet", validators=[DataRequired(), Length(max=150)])
    telephone = StringField("Téléphone", validators=[Optional(), Length(max=50)])
    fonction = StringField("Fonction", validators=[Optional(), Length(max=120)])
    type_contrat = SelectField(
        "Type de contrat", choices=[(t, t) for t in TYPES_CONTRAT], validators=[Optional()]
    )
    date_embauche = DateField("Date d'embauche", validators=[Optional()])
    poste_id = SelectField("Poste", coerce=int, validators=[Optional()])
    projet_id = SelectField("Projet", coerce=int, validators=[Optional()])

    # Facultatif à la création (ex. bénévole, ou salaire à négocier plus
    # tard) — sert de référence au compte salarié pour savoir ce qui est dû.
    salaire_habituel = IntegerField("Salaire habituel", validators=[Optional(), NumberRange(min=0)])
    frequence_remuneration = SelectField(
        "Fréquence de versement",
        choices=[("", "—")] + FREQUENCES_REMUNERATION,
        validators=[Optional()],
    )
    quota_conges = IntegerField(
        "Quota de congés payés (jours/an)", validators=[Optional(), NumberRange(min=0)]
    )


class ImportSalariesForm(FlaskForm):
    fichier = FileField(
        "Fichier Excel",
        validators=[
            FileRequired("Choisissez un fichier .xlsx à importer."),
            FileAllowed(["xlsx"], "Formats accepté : XLSX (le modèle téléchargeable ci-dessus)."),
        ],
    )


class RemunerationForm(FlaskForm):
    type_remuneration = SelectField("Type", choices=TYPES_REMUNERATION, validators=[DataRequired()])
    montant = IntegerField("Montant", validators=[InputRequired(), NumberRange(min=1)])
    date_versement = DateField("Date", validators=[DataRequired()], default=date.today)
    moyen_paiement_id = SelectField("Moyen de paiement", coerce=int, validators=[Optional()])
    observations = TextAreaField("Observations", validators=[Optional()])


class AbsenceForm(FlaskForm):
    # RadioField (pas SelectField) : affiché en pilules cliquables sur la
    # fiche salarié, pas en menu déroulant — voir la note équivalente sur
    # AchatForm.type_achat.
    type_absence = RadioField("Type", choices=TYPES_ABSENCE, validators=[DataRequired()])
    date_debut = DateField("Du", validators=[DataRequired()], default=date.today)
    date_fin = DateField("Au", validators=[DataRequired()], default=date.today)
    observations = TextAreaField("Observations", validators=[Optional()])

    def validate_date_fin(self, field):
        if self.date_debut.data and field.data and field.data < self.date_debut.data:
            raise ValidationError("La date de fin doit être postérieure ou égale à la date de début.")
