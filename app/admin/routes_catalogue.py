import re
import unicodedata
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..auth.decorators import permission_required
from ..extensions import db
from .import_excel import generer_modele_xlsx, importer_produits_excel
from ..models import (
    AjustementCompte,
    Categorie,
    CompteFinancier,
    Fournisseur,
    MoyenPaiement,
    WIDGETS_TABLEAU_BORD,
    WidgetTableauBord,
    Poste,
    PrixProduit,
    Produit,
    Projet,
    ParametresImprimante,
    ParametresLegaux,
    ParametresRH,
    SousCategorie,
    TauxChange,
    TypeTarif,
    arrondir_centaine_superieure,
    categories_par_poste,
    sous_categories_par_categorie,
    verifier_suppression_categorie,
    verifier_suppression_compte_financier,
    verifier_suppression_fournisseur,
    verifier_suppression_poste,
    verifier_suppression_produit,
    verifier_suppression_projet,
    verifier_suppression_sous_categorie,
    verifier_suppression_tarif,
)
from . import bp
from .forms import (
    AjustementCompteForm,
    CategorieForm,
    CompteFinancierForm,
    FournisseurForm,
    ImportProduitsForm,
    MoyenPaiementForm,
    ParametresImprimanteForm,
    ParametresLegauxForm,
    ParametresRHForm,
    PosteForm,
    ProduitForm,
    ProjetForm,
    RabaisTarifForm,
    SousCategorieForm,
    TauxChangeForm,
    TypeTarifForm,
)


