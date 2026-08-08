from datetime import date, datetime

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from ..admin.import_excel import generer_modele_salaries_xlsx, importer_salaries_excel
from ..auth.decorators import permission_required
from ..caisse.services import debiter_compte, montant_depuis_ariary
from ..extensions import db
from ..models import (
    Absence,
    MoyenPaiement,
    ParametresLegaux,
    ParametresRH,
    Poste,
    Projet,
    RemunerationSalarie,
    Salarie,
    verifier_suppression_salarie,
)
from . import bp
from .forms import AbsenceForm, ImportSalariesForm, RemunerationForm, SalarieForm
from .services import TYPES_SALAIRE, construire_fiche_paie


def _populate_salarie_choices(form):
    form.poste_id.choices = [(0, "—")] + [
        (p.id, p.name) for p in Poste.query.filter_by(is_archived=False).order_by(Poste.name)
    ]
    form.projet_id.choices = [(0, "—")] + [
        (p.id, p.name) for p in Projet.query.filter_by(is_archived=False).order_by(Projet.name)
    ]


@bp.route("/")
@permission_required("rh")
def index():
    items = Salarie.query.order_by(Salarie.is_archived, Salarie.nom).all()
    return render_template("rh/index.html", items=items)


@bp.route("/nouveau", methods=["GET", "POST"])
@permission_required("rh")
def nouveau():
    form = SalarieForm()
    _populate_salarie_choices(form)

    if not form.is_submitted():
        form.quota_conges.data = ParametresRH.get().quota_conges_defaut

    if form.validate_on_submit():
        salarie = Salarie(
            nom=form.nom.data,
            telephone=form.telephone.data or None,
            fonction=form.fonction.data or None,
            type_contrat=form.type_contrat.data or None,
            date_embauche=form.date_embauche.data,
            poste_id=form.poste_id.data or None,
            projet_id=form.projet_id.data or None,
            salaire_habituel=form.salaire_habituel.data,
            frequence_remuneration=form.frequence_remuneration.data or None,
            quota_conges=form.quota_conges.data
            if form.quota_conges.data is not None
            else ParametresRH.get().quota_conges_defaut,
        )
        db.session.add(salarie)
        db.session.commit()
        flash(f"Fiche salarié {salarie.nom} créée.", "info")
        return redirect(url_for("rh.index"))

    return render_template("rh/form.html", form=form, salarie=None)


@bp.route("/import", methods=["GET", "POST"])
@permission_required("rh")
def import_salaries():
    form = ImportSalariesForm()
    resultat = None
    if form.validate_on_submit():
        resultat = importer_salaries_excel(form.fichier.data)
        if resultat["crees"]:
            flash(f"{len(resultat['crees'])} fiche(s) salarié créée(s).", "info")
        if not resultat["crees"] and not resultat["erreurs"] and not resultat["ignores"]:
            flash("Aucune ligne à importer dans ce fichier.", "error")

    return render_template("rh/import.html", form=form, resultat=resultat)


@bp.route("/import/modele")
@permission_required("rh")
def import_salaries_modele():
    buffer = generer_modele_salaries_xlsx()
    return send_file(
        buffer,
        as_attachment=True,
        download_name="modele_import_salaries.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/<int:salarie_id>/modifier", methods=["GET", "POST"])
@permission_required("rh")
def modifier(salarie_id):
    salarie = db.session.get(Salarie, salarie_id)
    if salarie is None:
        abort(404)

    form = SalarieForm(obj=salarie)
    _populate_salarie_choices(form)
    if not form.is_submitted():
        form.poste_id.data = salarie.poste_id or 0
        form.projet_id.data = salarie.projet_id or 0
        form.frequence_remuneration.data = salarie.frequence_remuneration or ""

    if form.validate_on_submit():
        salarie.nom = form.nom.data
        salarie.telephone = form.telephone.data or None
        salarie.fonction = form.fonction.data or None
        salarie.type_contrat = form.type_contrat.data or None
        salarie.date_embauche = form.date_embauche.data
        salarie.poste_id = form.poste_id.data or None
        salarie.projet_id = form.projet_id.data or None
        salarie.salaire_habituel = form.salaire_habituel.data
        salarie.frequence_remuneration = form.frequence_remuneration.data or None
        salarie.quota_conges = form.quota_conges.data
        db.session.commit()
        flash("Fiche salarié mise à jour.", "info")
        return redirect(url_for("rh.index"))

    return render_template("rh/form.html", form=form, salarie=salarie)


@bp.route("/<int:salarie_id>/archiver", methods=["POST"])
@permission_required("rh")
def toggle_archive(salarie_id):
    salarie = db.session.get(Salarie, salarie_id)
    if salarie is None:
        abort(404)
    salarie.is_archived = not salarie.is_archived
    db.session.commit()
    return redirect(url_for("rh.index"))


@bp.route("/<int:salarie_id>/supprimer", methods=["POST"])
@permission_required("rh")
def supprimer(salarie_id):
    salarie = db.session.get(Salarie, salarie_id)
    if salarie is None:
        abort(404)
    raison = verifier_suppression_salarie(salarie)
    if raison:
        flash(f"Impossible de supprimer « {salarie.nom} » définitivement : {raison}.", "error")
        return redirect(url_for("rh.index"))
    nom = salarie.nom
    db.session.delete(salarie)
    db.session.commit()
    flash(f"« {nom} » supprimé définitivement.", "info")
    return redirect(url_for("rh.index"))


