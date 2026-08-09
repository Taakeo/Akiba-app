from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from . import bp
from .backup_service import (
    BackupError,
    creer_sauvegarde,
    creer_sauvegarde_externe,
    dossier_sauvegardes_actuel,
    ecrire_destination_sauvegarde,
    espace_disque_disponible,
    lire_audit_log,
    lire_destination_sauvegarde,
    lister_lecteurs_disponibles,
    lister_sauvegardes,
    restaurer_sauvegarde,
)


@bp.route("/sauvegardes")
@permission_required("admin")
def sauvegardes():
    items = lister_sauvegardes(current_app)
    audit = lire_audit_log(current_app, limite=30)
    dossier_actuel = dossier_sauvegardes_actuel(current_app)
    espace = espace_disque_disponible(dossier_actuel)
    return render_template(
        "admin/sauvegardes.html",
        items=items,
        audit=audit,
        dossier_actuel=dossier_actuel,
        destination_configuree=lire_destination_sauvegarde(current_app),
        espace_libre=espace[0] if espace else None,
        espace_total=espace[1] if espace else None,
        lecteurs=lister_lecteurs_disponibles(),
    )


@bp.route("/sauvegardes/destination", methods=["POST"])
@permission_required("admin")
def sauvegarde_destination():
    dossier = request.form.get("dossier_destination", "")
    try:
        ecrire_destination_sauvegarde(current_app, dossier)
        if dossier.strip():
            flash(f"Les sauvegardes seront désormais créées dans « {dossier.strip()} ».", "info")
        else:
            flash("Retour au dossier de sauvegarde par défaut.", "info")
    except BackupError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.sauvegardes"))


@bp.route("/sauvegardes/nouvelle", methods=["POST"])
@permission_required("admin")
def sauvegarde_nouvelle():
    try:
        nom = creer_sauvegarde(current_app, current_user)
        flash(f"Sauvegarde {nom} créée.", "info")
    except BackupError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.sauvegardes"))


@bp.route("/sauvegardes/nouvelle-externe/<lettre>", methods=["POST"])
@permission_required("admin")
def sauvegarde_nouvelle_externe(lettre):
    """Sauvegarde manuelle vers un disque externe/clé USB détecté
    automatiquement — seule vraie protection contre la perte totale du
    poste. `lettre` est revalidée ici plutôt qu'acceptée telle quelle : un
    disque débranché entre l'affichage de la page et le clic ne doit jamais
    planter l'application, juste afficher un message clair."""
    lettre = lettre.upper()
    if lettre not in {l["lettre"] for l in lister_lecteurs_disponibles()}:
        flash(f"Le lecteur {lettre}: n'est plus disponible — vérifiez qu'il est bien branché et réessayez.", "error")
        return redirect(url_for("admin.sauvegardes"))

    try:
        nom = creer_sauvegarde_externe(current_app, current_user, lettre)
        flash(f"Sauvegarde {nom} créée sur le lecteur {lettre}:.", "info")
    except BackupError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.sauvegardes"))


@bp.route("/sauvegardes/<nom>/restaurer", methods=["POST"])
@permission_required("admin")
def sauvegarde_restaurer(nom):
    try:
        restaurer_sauvegarde(current_app, nom, current_user)
        flash(
            f"Sauvegarde {nom} restaurée. Redémarrez l'application pour repartir sur une base saine.",
            "info",
        )
    except BackupError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.sauvegardes"))
