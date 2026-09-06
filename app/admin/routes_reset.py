from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from . import bp
from .reset_service import ReinitialisationError, reinitialiser_pour_production, resume_avant_reinitialisation

PHRASE_CONFIRMATION = "RÉINITIALISER"


@bp.route("/reinitialisation", methods=["GET", "POST"])
@permission_required("admin")
def reinitialisation():
    if request.method == "POST":
        if (request.form.get("confirmation") or "").strip().upper() != PHRASE_CONFIRMATION:
            flash(f'Tapez exactement « {PHRASE_CONFIRMATION} » pour confirmer.', "error")
            return render_template(
                "admin/reinitialisation.html", phrase=PHRASE_CONFIRMATION, resume=resume_avant_reinitialisation()
            )

        try:
            horodatage = reinitialiser_pour_production(current_app, current_user)
        except ReinitialisationError as exc:
            flash(str(exc), "error")
            return render_template(
                "admin/reinitialisation.html", phrase=PHRASE_CONFIRMATION, resume=resume_avant_reinitialisation()
            )

        flash(
            f"Base réinitialisée pour le lancement en production. Une sauvegarde complète de l'état "
            f"précédent a été conservée ({horodatage}) avant toute suppression.",
            "info",
        )
        return redirect(url_for("admin.index"))

    return render_template(
        "admin/reinitialisation.html", phrase=PHRASE_CONFIRMATION, resume=resume_avant_reinitialisation()
    )
