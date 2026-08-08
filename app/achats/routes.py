from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from ..auth.decorators import permission_required
from ..caisse.services import (
    debiter_compte,
    get_caisse_compte,
    get_open_session,
    montant_depuis_ariary,
    tenter_ouverture_tiroir,
)
from ..extensions import db
from ..models import (
    Achat,
    AchatDocument,
    AchatRecurrent,
    Categorie,
    Fournisseur,
    MoyenPaiement,
    Poste,
    Produit,
    Projet,
    SousCategorie,
    categories_par_poste,
    enregistrer_mouvement,
    moyen_paiement_par_defaut,
    sous_categories_par_categorie,
)
from . import bp
from .forms import AchatForm, AchatModifierForm, AchatRecurrentForm


def _populate_choices(form, moyen_paiement_optionnel=False):
    form.fournisseur_id.choices = [(0, "—")] + [
        (f.id, f.name) for f in Fournisseur.query.filter_by(is_archived=False).order_by(Fournisseur.name)
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
    # Compte en suffixe : deux moyens peuvent porter le même nom mais
    # pointer vers des comptes différents (ex. "Espèces Ariary" pour le
    # tiroir PDV ET pour le Compte Akiba) — jamais les confondre dans la
    # liste (retour utilisateur du 08/08/2026).
    moyens = [
        (m.id, f"{m.name} — {m.compte_financier.name}")
        for m in MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name)
    ]
    form.moyen_paiement_id.choices = ([(0, "—")] + moyens) if moyen_paiement_optionnel else moyens


@bp.route("/")
@permission_required("achats")
def index():
    items = Achat.query.order_by(Achat.date_achat.desc(), Achat.id.desc()).limit(100).all()
    modeles = AchatRecurrent.query.filter_by(is_archived=False).order_by(AchatRecurrent.nom).all()
    return render_template("achats/index.html", items=items, modeles=modeles)


