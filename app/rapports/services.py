from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

from ..models import Achat, Fabrication, LigneVente, RemunerationSalarie, Vente

GROUPES_VENTES = [
    ("produit", "Produit"),
    ("categorie", "Catégorie"),
    ("poste", "Poste"),
    ("projet", "Projet"),
    ("vendeur", "Vendeur"),
    ("date", "Date (évolution)"),
]

GROUPES_ACHATS = [
    ("fournisseur", "Fournisseur"),
    ("categorie", "Catégorie"),
    ("poste", "Poste"),
    ("projet", "Projet"),
    ("date", "Date (évolution)"),
]

GROUPES_RH = [
    ("salarie", "Salarié"),
    ("projet", "Projet"),
]


def periode_par_defaut():
    aujourdhui = datetime.now(timezone.utc).date()
    return aujourdhui.replace(day=1), aujourdhui


def parser_date(raw, defaut):
    if not raw:
        return defaut
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return defaut


def _bornes_utc(date_debut, date_fin):
    debut = datetime(date_debut.year, date_debut.month, date_debut.day, tzinfo=timezone.utc)
    fin = datetime(date_fin.year, date_fin.month, date_fin.day, tzinfo=timezone.utc) + timedelta(days=1)
    return debut, fin


def _cle_vente(ligne, group_by):
    if group_by == "categorie":
        return ligne.categorie.name
    if group_by == "poste":
        return ligne.poste.name
    if group_by == "projet":
        return ligne.projet.name if ligne.projet_id else "Aucun"
    if group_by == "vendeur":
        return ligne.vente.created_by_name
    if group_by == "date":
        return ligne.vente.created_at.date().isoformat()
    return ligne.produit_nom


def rapport_ventes(date_debut, date_fin, group_by):
    if group_by not in dict(GROUPES_VENTES):
        group_by = "produit"

    debut, fin = _bornes_utc(date_debut, date_fin)
    lignes = (
        LigneVente.query.join(Vente)
        .filter(Vente.statut == "validee", Vente.created_at >= debut, Vente.created_at < fin)
        .all()
    )

    groupes = OrderedDict()
    for ligne in lignes:
        cle = _cle_vente(ligne, group_by)
        entree = groupes.setdefault(cle, {"quantite": 0, "total": 0})
        entree["quantite"] += ligne.quantite
        entree["total"] += ligne.total_ligne

    # Par date : ordre chronologique (évolution) ; sinon classement par montant.
    if group_by == "date":
        lignes_triees = [
            {"libelle": cle, **valeurs} for cle, valeurs in sorted(groupes.items())
        ]
    else:
        lignes_triees = sorted(
            ({"libelle": cle, **valeurs} for cle, valeurs in groupes.items()),
            key=lambda r: r["total"],
            reverse=True,
        )
    total_general = sum(r["total"] for r in lignes_triees)
    return lignes_triees, total_general


def rapport_production(date_debut, date_fin):
    """Fabrications, quantités produites, historique des lots. §9.2 CDC v1."""
    fabrications = (
        Fabrication.query.filter(
            Fabrication.date_fabrication >= date_debut, Fabrication.date_fabrication <= date_fin
        )
        .order_by(Fabrication.date_fabrication.desc())
        .all()
    )

    par_produit = OrderedDict()
    for fab in fabrications:
        entree = par_produit.setdefault(fab.produit.name, {"quantite": 0})
        entree["quantite"] += fab.quantite

    lignes_triees = sorted(
        ({"libelle": cle, **valeurs} for cle, valeurs in par_produit.items()),
        key=lambda r: r["quantite"],
        reverse=True,
    )
    return fabrications, lignes_triees


def _cle_rh(remuneration, group_by):
    if group_by == "projet":
        salarie = remuneration.salarie
        return salarie.projet.name if salarie.projet_id else "Aucun"
    return remuneration.salarie.nom


def rapport_rh(date_debut, date_fin, group_by):
    """Salaires, avances, coût par salarié / par projet. §9.2 CDC v1."""
    if group_by not in dict(GROUPES_RH):
        group_by = "salarie"

    remunerations = RemunerationSalarie.query.filter(
        RemunerationSalarie.date_versement >= date_debut, RemunerationSalarie.date_versement <= date_fin
    ).all()

    groupes = OrderedDict()
    for r in remunerations:
        cle = _cle_rh(r, group_by)
        entree = groupes.setdefault(cle, {"total": 0})
        montant = -r.montant if r.type_remuneration == "retenue" else r.montant
        entree["total"] += montant

    lignes_triees = sorted(
        ({"libelle": cle, **valeurs} for cle, valeurs in groupes.items()),
        key=lambda r: r["total"],
        reverse=True,
    )
    total_general = sum(r["total"] for r in lignes_triees)
    return lignes_triees, total_general


def _cle_achat(achat, group_by):
    if group_by == "categorie":
        return achat.categorie.name
    if group_by == "poste":
        return achat.poste.name
    if group_by == "projet":
        return achat.projet.name if achat.projet_id else "Aucun"
    if group_by == "date":
        return achat.date_achat.isoformat()
    return achat.fournisseur.name if achat.fournisseur_id else "Sans fournisseur"


def rapport_achats(date_debut, date_fin, group_by):
    if group_by not in dict(GROUPES_ACHATS):
        group_by = "fournisseur"

    debut, fin = _bornes_utc(date_debut, date_fin)
    achats = Achat.query.filter(Achat.date_achat >= date_debut, Achat.date_achat <= date_fin).all()

    groupes = OrderedDict()
    for achat in achats:
        cle = _cle_achat(achat, group_by)
        entree = groupes.setdefault(cle, {"nombre": 0, "total": 0})
        entree["nombre"] += 1
        entree["total"] += achat.montant_total

    if group_by == "date":
        lignes_triees = [
            {"libelle": cle, **valeurs} for cle, valeurs in sorted(groupes.items())
        ]
    else:
        lignes_triees = sorted(
            ({"libelle": cle, **valeurs} for cle, valeurs in groupes.items()),
            key=lambda r: r["total"],
            reverse=True,
        )
    total_general = sum(r["total"] for r in lignes_triees)
    return lignes_triees, total_general
