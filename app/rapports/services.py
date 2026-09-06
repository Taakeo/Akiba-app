from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

from ..models import Achat, Fabrication, LigneVente, RemunerationSalarie, Vente, VenteExterne

# Mois abrégés en français, tels qu'utilisés dans le classeur comptable de
# référence de l'association (Outils/Essai de compte pour akiba yanis.xlsx,
# feuille "Saisie") — repris à l'identique pour le Rapport total (§4).
MOIS_ABREGES = {
    1: "Janv.", 2: "Févr.", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin",
    7: "Juillet", 8: "Août", 9: "Sept.", 10: "Oct.", 11: "Nov.", 12: "Déc.",
}

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
            Fabrication.date_fabrication >= date_debut,
            Fabrication.date_fabrication <= date_fin,
            Fabrication.is_annule.is_(False),
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
        RemunerationSalarie.date_versement >= date_debut,
        RemunerationSalarie.date_versement <= date_fin,
        RemunerationSalarie.is_annule.is_(False),
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
    achats = Achat.query.filter(
        Achat.date_achat >= date_debut, Achat.date_achat <= date_fin, Achat.is_annule.is_(False)
    ).all()

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


def rapport_total(date_debut, date_fin, poste_id=None, projet_id=None):
    """Grand livre unifié (Ventes PDV + Ventes externes + Achats + RH) au même
    format que le classeur comptable de référence de l'association (Mois /
    Poste / Catégorie / Sous-catégorie / Note / Recettes / Dépenses / Projet)
    — calqué sur `Outils/Essai de compte pour akiba yanis.xlsx`, feuille
    "Saisie". `poste_id`/`projet_id` sont les filtres additionnels demandés en
    plus de la période, en écho à ceux du classeur de référence."""
    from ..models import TYPES_REMUNERATION, VenteExterne

    labels_remuneration = dict(TYPES_REMUNERATION)
    debut, fin = _bornes_utc(date_debut, date_fin)
    lignes = []

    ventes = (
        LigneVente.query.join(Vente)
        .filter(Vente.statut == "validee", Vente.created_at >= debut, Vente.created_at < fin)
        .all()
    )
    for ligne in ventes:
        if poste_id and ligne.poste_id != poste_id:
            continue
        if projet_id and ligne.projet_id != projet_id:
            continue
        lignes.append(
            {
                "date": ligne.vente.created_at.date(),
                "poste": ligne.poste.name,
                "categorie": ligne.categorie.name,
                "sous_categorie": ligne.sous_categorie.name if ligne.sous_categorie_id else "",
                "note": f"Vente PDV #{ligne.vente_id} — {ligne.produit_nom}",
                "recette": ligne.total_ligne,
                "depense": 0,
                "projet": ligne.projet.name if ligne.projet_id else "",
            }
        )

    # Ventes externes (§ nouvel onglet) — inclut les dons/financements passés
    # par cet onglet, confirmé comme leur point d'entrée dans le rapport total.
    ventes_externes = VenteExterne.query.filter(
        VenteExterne.date_vente >= date_debut,
        VenteExterne.date_vente <= date_fin,
        VenteExterne.is_annule.is_(False),
    ).all()
    for ve in ventes_externes:
        if poste_id and ve.poste_id != poste_id:
            continue
        if projet_id and ve.projet_id != projet_id:
            continue
        client = ve.client.nom if ve.client_id else (ve.client_nom or "Client de passage")
        lignes.append(
            {
                "date": ve.date_vente,
                "poste": ve.poste.name,
                "categorie": ve.categorie.name,
                "sous_categorie": ve.sous_categorie.name if ve.sous_categorie_id else "",
                "note": ve.observations or f"Vente externe — {client}",
                "recette": ve.montant_total,
                "depense": 0,
                "projet": ve.projet.name if ve.projet_id else "",
            }
        )

    achats_total = Achat.query.filter(
        Achat.date_achat >= date_debut, Achat.date_achat <= date_fin, Achat.is_annule.is_(False)
    ).all()
    for achat in achats_total:
        if poste_id and achat.poste_id != poste_id:
            continue
        if projet_id and achat.projet_id != projet_id:
            continue
        lignes.append(
            {
                "date": achat.date_achat,
                "poste": achat.poste.name,
                "categorie": achat.categorie.name,
                "sous_categorie": achat.sous_categorie.name if achat.sous_categorie_id else "",
                "note": achat.nom or achat.observations or "",
                "recette": 0,
                "depense": achat.montant_total,
                "projet": achat.projet.name if achat.projet_id else "",
            }
        )

    # RH (confirmé : les rémunérations doivent apparaître dans le rapport
    # total). Une retenue, ou un montant sans moyen de paiement renseigné, n'a
    # jamais d'effet réel sur les comptes (§5.4 spec) — exclue des dépenses ici
    # pour la même raison, sinon le rapport afficherait de l'argent qui n'a en
    # réalité jamais bougé. `Salarie` n'a pas de vraie catégorie : "Salaires"
    # est un libellé calculé, pas une colonne en base.
    remunerations = RemunerationSalarie.query.filter(
        RemunerationSalarie.date_versement >= date_debut,
        RemunerationSalarie.date_versement <= date_fin,
        RemunerationSalarie.is_annule.is_(False),
    ).all()
    for r in remunerations:
        if r.type_remuneration == "retenue" or not r.moyen_paiement_id:
            continue
        salarie = r.salarie
        if poste_id and salarie.poste_id != poste_id:
            continue
        if projet_id and salarie.projet_id != projet_id:
            continue
        lignes.append(
            {
                "date": r.date_versement,
                "poste": salarie.poste.name if salarie.poste_id else "GENERAL",
                "categorie": "Salaires",
                "sous_categorie": "",
                "note": f"{salarie.nom} — {labels_remuneration.get(r.type_remuneration, r.type_remuneration)}",
                "recette": 0,
                "depense": r.montant,
                "projet": salarie.projet.name if salarie.projet_id else "",
            }
        )

    lignes.sort(key=lambda l: l["date"])
    for l in lignes:
        l["mois"] = MOIS_ABREGES[l["date"].month]

    return lignes


