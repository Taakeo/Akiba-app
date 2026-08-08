from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from ..caisse.services import crediter_compte, montant_en_ariary
from ..extensions import db
from ..models import Client, ClientPaiement, MoyenPaiement, Vente, moyen_paiement_par_defaut, verifier_suppression_client
from . import bp
from .forms import ClientForm, ClientPaiementForm


@bp.route("/")
@permission_required("clients")
def index():
    recherche = request.args.get("q", "").strip()
    query = Client.query
    if recherche:
        query = query.filter(Client.nom.ilike(f"%{recherche}%"))
    items = query.order_by(Client.is_archived, Client.nom).all()
    return render_template("clients/index.html", items=items, recherche=recherche)


@bp.route("/nouveau", methods=["GET", "POST"])
@permission_required("clients")
def nouveau():
    form = ClientForm()
    if form.validate_on_submit():
        client = Client(
            type_client=form.type_client.data,
            nom=form.nom.data,
            telephone=form.telephone.data or None,
            email=form.email.data or None,
            adresse=form.adresse.data or None,
            observations=form.observations.data or None,
        )
        db.session.add(client)
        db.session.commit()
        flash(f"Client {client.nom} créé.", "info")
        return redirect(url_for("clients.index"))

    return render_template("clients/form.html", form=form, client=None)


@bp.route("/<int:client_id>/modifier", methods=["GET", "POST"])
@permission_required("clients")
def modifier(client_id):
    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)

    form = ClientForm(obj=client)
    if form.validate_on_submit():
        client.type_client = form.type_client.data
        client.nom = form.nom.data
        client.telephone = form.telephone.data or None
        client.email = form.email.data or None
        client.adresse = form.adresse.data or None
        client.observations = form.observations.data or None
        db.session.commit()
        flash("Fiche client mise à jour.", "info")
        return redirect(url_for("clients.index"))

    return render_template("clients/form.html", form=form, client=client)


@bp.route("/<int:client_id>/archiver", methods=["POST"])
@permission_required("clients")
def toggle_archive(client_id):
    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)
    client.is_archived = not client.is_archived
    db.session.commit()
    return redirect(url_for("clients.index"))


@bp.route("/<int:client_id>/supprimer", methods=["POST"])
@permission_required("clients")
def supprimer(client_id):
    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)
    raison = verifier_suppression_client(client)
    if raison:
        flash(f"Impossible de supprimer « {client.nom} » définitivement : {raison}.", "error")
        return redirect(url_for("clients.index"))
    nom = client.nom
    db.session.delete(client)
    db.session.commit()
    flash(f"« {nom} » supprimé définitivement.", "info")
    return redirect(url_for("clients.index"))


@bp.route("/<int:client_id>")
@permission_required("clients")
def fiche(client_id):
    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)

    form = ClientPaiementForm()
    form.moyen_paiement_id.choices = [
        (m.id, m.name) for m in MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name)
    ]
    defaut = moyen_paiement_par_defaut()
    if defaut:
        form.moyen_paiement_id.data = defaut.id

    ventes = sorted(client.ventes, key=lambda v: v.created_at, reverse=True)
    return render_template("clients/fiche.html", client=client, form=form, ventes=ventes)


@bp.route("/<int:client_id>/paiement", methods=["POST"])
@permission_required("clients")
def ajouter_paiement(client_id):
    client = db.session.get(Client, client_id)
    if client is None:
        abort(404)

    form = ClientPaiementForm()
    form.moyen_paiement_id.choices = [
        (m.id, m.name) for m in MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name)
    ]

    if form.validate_on_submit():
        montant = form.montant.data
        moyen = db.session.get(MoyenPaiement, form.moyen_paiement_id.data)
        # `montant` est saisi dans la devise du moyen choisi (ex. des euros
        # pour "Espèces Euro") — le solde dû du client reste lui toujours en
        # ariary, donc on compare/déduit son équivalent, jamais le nombre
        # brut saisi (même bug que corrigé au PDV : un remboursement en
        # euros ne doit pas être traité comme s'il était déjà en ariary).
        montant_ariary = montant_en_ariary(moyen, montant)

        if montant <= 0 or montant_ariary > client.solde_credit:
            flash(
                f"Le montant doit correspondre à un équivalent compris entre 1 et "
                f"{client.solde_credit} Ar (solde dû).",
                "error",
            )
            return redirect(url_for("clients.fiche", client_id=client.id))

        paiement = ClientPaiement(
            client_id=client.id,
            montant=montant,
            moyen_paiement_id=moyen.id,
            date_paiement=form.date_paiement.data,
            observations=form.observations.data or None,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(paiement)
        client.solde_credit -= montant_ariary
        crediter_compte(moyen.compte_financier, montant)
        _allouer_paiement_aux_ventes(client, montant_ariary)
        db.session.commit()
        flash("Paiement enregistré.", "info")
    else:
        flash("Formulaire invalide.", "error")

    return redirect(url_for("clients.fiche", client_id=client.id))


def _allouer_paiement_aux_ventes(client, montant):
    """Répartit un paiement de crédit sur les ventes à crédit non soldées de
    ce client, la plus ancienne d'abord (FIFO) — sert uniquement à savoir
    quand un ticket précis n'est plus "à crédit" sur son reçu ; le solde
    global du client (montant réellement dû) reste `client.solde_credit`."""
    restant = montant
    ventes_dues = (
        Vente.query.filter(Vente.client_id == client.id, Vente.credit_solde_restant > 0)
        .order_by(Vente.created_at)
        .all()
    )
    for vente in ventes_dues:
        if restant <= 0:
            break
        applique = min(restant, vente.credit_solde_restant)
        vente.credit_solde_restant -= applique
        restant -= applique