def _slugifier(texte):
    """Convertit un libellé en code technique unique (ex. "Prix Adhérent" ->
    "prix_adherent"), sans dépendance externe."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    code = re.sub(r"[^a-z0-9]+", "_", sans_accents.lower()).strip("_") or "tarif"
    base = code
    suffixe = 2
    while TypeTarif.query.filter_by(code=code).first() is not None:
        code = f"{base}_{suffixe}"
        suffixe += 1
    return code


@bp.route("/")
@permission_required("admin")
def index():
    return render_template("admin/index.html")


# --- Postes -----------------------------------------------------------------


@bp.route("/postes", methods=["GET", "POST"])
@permission_required("admin")
def postes():
    form = PosteForm()
    if form.validate_on_submit():
        db.session.add(Poste(name=form.name.data, icon=form.icon.data or "storefront"))
        db.session.commit()
        flash("Poste créé.", "info")
        return redirect(url_for("admin.postes"))

    items = Poste.query.order_by(Poste.is_archived, Poste.name).all()
    return render_template("admin/postes.html", form=form, items=items)


@bp.route("/postes/<int:poste_id>/archiver", methods=["POST"])
@permission_required("admin")
def poste_toggle_archive(poste_id):
    poste = db.session.get(Poste, poste_id)
    if poste is None:
        abort(404)
    poste.is_archived = not poste.is_archived
    db.session.commit()
    return redirect(url_for("admin.postes"))


@bp.route("/postes/<int:poste_id>/supprimer", methods=["POST"])
@permission_required("admin")
def poste_supprimer(poste_id):
    poste = db.session.get(Poste, poste_id)
    if poste is None:
        abort(404)
    raison = verifier_suppression_poste(poste)
    if raison:
        flash(f"Impossible de supprimer « {poste.name} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.postes"))
    nom = poste.name
    db.session.delete(poste)
    db.session.commit()
    flash(f"« {nom} » supprimé définitivement.", "info")
    return redirect(url_for("admin.postes"))


# --- Projets ------------------------------------------------------------------


@bp.route("/projets", methods=["GET", "POST"])
@permission_required("admin")
def projets():
    form = ProjetForm()
    if form.validate_on_submit():
        db.session.add(Projet(name=form.name.data))
        db.session.commit()
        flash("Projet créé.", "info")
        return redirect(url_for("admin.projets"))

    items = Projet.query.order_by(Projet.is_archived, Projet.name).all()
    return render_template("admin/projets.html", form=form, items=items)


@bp.route("/projets/<int:projet_id>/archiver", methods=["POST"])
@permission_required("admin")
def projet_toggle_archive(projet_id):
    projet = db.session.get(Projet, projet_id)
    if projet is None:
        abort(404)
    projet.is_archived = not projet.is_archived
    db.session.commit()
    return redirect(url_for("admin.projets"))


@bp.route("/projets/<int:projet_id>/supprimer", methods=["POST"])
@permission_required("admin")
def projet_supprimer(projet_id):
    projet = db.session.get(Projet, projet_id)
    if projet is None:
        abort(404)
    raison = verifier_suppression_projet(projet)
    if raison:
        flash(f"Impossible de supprimer « {projet.name} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.projets"))
    nom = projet.name
    db.session.delete(projet)
    db.session.commit()
    flash(f"« {nom} » supprimé définitivement.", "info")
    return redirect(url_for("admin.projets"))


# --- Fournisseurs --------------------------------------------------------------


@bp.route("/fournisseurs", methods=["GET", "POST"])
@permission_required("admin")
def fournisseurs():
    form = FournisseurForm()
    if form.validate_on_submit():
        db.session.add(
            Fournisseur(
                name=form.name.data,
                telephone=form.telephone.data or None,
                email=form.email.data or None,
                adresse=form.adresse.data or None,
                observations=form.observations.data or None,
            )
        )
        db.session.commit()
        flash("Fournisseur créé.", "info")
        return redirect(url_for("admin.fournisseurs"))

    items = Fournisseur.query.order_by(Fournisseur.is_archived, Fournisseur.name).all()
    return render_template("admin/fournisseurs.html", form=form, items=items)


@bp.route("/fournisseurs/<int:fournisseur_id>/archiver", methods=["POST"])
@permission_required("admin")
def fournisseur_toggle_archive(fournisseur_id):
    fournisseur = db.session.get(Fournisseur, fournisseur_id)
    if fournisseur is None:
        abort(404)
    fournisseur.is_archived = not fournisseur.is_archived
    db.session.commit()
    return redirect(url_for("admin.fournisseurs"))


@bp.route("/fournisseurs/<int:fournisseur_id>/supprimer", methods=["POST"])
@permission_required("admin")
def fournisseur_supprimer(fournisseur_id):
    fournisseur = db.session.get(Fournisseur, fournisseur_id)
    if fournisseur is None:
        abort(404)
    raison = verifier_suppression_fournisseur(fournisseur)
    if raison:
        flash(f"Impossible de supprimer « {fournisseur.name} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.fournisseurs"))
    nom = fournisseur.name
    db.session.delete(fournisseur)
    db.session.commit()
    flash(f"« {nom} » supprimé définitivement.", "info")
    return redirect(url_for("admin.fournisseurs"))


# --- Moyens de paiement --------------------------------------------------------


@bp.route("/moyens-paiement", methods=["GET", "POST"])
@permission_required("admin")
def moyens_paiement():
    form = MoyenPaiementForm()
    form.compte_financier_id.choices = [
        (c.id, f"{c.name} ({c.devise})")
        for c in CompteFinancier.query.filter_by(is_archived=False).order_by(CompteFinancier.name)
    ]
    if form.validate_on_submit():
        if form.is_default.data:
            # Un seul moyen "par défaut" à la fois — désélectionner les autres,
            # sinon les formulaires qui présélectionnent le moyen par défaut
            # (moyen_paiement_par_defaut()) deviendraient ambigus.
            MoyenPaiement.query.filter_by(is_default=True).update({"is_default": False})
        db.session.add(
            MoyenPaiement(
                name=form.name.data,
                compte_financier_id=form.compte_financier_id.data,
                ouvre_tiroir=form.ouvre_tiroir.data,
                is_default=form.is_default.data,
                visible_pdv=form.visible_pdv.data,
            )
        )
        db.session.commit()
        flash("Moyen de paiement créé.", "info")
        return redirect(url_for("admin.moyens_paiement"))

    items = MoyenPaiement.query.order_by(MoyenPaiement.is_archived, MoyenPaiement.name).all()
    return render_template("admin/moyens_paiement.html", form=form, items=items, moyen=None)


@bp.route("/moyens-paiement/<int:moyen_id>/modifier", methods=["GET", "POST"])
@permission_required("admin")
def moyen_paiement_modifier(moyen_id):
    moyen = db.session.get(MoyenPaiement, moyen_id)
    if moyen is None:
        abort(404)

    form = MoyenPaiementForm(obj=moyen)
    form.compte_financier_id.choices = [
        (c.id, f"{c.name} ({c.devise})")
        for c in CompteFinancier.query.filter_by(is_archived=False).order_by(CompteFinancier.name)
    ]

    if form.validate_on_submit():
        if form.is_default.data and not moyen.is_default:
            # Même règle qu'à la création : un seul moyen "par défaut" à la fois.
            MoyenPaiement.query.filter_by(is_default=True).update({"is_default": False})
        moyen.name = form.name.data
        moyen.compte_financier_id = form.compte_financier_id.data
        moyen.ouvre_tiroir = form.ouvre_tiroir.data
        moyen.is_default = form.is_default.data
        moyen.visible_pdv = form.visible_pdv.data
        db.session.commit()
        flash(f"« {moyen.name} » mis à jour.", "info")
        return redirect(url_for("admin.moyens_paiement"))

    items = MoyenPaiement.query.order_by(MoyenPaiement.is_archived, MoyenPaiement.name).all()
    return render_template("admin/moyens_paiement.html", form=form, items=items, moyen=moyen)


@bp.route("/moyens-paiement/<int:moyen_id>/archiver", methods=["POST"])
@permission_required("admin")
def moyen_paiement_toggle_archive(moyen_id):
    moyen = db.session.get(MoyenPaiement, moyen_id)
    if moyen is None:
        abort(404)
    moyen.is_archived = not moyen.is_archived
    if moyen.is_archived:
        # Un moyen archivé ne doit plus jamais être présélectionné par
        # défaut (il a déjà disparu de tous les menus déroulants).
        moyen.is_default = False
    db.session.commit()
    flash(f"« {moyen.name} » {'archivé' if moyen.is_archived else 'réactivé'}.", "info")
    return redirect(url_for("admin.moyens_paiement"))


# --- Comptes financiers ---------------------------------------------------------


@bp.route("/comptes-financiers", methods=["GET", "POST"])
@permission_required("admin")
def comptes_financiers():
    form = CompteFinancierForm()
    if form.validate_on_submit():
        if form.is_caisse_physique.data:
            # Une seule caisse physique à la fois (§2 spec, mono-poste) —
            # même garde-fou que pour is_default sur MoyenPaiement/TypeTarif.
            CompteFinancier.query.filter_by(is_caisse_physique=True).update({"is_caisse_physique": False})
        if form.is_compte_akiba.data:
            CompteFinancier.query.filter_by(is_compte_akiba=True).update({"is_compte_akiba": False})
        db.session.add(
            CompteFinancier(
                name=form.name.data,
                devise=form.devise.data,
                is_caisse_physique=form.is_caisse_physique.data,
                is_compte_akiba=form.is_compte_akiba.data,
                visible_tableau_bord=form.visible_tableau_bord.data,
            )
        )
        db.session.commit()
        flash(f"Compte « {form.name.data} » créé.", "info")
        return redirect(url_for("admin.comptes_financiers"))

    comptes = CompteFinancier.query.order_by(CompteFinancier.is_archived, CompteFinancier.name).all()
    return render_template("admin/comptes_financiers.html", comptes=comptes, form=form, compte=None)


@bp.route("/comptes-financiers/<int:compte_id>/modifier", methods=["GET", "POST"])
@permission_required("admin")
def compte_financier_modifier(compte_id):
    compte = db.session.get(CompteFinancier, compte_id)
    if compte is None:
        abort(404)

    form = CompteFinancierForm(obj=compte)
    if form.validate_on_submit():
        if form.is_caisse_physique.data and not compte.is_caisse_physique:
            CompteFinancier.query.filter_by(is_caisse_physique=True).update({"is_caisse_physique": False})
        if form.is_compte_akiba.data and not compte.is_compte_akiba:
            CompteFinancier.query.filter_by(is_compte_akiba=True).update({"is_compte_akiba": False})
        compte.name = form.name.data
        compte.devise = form.devise.data
        compte.is_caisse_physique = form.is_caisse_physique.data
        compte.is_compte_akiba = form.is_compte_akiba.data
        compte.visible_tableau_bord = form.visible_tableau_bord.data
        db.session.commit()
        flash(f"« {compte.name} » mis à jour.", "info")
        return redirect(url_for("admin.comptes_financiers"))

    comptes = CompteFinancier.query.order_by(CompteFinancier.is_archived, CompteFinancier.name).all()
    return render_template("admin/comptes_financiers.html", comptes=comptes, form=form, compte=compte)


@bp.route("/comptes-financiers/<int:compte_id>/archiver", methods=["POST"])
@permission_required("admin")
def compte_financier_toggle_archive(compte_id):
    compte = db.session.get(CompteFinancier, compte_id)
    if compte is None:
        abort(404)
    compte.is_archived = not compte.is_archived
    db.session.commit()
    flash(f"« {compte.name} » {'archivé' if compte.is_archived else 'réactivé'}.", "info")
    return redirect(url_for("admin.comptes_financiers"))


@bp.route("/comptes-financiers/<int:compte_id>/supprimer", methods=["POST"])
@permission_required("admin")
def compte_financier_supprimer(compte_id):
    compte = db.session.get(CompteFinancier, compte_id)
    if compte is None:
        abort(404)
    raison = verifier_suppression_compte_financier(compte)
    if raison:
        flash(f"Impossible de supprimer « {compte.name} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.comptes_financiers"))
    nom = compte.name
    db.session.delete(compte)
    db.session.commit()
    flash(f"« {nom} » supprimé définitivement.", "info")
    return redirect(url_for("admin.comptes_financiers"))


@bp.route("/comptes-financiers/<int:compte_id>/ajuster", methods=["GET", "POST"])
@permission_required("admin")
def compte_financier_ajuster(compte_id):
    compte = db.session.get(CompteFinancier, compte_id)
    if compte is None:
        abort(404)

    form = AjustementCompteForm()
    if form.validate_on_submit():
        ancien_solde = compte.solde
        ajustement = AjustementCompte(
            compte_financier_id=compte.id,
            ancien_solde=ancien_solde,
            nouveau_solde=form.nouveau_solde.data,
            motif=form.motif.data,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        compte.solde = form.nouveau_solde.data
        db.session.add(ajustement)
        db.session.commit()
        flash(f"Solde de « {compte.name} » corrigé : {ancien_solde} → {compte.solde}.", "info")
        return redirect(url_for("admin.comptes_financiers"))

    form.nouveau_solde.data = compte.solde
    historique = (
        AjustementCompte.query.filter_by(compte_financier_id=compte.id)
        .order_by(AjustementCompte.created_at.desc())
        .all()
    )
    return render_template(
        "admin/compte_financier_ajuster.html", form=form, compte=compte, historique=historique
    )


# --- Tableau de bord (widgets) --------------------------------------------------


@bp.route("/tableau-bord", methods=["GET", "POST"])
@permission_required("admin")
def tableau_bord_widgets():
    widgets = WidgetTableauBord.liste_ordonnee()

    if request.method == "POST":
        ordre = [code for code in request.form.get("ordre", "").split(",") if code]
        actifs = set(request.form.getlist("actifs"))
        par_code = {w.code: w for w in widgets}
        for index, code in enumerate(ordre):
            widget = par_code.get(code)
            if widget is not None:
                widget.ordre = index
                widget.actif = code in actifs
        db.session.commit()
        flash("Tableau de bord mis à jour.", "info")
        return redirect(url_for("admin.tableau_bord_widgets"))

    labels = dict(WIDGETS_TABLEAU_BORD)
    return render_template("admin/tableau_bord_widgets.html", widgets=widgets, labels=labels)


# --- Catégories / Sous-catégories ---------------------------------------------


@bp.route("/categories", methods=["GET", "POST"])
@permission_required("admin")
def categories():
    form = CategorieForm()
    form.poste_id.choices = [(p.id, p.name) for p in Poste.query.filter_by(is_archived=False).order_by(Poste.name)]
    sous_form = SousCategorieForm()
    sous_form.categorie_id.choices = [
        (c.id, f"{c.poste.name} / {c.name}")
        for c in Categorie.query.filter_by(is_archived=False).order_by(Categorie.name)
    ]

    if form.validate_on_submit():
        db.session.add(
            Categorie(
                poste_id=form.poste_id.data,
                name=form.name.data,
                icon=form.icon.data or "category",
                ordre=form.ordre.data or 0,
            )
        )
        db.session.commit()
        flash("Catégorie créée.", "info")
        return redirect(url_for("admin.categories"))

    items = Categorie.query.order_by(Categorie.poste_id, Categorie.is_archived, Categorie.ordre, Categorie.name).all()
    return render_template("admin/categories.html", form=form, sous_form=sous_form, items=items)


@bp.route("/categories/<int:categorie_id>/archiver", methods=["POST"])
@permission_required("admin")
def categorie_toggle_archive(categorie_id):
    categorie = db.session.get(Categorie, categorie_id)
    if categorie is None:
        abort(404)
    categorie.is_archived = not categorie.is_archived
    db.session.commit()
    return redirect(url_for("admin.categories"))


@bp.route("/categories/<int:categorie_id>/supprimer", methods=["POST"])
@permission_required("admin")
def categorie_supprimer(categorie_id):
    categorie = db.session.get(Categorie, categorie_id)
    if categorie is None:
        abort(404)
    raison = verifier_suppression_categorie(categorie)
    if raison:
        flash(f"Impossible de supprimer « {categorie.name} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.categories"))
    nom = categorie.name
    db.session.delete(categorie)
    db.session.commit()
    flash(f"« {nom} » supprimée définitivement.", "info")
    return redirect(url_for("admin.categories"))


@bp.route("/sous-categories", methods=["POST"])
@permission_required("admin")
def sous_categories_create():
    form = SousCategorieForm()
    form.categorie_id.choices = [
        (c.id, c.name) for c in Categorie.query.filter_by(is_archived=False).order_by(Categorie.name)
    ]
    if form.validate_on_submit():
        db.session.add(SousCategorie(categorie_id=form.categorie_id.data, name=form.name.data))
        db.session.commit()
        flash("Sous-catégorie créée.", "info")
    else:
        flash("Formulaire invalide.", "error")
    return redirect(url_for("admin.categories"))


@bp.route("/sous-categories/<int:sous_categorie_id>/archiver", methods=["POST"])
@permission_required("admin")
def sous_categorie_toggle_archive(sous_categorie_id):
    sous_categorie = db.session.get(SousCategorie, sous_categorie_id)
    if sous_categorie is None:
        abort(404)
    sous_categorie.is_archived = not sous_categorie.is_archived
    db.session.commit()
    return redirect(url_for("admin.categories"))


@bp.route("/sous-categories/<int:sous_categorie_id>/supprimer", methods=["POST"])
@permission_required("admin")
def sous_categorie_supprimer(sous_categorie_id):
    sous_categorie = db.session.get(SousCategorie, sous_categorie_id)
    if sous_categorie is None:
        abort(404)
    raison = verifier_suppression_sous_categorie(sous_categorie)
    if raison:
        flash(f"Impossible de supprimer « {sous_categorie.name} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.categories"))
    nom = sous_categorie.name
    db.session.delete(sous_categorie)
    db.session.commit()
    flash(f"« {nom} » supprimée définitivement.", "info")
    return redirect(url_for("admin.categories"))


# --- Tarifs ---------------------------------------------------------------


@bp.route("/tarifs", methods=["GET", "POST"])
@permission_required("admin")
def tarifs():
    form = TypeTarifForm()
    if form.validate_on_submit():
        ordre_max = db.session.query(db.func.max(TypeTarif.ordre)).scalar() or 0
        premier_tarif = TypeTarif.query.count() == 0
        db.session.add(
            TypeTarif(
                code=_slugifier(form.label.data),
                label=form.label.data,
                ordre=ordre_max + 1,
                # Le tout premier tarif créé est automatiquement le tarif par
                # défaut du PDV, pour ne jamais laisser la caisse sans tarif actif.
                is_default=premier_tarif,
            )
        )
        db.session.commit()
        flash(f"Tarif « {form.label.data} » créé.", "info")
        return redirect(url_for("admin.tarifs"))

    items = TypeTarif.query.order_by(TypeTarif.is_archived, TypeTarif.ordre).all()
    return render_template("admin/tarifs.html", form=form, items=items)


@bp.route("/tarifs/<int:tarif_id>/definir-defaut", methods=["POST"])
@permission_required("admin")
def tarif_definir_defaut(tarif_id):
    tarif = db.session.get(TypeTarif, tarif_id)
    if tarif is None:
        abort(404)
    if tarif.is_archived:
        flash("Un tarif archivé ne peut pas être défini par défaut.", "error")
        return redirect(url_for("admin.tarifs"))

    TypeTarif.query.filter(TypeTarif.id != tarif.id).update({"is_default": False})
    tarif.is_default = True
    db.session.commit()
    flash(f"« {tarif.label} » est maintenant le tarif par défaut du PDV.", "info")
    return redirect(url_for("admin.tarifs"))


@bp.route("/tarifs/<int:tarif_id>/rabais", methods=["POST"])
@permission_required("admin")
def tarif_rabais(tarif_id):
    tarif = db.session.get(TypeTarif, tarif_id)
    if tarif is None:
        abort(404)

    form = RabaisTarifForm()
    if not form.validate_on_submit():
        flash("Pourcentage invalide (0 à 100).", "error")
        return redirect(url_for("admin.tarifs"))

    if form.rabais_actif.data and not form.pourcentage_rabais.data:
        flash("Indiquez un pourcentage avant d'activer le rabais.", "error")
        return redirect(url_for("admin.tarifs"))

    tarif.pourcentage_rabais = form.pourcentage_rabais.data
    tarif.rabais_actif = form.rabais_actif.data
    db.session.commit()
    if tarif.rabais_actif:
        flash(f"Rabais de {tarif.pourcentage_rabais}% activé pour « {tarif.label} ».", "info")
    else:
        flash(f"Rabais désactivé pour « {tarif.label} ».", "info")
    return redirect(url_for("admin.tarifs"))


@bp.route("/tarifs/<int:tarif_id>/archiver", methods=["POST"])
@permission_required("admin")
def tarif_toggle_archive(tarif_id):
    tarif = db.session.get(TypeTarif, tarif_id)
    if tarif is None:
        abort(404)

    if not tarif.is_archived:
        if tarif.is_default:
            flash("Définissez d'abord un autre tarif par défaut avant d'archiver celui-ci.", "error")
            return redirect(url_for("admin.tarifs"))
        autres_actifs = TypeTarif.query.filter(
            TypeTarif.id != tarif.id, TypeTarif.is_archived.is_(False)
        ).count()
        if autres_actifs == 0:
            flash("Impossible d'archiver le dernier tarif actif : le PDV a besoin d'au moins un tarif.", "error")
            return redirect(url_for("admin.tarifs"))

    tarif.is_archived = not tarif.is_archived
    db.session.commit()
    return redirect(url_for("admin.tarifs"))


@bp.route("/tarifs/<int:tarif_id>/supprimer", methods=["POST"])
@permission_required("admin")
def tarif_supprimer(tarif_id):
    tarif = db.session.get(TypeTarif, tarif_id)
    if tarif is None:
        abort(404)
    if tarif.is_default:
        flash("Définissez d'abord un autre tarif par défaut avant de supprimer celui-ci.", "error")
        return redirect(url_for("admin.tarifs"))
    raison = verifier_suppression_tarif(tarif)
    if raison:
        flash(f"Impossible de supprimer « {tarif.label} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.tarifs"))
    label = tarif.label
    db.session.delete(tarif)
    db.session.commit()
    flash(f"« {label} » supprimé définitivement.", "info")
    return redirect(url_for("admin.tarifs"))


# --- Produits -------------------------------------------------------------


def _populate_produit_choices(form):
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
    form.fournisseur_principal_id.choices = [(0, "—")] + [
        (f.id, f.name) for f in Fournisseur.query.filter_by(is_archived=False).order_by(Fournisseur.name)
    ]


def _tarifs_actifs():
    return TypeTarif.query.filter_by(is_archived=False).order_by(TypeTarif.ordre).all()


def _prix_suggeres(tarifs, prix_reference):
    """{ tarif.id: prix calculé si rabais actif et prix de référence connu }
    — juste un indice affiché dans le placeholder, jamais imposé : laisser le
    champ vide applique ce calcul, le remplir le remplace."""
    suggeres = {}
    for tarif in tarifs:
        if tarif.rabais_actif and tarif.pourcentage_rabais and prix_reference:
            suggeres[tarif.id] = arrondir_centaine_superieure(
                prix_reference * (100 - tarif.pourcentage_rabais) / 100
            )
    return suggeres


@bp.route("/produits")
@permission_required("admin")
def produits():
    items = Produit.query.order_by(Produit.is_archived, Produit.name).all()
    return render_template("admin/produits.html", items=items)


@bp.route("/produits/nouveau", methods=["GET", "POST"])
@permission_required("admin")
def produit_nouveau():
    form = ProduitForm()
    _populate_produit_choices(form)
    tarifs = _tarifs_actifs()

    if form.validate_on_submit():
        produit = Produit(
            name=form.name.data,
            poste_id=form.poste_id.data,
            projet_id=form.projet_id.data or None,
            categorie_id=form.categorie_id.data,
            sous_categorie_id=form.sous_categorie_id.data or None,
            fournisseur_principal_id=form.fournisseur_principal_id.data or None,
            unite=form.unite.data or "unité",
            prix_achat=form.prix_achat.data,
            prix_reference=form.prix_reference.data,
            stock_illimite=form.stock_illimite.data,
            prix_libre=form.prix_libre.data,
            seuil_alerte=form.seuil_alerte.data,
            stock_quantite=form.stock_quantite.data or 0,
            code_barres=form.code_barres.data or None,
        )
        db.session.add(produit)
        db.session.flush()
        _sauvegarder_tarifs(produit, tarifs)
        _enregistrer_photo(produit, form.photo.data)
        db.session.commit()
        flash("Produit créé.", "info")
        return redirect(url_for("admin.produits"))

    return render_template(
        "admin/produit_form.html",
        form=form,
        tarifs=tarifs,
        produit=None,
        prix_actuels={},
        prix_suggeres=_prix_suggeres(tarifs, form.prix_reference.data),
        sous_categories_json=sous_categories_par_categorie(),
        categories_json=categories_par_poste(),
    )


@bp.route("/produits/<int:produit_id>/modifier", methods=["GET", "POST"])
@permission_required("admin")
def produit_modifier(produit_id):
    produit = db.session.get(Produit, produit_id)
    if produit is None:
        abort(404)

    form = ProduitForm(obj=produit)
    _populate_produit_choices(form)
    if request.method == "GET":
        form.projet_id.data = produit.projet_id or 0
        form.sous_categorie_id.data = produit.sous_categorie_id or 0
        form.fournisseur_principal_id.data = produit.fournisseur_principal_id or 0

    tarifs = _tarifs_actifs()

    if form.validate_on_submit():
        produit.name = form.name.data
        produit.poste_id = form.poste_id.data
        produit.projet_id = form.projet_id.data or None
        produit.categorie_id = form.categorie_id.data
        produit.sous_categorie_id = form.sous_categorie_id.data or None
        produit.fournisseur_principal_id = form.fournisseur_principal_id.data or None
        produit.unite = form.unite.data or "unité"
        produit.prix_achat = form.prix_achat.data
        produit.prix_reference = form.prix_reference.data
        produit.stock_illimite = form.stock_illimite.data
        produit.prix_libre = form.prix_libre.data
        produit.seuil_alerte = form.seuil_alerte.data
        produit.stock_quantite = form.stock_quantite.data or 0
        produit.code_barres = form.code_barres.data or None
        _sauvegarder_tarifs(produit, tarifs)
        _enregistrer_photo(produit, form.photo.data)
        db.session.commit()
        flash("Produit mis à jour.", "info")
        return redirect(url_for("admin.produits"))

    prix_actuels = {prix.type_tarif_id: prix.montant for prix in produit.prix_tarifs}
    return render_template(
        "admin/produit_form.html",
        form=form,
        tarifs=tarifs,
        produit=produit,
        prix_actuels=prix_actuels,
        prix_suggeres=_prix_suggeres(tarifs, form.prix_reference.data),
        sous_categories_json=sous_categories_par_categorie(),
        categories_json=categories_par_poste(),
    )


def _sauvegarder_tarifs(produit, tarifs):
    existants = {prix.type_tarif_id: prix for prix in produit.prix_tarifs}
    for tarif in tarifs:
        raw = request.form.get(f"prix_{tarif.id}", "").strip()
        if raw == "":
            if tarif.id in existants:
                db.session.delete(existants[tarif.id])
            continue
        montant = int(raw)
        if tarif.id in existants:
            existants[tarif.id].montant = montant
        else:
            db.session.add(PrixProduit(produit_id=produit.id, type_tarif_id=tarif.id, montant=montant))


@bp.route("/produits/<int:produit_id>/archiver", methods=["POST"])
@permission_required("admin")
def produit_toggle_archive(produit_id):
    produit = db.session.get(Produit, produit_id)
    if produit is None:
        abort(404)
    produit.is_archived = not produit.is_archived
    db.session.commit()
    return redirect(url_for("admin.produits"))


@bp.route("/produits/<int:produit_id>/supprimer", methods=["POST"])
@permission_required("admin")
def produit_supprimer(produit_id):
    produit = db.session.get(Produit, produit_id)
    if produit is None:
        abort(404)
    raison = verifier_suppression_produit(produit)
    if raison:
        flash(f"Impossible de supprimer « {produit.name} » définitivement : {raison}.", "error")
        return redirect(url_for("admin.produits"))
    nom = produit.name
    if produit.photo_path:
        dossier = Path(current_app.config["UPLOAD_DIR_PRODUITS"]) / str(produit.id)
        (dossier / produit.photo_path).unlink(missing_ok=True)
    db.session.delete(produit)
    db.session.commit()
    flash(f"« {nom} » supprimé définitivement.", "info")
    return redirect(url_for("admin.produits"))


def _enregistrer_photo(produit, fichier):
    if not fichier or not fichier.filename:
        return
    dossier = Path(current_app.config["UPLOAD_DIR_PRODUITS"]) / str(produit.id)
    dossier.mkdir(parents=True, exist_ok=True)
    nom_sécurisé = secure_filename(fichier.filename)
    fichier.save(dossier / nom_sécurisé)
    produit.photo_path = nom_sécurisé


@bp.route("/produits/import", methods=["GET", "POST"])
@permission_required("admin")
def produits_import():
    form = ImportProduitsForm()
    resultat = None
    if form.validate_on_submit():
        resultat = importer_produits_excel(form.fichier.data)
        if resultat["crees"]:
            flash(f"{len(resultat['crees'])} produit(s) importé(s).", "info")
        if not resultat["crees"] and not resultat["erreurs"] and not resultat["ignores"]:
            flash("Aucune ligne à importer dans ce fichier.", "error")

    return render_template("admin/produits_import.html", form=form, resultat=resultat)


@bp.route("/produits/import/modele")
@permission_required("admin")
def produits_import_modele():
    buffer = generer_modele_xlsx()
    return send_file(
        buffer,
        as_attachment=True,
        download_name="modele_import_produits.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/produits/<int:produit_id>/photo")
@login_required
def produit_photo(produit_id):
    # @login_required seul (pas @permission_required("admin")) : la photo
    # doit rester visible depuis le PDV pour un Vendeur, qui n'a pas le droit
    # "admin" — seule l'authentification est exigée, pas un droit spécifique.
    produit = db.session.get(Produit, produit_id)
    if produit is None or not produit.photo_path:
        abort(404)
    dossier = Path(current_app.config["UPLOAD_DIR_PRODUITS"]) / str(produit.id)
    return send_from_directory(dossier, produit.photo_path)


# --- Informations légales (facturation officielle) --------------------------


@bp.route("/parametres-legaux", methods=["GET", "POST"])
@permission_required("admin")
def parametres_legaux():
    parametres = ParametresLegaux.get()
    form = ParametresLegauxForm(obj=parametres)
    if form.validate_on_submit():
        parametres.raison_sociale = form.raison_sociale.data
        parametres.adresse = form.adresse.data or None
        parametres.telephone = form.telephone.data or None
        parametres.email = form.email.data or None
        parametres.nif = form.nif.data or None
        parametres.stat = form.stat.data or None
        parametres.rcs = form.rcs.data or None
        db.session.commit()
        flash("Informations légales mises à jour.", "info")
        return redirect(url_for("admin.parametres_legaux"))
    return render_template("admin/parametres_legaux.html", form=form)


# --- Imprimante ticket / tiroir-caisse ---------------------------------------


@bp.route("/parametres-imprimante", methods=["GET", "POST"])
@permission_required("admin")
def parametres_imprimante():
    parametres = ParametresImprimante.get()
    form = ParametresImprimanteForm(obj=parametres)
    if form.validate_on_submit():
        parametres.nom_imprimante = form.nom_imprimante.data
        db.session.commit()
        flash("Nom de l'imprimante mis à jour.", "info")
        return redirect(url_for("admin.parametres_imprimante"))
    return render_template("admin/parametres_imprimante.html", form=form)


@bp.route("/parametres-imprimante/tester", methods=["POST"])
@permission_required("admin")
def parametres_imprimante_tester():
    from ..caisse.printer import ImprimanteError, ouvrir_tiroir

    parametres = ParametresImprimante.get()
    try:
        ouvrir_tiroir(parametres.nom_imprimante)
        flash("Commande envoyée : le tiroir devrait s'ouvrir.", "info")
    except ImprimanteError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.parametres_imprimante"))


# --- Paramètres RH -----------------------------------------------------------


@bp.route("/parametres-rh", methods=["GET", "POST"])
@permission_required("admin")
def parametres_rh():
    parametres = ParametresRH.get()
    form = ParametresRHForm(obj=parametres)
    if form.validate_on_submit():
        parametres.quota_conges_defaut = form.quota_conges_defaut.data
        db.session.commit()
        flash("Paramètres RH mis à jour.", "info")
        return redirect(url_for("admin.parametres_rh"))
    return render_template("admin/parametres_rh.html", form=form)


# --- Taux de change -----------------------------------------------------------


@bp.route("/taux-change", methods=["GET", "POST"])
@permission_required("admin")
def taux_change():
    taux = TauxChange.get()
    form = TauxChangeForm(obj=taux)
    if form.validate_on_submit():
        taux.ariary_pour_un_euro = form.ariary_pour_un_euro.data
        taux.updated_by_name = current_user.full_name
        db.session.commit()
        flash("Taux de change mis à jour.", "info")
        return redirect(url_for("admin.taux_change"))
    return render_template("admin/taux_change.html", form=form, taux=taux)