def taxonomie_export():
    """Hiérarchie Poste -> Catégorie -> Sous-catégorie réellement en base
    (pas l'ancienne structure École/Dispensaire du classeur de référence),
    pour construire les listes déroulantes en cascade de l'export Excel du
    Rapport total (§ export_total_xlsx)."""
    from ..models import Categorie, Poste, SousCategorie

    postes = [p.name for p in Poste.query.filter_by(is_archived=False).order_by(Poste.name).all()]

    categories_par_poste = OrderedDict()
    for c in Categorie.query.filter_by(is_archived=False).order_by(Categorie.poste_id, Categorie.ordre, Categorie.name):
        categories_par_poste.setdefault(c.poste.name, []).append(c.name)

    sous_categories_par_categorie = OrderedDict()
    for sc in SousCategorie.query.filter_by(is_archived=False).order_by(SousCategorie.name):
        cle = (sc.categorie.poste.name, sc.categorie.name)
        sous_categories_par_categorie.setdefault(cle, []).append(sc.name)

    return {
        "postes": postes,
        "categories_par_poste": categories_par_poste,
        "sous_categories_par_categorie": sous_categories_par_categorie,
    }


def bilan_total(lignes):
    """Totaux par poste et répartition poste -> catégorie, à partir des lignes
    de rapport_total() — §BILAN du classeur de référence. Le bloc de
    pourcentages Dépenses/Recettes du fichier fourni n'est volontairement pas
    repris : ce sont des formules cassées dans le fichier (dénominateurs à
    zéro, #DIV/0!), pas une donnée exploitable."""
    par_poste = OrderedDict()
    par_poste_categorie = OrderedDict()

    for l in lignes:
        poste = par_poste.setdefault(l["poste"], {"recettes": 0, "depenses": 0})
        poste["recettes"] += l["recette"]
        poste["depenses"] += l["depense"]

        cle = (l["poste"], l["categorie"])
        cat = par_poste_categorie.setdefault(cle, {"recettes": 0, "depenses": 0})
        cat["recettes"] += l["recette"]
        cat["depenses"] += l["depense"]

    postes = [
        {"poste": poste, "recettes": v["recettes"], "depenses": v["depenses"], "solde": v["recettes"] - v["depenses"]}
        for poste, v in par_poste.items()
    ]
    categories = [
        {
            "poste": poste,
            "categorie": categorie,
            "recettes": v["recettes"],
            "depenses": v["depenses"],
            "solde": v["recettes"] - v["depenses"],
        }
        for (poste, categorie), v in par_poste_categorie.items()
    ]
    total_recettes = sum(p["recettes"] for p in postes)
    total_depenses = sum(p["depenses"] for p in postes)
    return {
        "postes": postes,
        "categories": categories,
        "total_recettes": total_recettes,
        "total_depenses": total_depenses,
        "solde": total_recettes - total_depenses,
    }