@bp.route("/<int:salarie_id>")
@permission_required("rh")
def fiche(salarie_id):
    salarie = db.session.get(Salarie, salarie_id)
    if salarie is None:
        abort(404)

    form = RemunerationForm()
    form.moyen_paiement_id.choices = [(0, "— non versé (à régler plus tard)")] + [
        (m.id, m.name) for m in MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name)
    ]
    absence_form = AbsenceForm()

    total_net = sum(
        r.montant if r.type_remuneration != "retenue" else -r.montant for r in salarie.remunerations
    )

    # Filtre "du ... au ..." sur les absences affichées, pour se concentrer
    # sur une période sans faire défiler tout l'historique.
    filtre_debut = request.args.get("depuis", "")
    filtre_fin = request.args.get("jusqua", "")
    absences = salarie.absences
    if filtre_debut:
        try:
            d = datetime.strptime(filtre_debut, "%Y-%m-%d").date()
            absences = [a for a in absences if a.date_fin >= d]
        except ValueError:
            filtre_debut = ""
    if filtre_fin:
        try:
            f = datetime.strptime(filtre_fin, "%Y-%m-%d").date()
            absences = [a for a in absences if a.date_debut <= f]
        except ValueError:
            filtre_fin = ""

    total_jours_absence = sum(a.nombre_jours for a in absences)

    annee_courante = date.today().year
    conges_pris = salarie.jours_conge_paye_pris(annee_courante)
    quota = salarie.quota_conges

    return render_template(
        "rh/fiche.html",
        salarie=salarie,
        form=form,
        total_net=total_net,
        absence_form=absence_form,
        absences=absences,
        total_jours_absence=total_jours_absence,
        filtre_debut=filtre_debut,
        filtre_fin=filtre_fin,
        annee_courante=annee_courante,
        conges_pris=conges_pris,
        conges_quota=quota,
        conges_restants=(quota - conges_pris) if quota is not None else None,
    )


@bp.route("/<int:salarie_id>/remuneration", methods=["POST"])
@permission_required("rh")
def ajouter_remuneration(salarie_id):
    salarie = db.session.get(Salarie, salarie_id)
    if salarie is None:
        abort(404)

    form = RemunerationForm()
    form.moyen_paiement_id.choices = [(0, "— non versé (à régler plus tard)")] + [
        (m.id, m.name) for m in MoyenPaiement.query.filter_by(is_archived=False).order_by(MoyenPaiement.name)
    ]

    if form.validate_on_submit():
        moyen = db.session.get(MoyenPaiement, form.moyen_paiement_id.data) if form.moyen_paiement_id.data else None

        remuneration = RemunerationSalarie(
            salarie_id=salarie.id,
            type_remuneration=form.type_remuneration.data,
            montant=form.montant.data,
            date_versement=form.date_versement.data,
            moyen_paiement_id=moyen.id if moyen else None,
            observations=form.observations.data or None,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(remuneration)

        if moyen is not None:
            # form.montant.data est toujours en ariary (salaire, avance, prime...
            # tous exprimés en ariary, quel que soit le moyen utilisé pour
            # payer) — le compte débité doit refléter ce qui en est réellement
            # sorti dans sa propre devise (même correction que pour les
            # achats, les paiements PDV et les remboursements de crédit).
            debiter_compte(moyen.compte_financier, montant_depuis_ariary(moyen, form.montant.data))

        db.session.commit()
        flash("Rémunération enregistrée.", "info")
    else:
        flash("Formulaire invalide.", "error")

    return redirect(url_for("rh.fiche", salarie_id=salarie.id))


@bp.route("/<int:salarie_id>/remuneration/<int:remuneration_id>/fiche-paie")
@permission_required("rh")
def fiche_paie(salarie_id, remuneration_id):
    remuneration = db.session.get(RemunerationSalarie, remuneration_id)
    if remuneration is None or remuneration.salarie_id != salarie_id:
        abort(404)
    if remuneration.type_remuneration not in TYPES_SALAIRE:
        # Une fiche de paie s'imprime pour un versement de salaire, pas pour
        # une avance/prime/retenue isolée (voir construire_fiche_paie).
        abort(404)

    donnees = construire_fiche_paie(remuneration)
    return render_template(
        "rh/fiche_paie_impression.html", parametres_legaux=ParametresLegaux.get(), **donnees
    )


@bp.route("/<int:salarie_id>/absence", methods=["POST"])
@permission_required("rh")
def ajouter_absence(salarie_id):
    salarie = db.session.get(Salarie, salarie_id)
    if salarie is None:
        abort(404)

    form = AbsenceForm()
    if form.validate_on_submit():
        absence = Absence(
            salarie_id=salarie.id,
            type_absence=form.type_absence.data,
            date_debut=form.date_debut.data,
            date_fin=form.date_fin.data,
            observations=form.observations.data or None,
            created_by_subprofile_id=current_user.id,
            created_by_name=current_user.full_name,
        )
        db.session.add(absence)
        db.session.commit()
        flash("Absence enregistrée.", "info")
    else:
        for messages in form.errors.values():
            for message in messages:
                flash(message, "error")

    return redirect(url_for("rh.fiche", salarie_id=salarie.id))


@bp.route("/<int:salarie_id>/absence/<int:absence_id>/supprimer", methods=["POST"])
@permission_required("rh")
def supprimer_absence(salarie_id, absence_id):
    absence = db.session.get(Absence, absence_id)
    if absence is None or absence.salarie_id != salarie_id:
        abort(404)
    db.session.delete(absence)
    db.session.commit()
    flash("Absence supprimée.", "info")
    return redirect(url_for("rh.fiche", salarie_id=salarie_id))
