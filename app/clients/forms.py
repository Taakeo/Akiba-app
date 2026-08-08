from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional

from ..models import TYPES_CLIENT


class ClientForm(FlaskForm):
    type_client = SelectField("Type", choices=TYPES_CLIENT, validators=[DataRequired()])
    nom = StringField("Nom", validators=[DataRequired(), Length(max=150)])
    telephone = StringField("Téléphone", validators=[Optional(), Length(max=50)])
    email = StringField("E-mail", validators=[Optional(), Length(max=120)])
    adresse = TextAreaField("Adresse", validators=[Optional()])
    observations = TextAreaField("Observations", validators=[Optional()])


class ClientPaiementForm(FlaskForm):
    montant = IntegerField("Montant", validators=[InputRequired(), NumberRange(min=1)])
    moyen_paiement_id = SelectField("Moyen de paiement", coerce=int, validators=[DataRequired()])
    date_paiement = DateField("Date", validators=[DataRequired()], default=date.today)
    observations = TextAreaField("Observations", validators=[Optional()])
