"""Journal d'activité unifié : "qui a fait quoi, quand" à travers toute
l'application, pour tous les profils y compris l'administrateur (retour
utilisateur du 08/08/2026).

Plutôt que d'ajouter un système de journalisation générique séparé (risque
d'oublier des routes, double maintenance), on s'appuie sur ce qui existe déjà
partout dans le modèle : chaque opération métier (vente, achat, mouvement de
stock, rémunération RH, ajustement de compte...) est déjà tracée avec
`created_by_name` + `created_at` (convention du projet). Ce module se
contente d'agréger ces tables et de les fusionner avec le journal d'audit en
fichier plat (`backup_service.log_audit`, utilisé pour les actions qui n'ont
pas de ligne en base : sauvegardes, suppressions, gestion des utilisateurs)."""

from datetime import datetime, timezone

from ..extensions import db
from ..models import (
    Absence,
    Achat,
    AjustementCompte,
    ClientPaiement,
    Fabrication,
    Facture,
    Inventaire,
    MouvementCaisse,
    MouvementStock,
    RemunerationSalarie,
    Vente,
)
from .backup_service import lire_audit_log

MODULES = [
    ("ventes", "Ventes"),
    ("factures", "Factures"),
    ("achats", "Achats"),
    ("stocks", "Mouvements de stock"),
    ("inventaires", "Inventaires"),
    ("production", "Fabrications"),
    ("rh_remunerations", "RH — Rémunérations"),
    ("rh_absences", "RH — Absences"),
    ("clients", "Paiements clients"),
    ("caisse", "Mouvements de caisse"),
    ("comptes", "Ajustements de comptes"),
    ("administration", "Administration"),
]

_LABELS_MODULE = dict(MODULES)

TYPES_REMUNERATION_LABELS = {
    "salaire_mensuel": "Salaire mensuel",
    "salaire_hebdomadaire": "Salaire hebdomadaire",
    "remuneration_journaliere": "Rémunération journalière",
    "avance": "Avance",
    "prime": "Prime",
    "retenue": "Retenue",
}


def _montant(n):
    return "{:,}".format(n).replace(",", " ")


def _entrees_modele(query, module, description):
    return [
        {
            "horodatage": obj.created_at,
            "utilisateur": obj.created_by_name,
            "module": module,
            "module_label": _LABELS_MODULE[module],
            "description": description(obj),
        }
        for obj in query
    ]


def _bornee(requete, colonne, depuis, jusqua):
    if depuis:
        requete = requete.filter(colonne >= depuis)
    if jusqua:
        requete = requete.filter(colonne <= jusqua)
    return requete


def _entrees_administration(app, depuis, jusqua, limite):
    """Journal d'audit en fichier plat (backups, suppressions, gestion des
    comptes utilisateurs...) — voir backup_service.log_audit. Reconverti au
    même format que les entrées issues de la base pour pouvoir tout trier
    ensemble."""
    entrees = []
    for ligne in lire_audit_log(app, limite=limite):
        try:
            horodatage = datetime.fromisoformat(ligne["horodatage"])
        except (KeyError, ValueError):
            continue
        # SQLite ne conserve pas le fuseau horaire des colonnes
        # DateTime(timezone=True) : les horodatages issus de la base
        # ressortent "naïfs" (sans tzinfo), bien qu'exprimés en UTC comme
        # partout dans l'appli (utcnow()) — on aligne celui-ci sur le même
        # format pour pouvoir tout trier ensemble sans TypeError.
        if horodatage.tzinfo is not None:
            horodatage = horodatage.astimezone(timezone.utc).replace(tzinfo=None)
        if depuis and horodatage < depuis:
            continue
        if jusqua and horodatage > jusqua:
            continue
        entrees.append(
            {
                "horodatage": horodatage,
                "utilisateur": ligne.get("utilisateur", "?"),
                "module": "administration",
                "module_label": _LABELS_MODULE["administration"],
                "description": f"{ligne.get('action', '?')} — {ligne.get('detail', '')}".strip(" —"),
            }
        )
    return entrees


