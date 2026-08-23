from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth.decorators import permission_required
from ..caisse.services import crediter_compte, montant_depuis_ariary
from ..extensions import db
from ..models import (
    Categorie,
    Client,
    MoyenPaiement,
    Poste,
    Produit,
    Projet,
    SousCategorie,
    VenteExterne,
    categories_par_poste,
    enregistrer_mouvement,
    moyen_paiement_par_defaut,
    sous_categories_par_categorie,
)
from . import bp
from .forms import VenteExterneForm


def _populate_choices(form):
    form.client_id.choices = [(0, "—")] + [
        (c.id, c.nom) for c in Client.query.filter_by(is_archived=False).order_by(Client.nom)
    ]
    form.poste_id.choices = [(p.id, p.name) for p in Poste.query.filter_by(is_archived=False).order_by(Poste.name)]
    form.projet_id.choices = [(0, "—")] + [
        (p.id, p.name) for p in Projet.query.filter_by(is_archived=False).order_by(Projet.name)
    ]
    form.categorie_id.choices = [
        (c.id, f"{c.poste.name} / {c.name}")
        for c in Categorie.query.filter_by(is_archived=False).order_by(Categorie.name)
    ]
    form.sous_categorie_id.choices = [(0, "—")] + [
        (sc.id, f"{sc.categorie.name} / {sc.name}")
        for sc in SousCategorie.query.filter_by(is_archived=False).order_by(SousCategorie.name)
    ]
    form.produit_id.choices = [(0, "—")] + [
        (p.id, p.name) for p in Produit.query.filter_by(is_archived=False).order_by(Produit.name)
    ]
    # Comme pour un achat payé "Compte Akiba (coffre-fort)" : seuls les moyens
    # NON rattachés au tiroir-caisse physique du PDV sont proposés — une vente
    # externe ne doit jamais créditer le PDV (retour utilisateur). L'argent va
    # réellement vers le compte auquel le moyen choisi est rattaché (Compte
    # Akiba, BMOI, Orange Money...), exactement comme pour achats/routes.py.
    form.moyen_paiement_id.choices = [
        (m.id, f"{m.name} — {m.compte_financier.name}")
        for m in MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name)
        if not m.compte_financier.is_caisse_physique
    ]


@bp.route("/")
@permission_required("ventes_externes")
def index():
    items = (
        VenteExterne.query.order_by(VenteExterne.date_vente.desc(), VenteExterne.id.desc()).limit(100).all()
    )
    return render_template("ventes_externes/index.html", items=items)


def _render_form(form):
    return render_template(
        "ventes_externes/form.html",
        form=form,
        sous_categories_json=sous_categories_par_categorie(),
        categories_json=categories_par_poste(),
    )


@bp.route("/nouveau", methods=["GET", "POST"])
@permission_required("ventes_externes")
def nouveau():
    form = VenteExterneForm()
    _populate_choices(form)
    if request.method == "GET":
        defaut = moyen_paiement_par_defaut()
        if defaut:
            form.moyen_paiement_id.data = defaut.id

    if form.validate_on_submit():
        produit = db.session.get(Produit, form.produit_id.data) if form.produit_id.data else None
        client_id = form.client_id.data or None
        client_nom = (form.client_nom.data or "").strip() or None

        if not client_id and not client_nom:
            flash("Choisissez un client enregistré ou indiquez un client de passage.", "error")
            return _render_form(form)

        if produit is not None:
            if not form.quantite.data or not form.prix_unitaire.data:
                flash("Une vente d'un produit catalogué nécessite une quantité et un prix unitaire.", "error")
                return _render_form(form)
            montant_total = form.quantite.data * form.prix_unitaire.data
        else:
            if not form.montant_total.data:
                flash("Le montant est obligatoire.", "error")
                return _render_form(form)
            montant_total = form.montant_total.data

        moyen = db.session.get(MoyenPaiement, form.moyen_paiement_id.data)

        # Garde-fou serveur, pas seulement visuel côté formulaire : une vente
        # externe ne doit jamais créditer le tiroir-caisse du PDV, quel que
        # soit le moyen soumis — même principe que achats/routes.py::nouveau.
        if moyen.compte_financier.is_caisse_physique:
            flash(
                f"« {moyen.name} » est rattaché au tiroir-caisse du PDV — une vente externe ne peut pas "
                "créditer ce compte. Choisissez un autre moyen de paiement.",
                "error",
            )
            return _render_form(form)

        vente_externe = VenteExterne(
            client_id=client_id,
            client_nom=client_nom if not client_id else None,
            date_vente=form.date_vente.data,
            poste_id=form.poste_id.data,
            projet_id=form.projet_id.data or None,
            categorie_id=form.categorie_id.data,
            sous_categorie_id=form.sous_categorie_id.data or None,
            produit_id=produit.id if produit else None,
            quantite=form.quantite.data if produit else None,
            prix_unitaire=form.prix_unitaire.data if produit else None,
            montant_total=montant_total,
            moyen_paiement_id=moyen.id,
            observations=form.observations.data or None,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(vente_externe)
        db.session.flush()

        if produit is not None:
            enregistrer_mouvement(
                produit,
                "sortie",
                "vente",
                form.quantite.data,
                current_user,
                commentaire=f"Vente externe #{vente_externe.id}",
                reference_type="vente_externe",
                reference_id=vente_externe.id,
            )

        crediter_compte(moyen.compte_financier, montant_depuis_ariary(moyen, montant_total))

        db.session.commit()
        flash("Vente externe enregistrée.", "info")
        return redirect(url_for("ventes_externes.index"))

    return _render_form(form)
