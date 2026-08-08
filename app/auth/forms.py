from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Regexp


class PinForm(FlaskForm):
    pin = StringField(
        "Code PIN",
        validators=[
            DataRequired(message="Le code PIN est obligatoire."),
            Regexp(r"^\d{4}$", message="Le code PIN doit contenir exactement 4 chiffres."),
        ],
    )
