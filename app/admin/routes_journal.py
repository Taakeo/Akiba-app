from datetime import datetime, time

from flask import current_app, render_template, request

from ..auth.decorators import permission_required
from . import bp
from .journal_service import MODULES, construire_journal


def _parse_date(valeur, fin_de_journee=False):
    if not valeur:
        return None
    try:
        d = datetime.strptime(valeur, "%Y-%m-%d").date()
    except ValueError:
        return None
    heure = time.max if fin_de_journee else time.min
    # Naïf (sans tzinfo), aligné sur ce que SQLite renvoie réellement pour les
    # colonnes DateTime(timezone=True) — voir la note dans journal_service.py.
    return datetime.combine(d, heure)


@bp.route("/journal")
@permission_required("admin")
def journal():
    filtre_depuis = request.args.get("depuis", "")
    filtre_jusqua = request.args.get("jusqua", "")
    filtre_utilisateur = request.args.get("utilisateur", "").strip()
    filtre_module = request.args.get("module", "").strip() or None

    entrees = construire_journal(
        current_app,
        depuis=_parse_date(filtre_depuis),
        jusqua=_parse_date(filtre_jusqua, fin_de_journee=True),
        utilisateur=filtre_utilisateur or None,
        module=filtre_module,
        limite=300,
    )

    return render_template(
        "admin/journal.html",
        entrees=entrees,
        modules=MODULES,
        filtre_depuis=filtre_depuis,
        filtre_jusqua=filtre_jusqua,
        filtre_utilisateur=filtre_utilisateur,
        filtre_module=filtre_module or "",
    )
