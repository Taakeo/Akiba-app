from flask import Blueprint

bp = Blueprint("stocks", __name__, template_folder="../templates/stocks")

from . import routes  # noqa: E402,F401
