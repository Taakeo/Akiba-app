from ..models import TYPES_REMUNERATION

TYPES_SALAIRE = ("salaire_mensuel", "salaire_hebdomadaire", "remuneration_journaliere")

_LABELS_TYPE_REMUNERATION = dict(TYPES_REMUNERATION)


def construire_fiche_paie(remuneration):
    """Assemble les données de la fiche de paie imprimable pour UNE ligne de
    salaire (mensuel/hebdo/journalier) — sépare "assembler les données" de
    "afficher" (route + template), même principe que côté École Akiba, mais
    contenu et calculs propres au modèle RH d'Akiba (RemunerationSalarie est
    un grand livre de mouvements, pas un paiement mensuel isolé comme côté
    école — primes/avances/retenues y sont réellement suivies séparément).

    Le "récapitulatif" (primes/avances/retenues à valoir sur cette paie) est
    calculé par chronologie : tout ce qui a été enregistré pour ce salarié
    depuis sa précédente ligne de salaire (exclue) jusqu'à celle-ci (incluse)
    — pas de champ "période" dédié dans le modèle, cette fenêtre est déduite
    des dates déjà présentes plutôt que d'en inventer une (retour utilisateur
    du 07/08/2026 : régime confirmé après clarification)."""

    salarie = remuneration.salarie

    # Ligne de salaire précédente (même salarié, un des 3 types "salaire"),
    # strictement antérieure à celle-ci — définit le début de la fenêtre du
    # récapitulatif. Départage par id si deux lignes partagent la même date.
    precedente = None
    for r in salarie.remunerations:
        if r.id == remuneration.id or r.type_remuneration not in TYPES_SALAIRE:
            continue
        if (r.date_versement, r.id) >= (remuneration.date_versement, remuneration.id):
            continue
        if precedente is None or (r.date_versement, r.id) > (precedente.date_versement, precedente.id):
            precedente = r

    borne_inf = precedente.date_versement if precedente else None

    mouvements = [
        r
        for r in salarie.remunerations
        if r.id != remuneration.id
        and r.type_remuneration in ("prime", "avance", "retenue")
        and r.date_versement <= remuneration.date_versement
        and (borne_inf is None or r.date_versement > borne_inf)
    ]
    mouvements.sort(key=lambda r: r.date_versement)

    total_primes = sum(r.montant for r in mouvements if r.type_remuneration == "prime")
    total_avances = sum(r.montant for r in mouvements if r.type_remuneration == "avance")
    total_retenues = sum(r.montant for r in mouvements if r.type_remuneration == "retenue")
    net_a_payer = remuneration.montant + total_primes - total_retenues - total_avances

    annee = remuneration.date_versement.year
    conges_pris = salarie.jours_conge_paye_pris(annee)
    quota = salarie.quota_conges

    return {
        "salarie": salarie,
        "remuneration": remuneration,
        "type_label": _LABELS_TYPE_REMUNERATION.get(remuneration.type_remuneration, remuneration.type_remuneration),
        "periode_debut": borne_inf,
        "periode_fin": remuneration.date_versement,
        "mouvements": mouvements,
        "labels_type_remuneration": _LABELS_TYPE_REMUNERATION,
        "total_primes": total_primes,
        "total_avances": total_avances,
        "total_retenues": total_retenues,
        "net_a_payer": net_a_payer,
        "annee_conges": annee,
        "conges_quota": quota,
        "conges_pris": conges_pris,
        "conges_restants": (quota - conges_pris) if quota is not None else None,
    }