def construire_journal(app, depuis=None, jusqua=None, utilisateur=None, module=None, limite=200):
    """Fusionne toutes les sources en une liste triée du plus récent au plus
    ancien, filtrée par utilisateur (sous-chaîne, insensible à la casse),
    module et plage de dates. `limite` borne le nombre de lignes lues par
    source (pas le total final) : une table jamais modifiée récemment ne doit
    pas empêcher d'en voir une autre très active, chacune est donc limitée
    indépendamment puis le tout est refusionné et retronqué à `limite`."""

    sources = []

    if module is None or module == "ventes":
        q = _bornee(Vente.query, Vente.created_at, depuis, jusqua).order_by(Vente.created_at.desc()).limit(limite)
        sources += _entrees_modele(
            q, "ventes",
            lambda v: f"Vente #{v.id}"
            + (f" — {v.client_nom}" if v.client_nom else "")
            + f" — {_montant(v.total)} Ar",
        )

    if module is None or module == "factures":
        q = _bornee(Facture.query, Facture.created_at, depuis, jusqua).order_by(Facture.created_at.desc()).limit(limite)
        sources += _entrees_modele(
            q, "factures",
            lambda f: f"Facture {f.numero} — {f.client_nom} — {_montant(f.total)} Ar",
        )

    if module is None or module == "achats":
        q = _bornee(Achat.query, Achat.created_at, depuis, jusqua).order_by(Achat.created_at.desc()).limit(limite)
        sources += _entrees_modele(
            q, "achats",
            lambda a: (a.nom or ("Achat de stock" if a.type_achat == "stock" else "Dépense"))
            + f" — {_montant(a.montant_total)} Ar",
        )

    if module is None or module == "stocks":
        q = (
            _bornee(MouvementStock.query, MouvementStock.created_at, depuis, jusqua)
            .order_by(MouvementStock.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "stocks",
            lambda m: f"{'Entrée' if m.type_mouvement == 'entree' else 'Sortie'} stock « {m.produit.name} » "
            f"({m.motif}) — {m.quantite}",
        )

    if module is None or module == "inventaires":
        q = (
            _bornee(Inventaire.query, Inventaire.created_at, depuis, jusqua)
            .order_by(Inventaire.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "inventaires",
            lambda i: f"Inventaire #{i.id} ({i.type_inventaire}) — {i.statut}",
        )

    if module is None or module == "production":
        q = (
            _bornee(Fabrication.query, Fabrication.created_at, depuis, jusqua)
            .order_by(Fabrication.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "production",
            lambda f: f"Fabrication « {f.produit.name} » — {f.quantite}",
        )

    if module is None or module == "rh_remunerations":
        q = (
            _bornee(RemunerationSalarie.query, RemunerationSalarie.created_at, depuis, jusqua)
            .order_by(RemunerationSalarie.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "rh_remunerations",
            lambda r: f"{TYPES_REMUNERATION_LABELS.get(r.type_remuneration, r.type_remuneration)} — "
            f"{r.salarie.nom} — {_montant(r.montant)} Ar",
        )

    if module is None or module == "rh_absences":
        q = (
            _bornee(Absence.query, Absence.created_at, depuis, jusqua)
            .order_by(Absence.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "rh_absences",
            lambda a: f"Absence ({a.type_absence}) — {a.salarie.nom} — "
            f"{a.date_debut.strftime('%d/%m/%Y')} au {a.date_fin.strftime('%d/%m/%Y')}",
        )

    if module is None or module == "clients":
        q = (
            _bornee(ClientPaiement.query, ClientPaiement.created_at, depuis, jusqua)
            .order_by(ClientPaiement.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "clients",
            lambda p: f"Paiement crédit — {p.client.nom} — {_montant(p.montant)} Ar",
        )

    if module is None or module == "caisse":
        q = (
            _bornee(MouvementCaisse.query, MouvementCaisse.created_at, depuis, jusqua)
            .order_by(MouvementCaisse.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "caisse",
            lambda m: f"{'Entrée' if m.type_mouvement == 'entree' else 'Sortie'} caisse — "
            f"{_montant(m.montant)} Ar — {m.motif}",
        )

    if module is None or module == "comptes":
        q = (
            _bornee(AjustementCompte.query, AjustementCompte.created_at, depuis, jusqua)
            .order_by(AjustementCompte.created_at.desc())
            .limit(limite)
        )
        sources += _entrees_modele(
            q, "comptes",
            lambda a: f"Ajustement solde « {a.compte_financier.name} » : "
            f"{_montant(a.ancien_solde)} → {_montant(a.nouveau_solde)} Ar — {a.motif}",
        )

    if module is None or module == "administration":
        sources += _entrees_administration(app, depuis, jusqua, limite)

    sources.sort(key=lambda e: e["horodatage"], reverse=True)

    if utilisateur:
        terme = utilisateur.strip().lower()
        sources = [e for e in sources if terme in (e["utilisateur"] or "").lower()]

    return sources[:limite]
