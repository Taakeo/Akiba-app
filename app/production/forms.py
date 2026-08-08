from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional


class FabricationForm(FlaskForm):
    # Pas de champ "responsable" : c'est toujours l'utilisateur connecté qui
    # déclare, non modifiable (traçabilité — voir Fabrication.responsable_nom
    # rempli depuis current_user côté route).
    produit_id = SelectField("Produit fabriqué", coerce=int, validators=[DataRequired()])
    quantite = IntegerField("Quantité", validators=[InputRequired(), NumberRange(min=1)])
    date_fabrication = DateField("Date de fabrication", validators=[DataRequired()], default=date.today)

    numero_lot = StringField("Numéro de lot", validators=[Optional(), Length(max=64)])
    ddm_dlc = DateField("DDM / DLC", validators=[Optional()])
    observations = TextAreaField("Note", validators=[Optional()])


class FabricationModifierForm(FlaskForm):
    """Édition d'une fabrication déjà enregistrée : quantité et produit ne
    sont plus modifiables (le mouvement de stock a déjà été appliqué), pour
    ne pas fausser le stock après coup. Seule la traçabilité reste éditable."""

    date_fabrication = DateField("Date de fabrication", validators=[DataRequired()])
    numero_lot = StringField("Numéro de lot", validators=[Optional(), Length(max=64)])
    ddm_dlc = DateField("DDM / DLC", validators=[Optional()])
    observations = TextAreaField("Note", validators=[Optional()])