@bp.route("/nouveau", methods=["GET", "POST"])
@permission_required("achats")
def nouveau():
    form = AchatForm()
    _populate_choices(form)
    moyens = MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name).all()
    if request.method == "GET":
        defaut = moyen_paiement_par_defaut()
        if defaut:
            form.moyen_paiement_id.data = defaut.id
            form.origine.data = "pdv" if defaut.compte_financier.is_caisse_physique else "coffre_fort"

    modele = None
    modele_id = request.args.get("modele", type=int)
    if request.method == "GET" and modele_id:
        modele = db.session.get(AchatRecurrent, modele_id)
        if modele is not None:
            form.type_achat.data = modele.type_achat
            form.fournisseur_id.data = modele.fournisseur_id or 0
            form.poste_id.data = modele.poste_id
            form.projet_id.data = modele.projet_id or 0
            form.categorie_id.data = modele.categorie_id
            form.sous_categorie_id.data = modele.sous_categorie_id or 0
            form.produit_id.data = modele.produit_id or 0
            form.quantite.data = modele.quantite_habituelle
            form.prix_unitaire.data = modele.prix_unitaire_habituel
            form.montant_total.data = modele.montant_habituel
            if modele.moyen_paiement_id:
                form.moyen_paiement_id.data = modele.moyen_paiement_id

    if form.validate_on_submit():
        type_achat = form.type_achat.data
        produit = db.session.get(Produit, form.produit_id.data) if form.produit_id.data else None

        if type_achat == "stock":
            if produit is None or not form.quantite.data or not form.prix_unitaire.data:
                flash("Un achat de stock nécessite un produit, une quantité et un prix unitaire.", "error")
                return render_template(
                    "achats/form.html", form=form, modele=modele, moyens=moyens, sous_categories_json=sous_categories_par_categorie(), categories_json=categories_par_poste()
                )
            montant_total = form.quantite.data * form.prix_unitaire.data
        else:
            if not form.montant_total.data:
                flash("Le montant de la dépense est obligatoire.", "error")
                return render_template(
                    "achats/form.html", form=form, modele=modele, moyens=moyens, sous_categories_json=sous_categories_par_categorie(), categories_json=categories_par_poste()
                )
            montant_total = form.montant_total.data

        moyen = db.session.get(MoyenPaiement, form.moyen_paiement_id.data)

        # Garde-fou serveur, pas seulement visuel côté formulaire : le moyen
        # choisi doit correspondre au compte déclaré — même contrôle que
        # caisse/routes.py::mouvement (retour utilisateur du 08/08/2026).
        origine_attendue = "pdv" if moyen.compte_financier.is_caisse_physique else "coffre_fort"
        if form.origine.data != origine_attendue:
            flash(
                f"« {moyen.name} » ne correspond pas au compte choisi "
                f"({'Caisse PDV' if form.origine.data == 'pdv' else 'Compte Akiba (coffre-fort)'}).",
                "error",
            )
            return render_template(
                "achats/form.html", form=form, modele=modele, moyens=moyens, sous_categories_json=sous_categories_par_categorie(), categories_json=categories_par_poste()
            )

        # Rattache l'achat à la session de caisse en cours seulement s'il est
        # payé en espèces depuis la caisse physique — sert à le faire
        # apparaître dans l'historique de la session et à le déduire du
        # contenu théorique du tiroir à la clôture.
        session_caisse = get_open_session()
        caisse_compte = get_caisse_compte()
        caisse_session_id = (
            session_caisse.id
            if session_caisse and caisse_compte and moyen.compte_financier_id == caisse_compte.id
            else None
        )

        achat = Achat(
            nom=form.nom.data or None,
            caisse_session_id=caisse_session_id,
            type_achat=type_achat,
            fournisseur_id=form.fournisseur_id.data or None,
            date_achat=form.date_achat.data,
            poste_id=form.poste_id.data,
            projet_id=form.projet_id.data or None,
            categorie_id=form.categorie_id.data,
            sous_categorie_id=form.sous_categorie_id.data or None,
            produit_id=produit.id if produit else None,
            quantite=form.quantite.data if type_achat == "stock" else None,
            prix_unitaire=form.prix_unitaire.data if type_achat == "stock" else None,
            montant_total=montant_total,
            moyen_paiement_id=moyen.id,
            observations=form.observations.data or None,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(achat)
        db.session.flush()

        if type_achat == "stock":
            enregistrer_mouvement(
                produit,
                "entree",
                "achat",
                form.quantite.data,
                current_user,
                commentaire=f"Achat #{achat.id}",
                reference_type="achat",
                reference_id=achat.id,
            )

        # montant_total est toujours la dépense réelle en ariary (achats et
        # rapports raisonnent tous en ariary) ; le compte débité doit lui
        # refléter ce qui en est réellement sorti dans sa propre devise
        # (ex. payé en espèces euros) — même correction que pour les
        # paiements PDV et les remboursements de crédit client.
        debiter_compte(moyen.compte_financier, montant_depuis_ariary(moyen, montant_total))

        _enregistrer_documents(achat, form.documents.data)

        db.session.commit()

        # Achat payé en espèces depuis le tiroir PDV : l'argent en sort
        # physiquement à l'instant, le tiroir doit s'ouvrir (retour
        # utilisateur du 08/08/2026 — même logique que les sorties de caisse
        # manuelles, voir caisse/routes.py::mouvement).
        if form.origine.data == "pdv" and moyen.ouvre_tiroir:
            tenter_ouverture_tiroir()

        flash("Achat enregistré.", "info")
        return redirect(url_for("achats.index"))

    return render_template(
        "achats/form.html", form=form, modele=modele, moyens=moyens, sous_categories_json=sous_categories_par_categorie(), categories_json=categories_par_poste()
    )


@bp.route("/<int:achat_id>/modifier", methods=["GET", "POST"])
@permission_required("achats")
def modifier(achat_id):
    achat = db.session.get(Achat, achat_id)
    if achat is None:
        abort(404)

    form = AchatModifierForm(obj=achat)
    _populate_choices_classement(form)
    if request.method == "GET":
        form.projet_id.data = achat.projet_id or 0
        form.sous_categorie_id.data = achat.sous_categorie_id or 0
        form.fournisseur_id.data = achat.fournisseur_id or 0

    if form.validate_on_submit():
        achat.nom = form.nom.data or None
        achat.fournisseur_id = form.fournisseur_id.data or None
        achat.date_achat = form.date_achat.data
        achat.poste_id = form.poste_id.data
        achat.projet_id = form.projet_id.data or None
        achat.categorie_id = form.categorie_id.data
        achat.sous_categorie_id = form.sous_categorie_id.data or None
        achat.observations = form.observations.data or None
        _enregistrer_documents(achat, form.documents.data)
        db.session.commit()
        flash("Achat mis à jour.", "info")
        return redirect(url_for("achats.index"))

    return render_template(
        "achats/modifier.html", form=form, achat=achat, sous_categories_json=sous_categories_par_categorie(), categories_json=categories_par_poste()
    )


def _populate_choices_classement(form):
    """Comme _populate_choices, mais sans produit/moyen de paiement — pas
    éditables sur un achat déjà enregistré."""
    form.fournisseur_id.choices = [(0, "—")] + [
        (f.id, f.name) for f in Fournisseur.query.filter_by(is_archived=False).order_by(Fournisseur.name)
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


def _enregistrer_documents(achat, fichiers):
    if not fichiers:
        return
    dossier = Path(current_app.config["UPLOAD_DIR"]) / str(achat.id)
    for fichier in fichiers:
        if not fichier or not fichier.filename:
            continue
        dossier.mkdir(parents=True, exist_ok=True)
        nom_sécurisé = secure_filename(fichier.filename)
        fichier.save(dossier / nom_sécurisé)
        db.session.add(
            AchatDocument(achat_id=achat.id, nom_original=fichier.filename, nom_fichier=nom_sécurisé)
        )


# --- Modèles d'achats récurrents -------------------------------------------


@bp.route("/recurrents", methods=["GET", "POST"])
@permission_required("achats")
def recurrents():
    form = AchatRecurrentForm()
    _populate_choices(form, moyen_paiement_optionnel=True)

    if form.validate_on_submit():
        modele = AchatRecurrent(
            nom=form.nom.data,
            type_achat=form.type_achat.data,
            fournisseur_id=form.fournisseur_id.data or None,
            poste_id=form.poste_id.data,
            projet_id=form.projet_id.data or None,
            categorie_id=form.categorie_id.data,
            sous_categorie_id=form.sous_categorie_id.data or None,
            produit_id=form.produit_id.data or None,
            quantite_habituelle=form.quantite_habituelle.data,
            prix_unitaire_habituel=form.prix_unitaire_habituel.data,
            montant_habituel=form.montant_habituel.data,
            moyen_paiement_id=form.moyen_paiement_id.data or None,
        )
        db.session.add(modele)
        db.session.commit()
        flash(f"Modèle « {modele.nom} » créé.", "info")
        return redirect(url_for("achats.recurrents"))

    items = AchatRecurrent.query.order_by(AchatRecurrent.is_archived, AchatRecurrent.nom).all()
    return render_template(
        "achats/recurrents.html", form=form, items=items, sous_categories_json=sous_categories_par_categorie(), categories_json=categories_par_poste()
    )


@bp.route("/recurrents/<int:modele_id>/archiver", methods=["POST"])
@permission_required("achats")
def recurrent_toggle_archive(modele_id):
    modele = db.session.get(AchatRecurrent, modele_id)
    if modele is None:
        flash("Modèle introuvable.", "error")
        return redirect(url_for("achats.recurrents"))
    modele.is_archived = not modele.is_archived
    db.session.commit()
    return redirect(url_for("achats.recurrents"))
