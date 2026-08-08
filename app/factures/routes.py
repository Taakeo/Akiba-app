from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from ..auth.decorators import permission_required, permission_required_any
from ..extensions import db
from ..models import Client, Facture, Vente
from . import bp
from .pdf import generer_facture_pdf
from .services import FactureError, generer_facture


@bp.route("/depuis-vente/<int:vente_id>", methods=["POST"])
@permission_required("point_de_vente")
def depuis_vente(vente_id):
    vente = db.session.get(Vente, vente_id)
    if vente is None:
        abort(404)
    if vente.client_id is None:
        flash("Une facture officielle nécessite un client enregistré (pas un client de passage).", "error")
        return redirect(url_for("pos.recu", vente_id=vente.id))

    client = db.session.get(Client, vente.client_id)
    try:
        facture = generer_facture(client, [vente], current_user)
    except FactureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("pos.recu", vente_id=vente.id))

    flash(f"Facture {facture.numero} créée.", "info")
    return redirect(url_for("factures.voir", facture_id=facture.id))


@bp.route("/depuis-client/<int:client_id>", methods=["POST"])
@permission_required("clients")
def depuis_client(client_id):
    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)

    vente_ids = [int(v) for v in request.form.getlist("vente_ids")]
    ventes = [db.session.get(Vente, vid) for vid in vente_ids]
    ventes = [v for v in ventes if v is not None]

    try:
        facture = generer_facture(client, ventes, current_user)
    except FactureError as exc:
        flash(str(exc), "error")
        return redirect(url_for("clients.fiche", client_id=client.id))

    flash(f"Facture {facture.numero} créée.", "info")
    return redirect(url_for("factures.voir", facture_id=facture.id))


@bp.route("/<int:facture_id>")
@permission_required_any("point_de_vente", "clients")
def voir(facture_id):
    facture = db.session.get(Facture, facture_id)
    if facture is None:
        abort(404)
    return render_template("factures/voir.html", facture=facture)


@bp.route("/<int:facture_id>/pdf")
@permission_required_any("point_de_vente", "clients")
def telecharger(facture_id):
    facture = db.session.get(Facture, facture_id)
    if facture is None:
        abort(404)
    buffer = generer_facture_pdf(facture)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{facture.numero}.pdf",
        mimetype="application/pdf",
    )
