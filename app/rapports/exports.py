import io
import re
import unicodedata

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..pdf_utils import logo_flowable

# NOTE : gabarit générique (date / regroupement / quantité / montant). Le
# modèle comptable exact utilisé par Akiba (§11.3 spec) n'est pas disponible
# dans ce dépôt — à ajuster une fois le fichier de référence du comptable
# fourni, pour que l'export s'insère directement dans son classeur existant.


def _entete(ws, titre, date_debut, date_fin):
    ws["A1"] = "AKIBA APP"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = titre
    ws["A3"] = f"Période : {date_debut.isoformat()} au {date_fin.isoformat()}"


def export_ventes_xlsx(lignes, total, date_debut, date_fin, group_by):
    wb = Workbook()
    ws = wb.active
    ws.title = "Ventes"
    _entete(ws, "Rapport des ventes", date_debut, date_fin)

    ws.append([])
    ws.append([group_by.capitalize(), "Quantité", "Montant"])
    for cell in ws[5]:
        cell.font = Font(bold=True)

    for ligne in lignes:
        ws.append([ligne["libelle"], ligne["quantite"], ligne["total"]])

    ws.append(["TOTAL", "", total])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 15

    return _vers_bytesio(wb)


def export_achats_xlsx(lignes, total, date_debut, date_fin, group_by):
    wb = Workbook()
    ws = wb.active
    ws.title = "Achats"
    _entete(ws, "Rapport des achats", date_debut, date_fin)

    ws.append([])
    ws.append([group_by.capitalize(), "Nombre d'achats", "Montant"])
    for cell in ws[5]:
        cell.font = Font(bold=True)

    for ligne in lignes:
        ws.append([ligne["libelle"], ligne["nombre"], ligne["total"]])

    ws.append(["TOTAL", "", total])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 15

    return _vers_bytesio(wb)


def _cle_excel(texte, cles_existantes):
    """Convertit un libellé en identifiant valide pour une plage nommée Excel
    (lettres/chiffres/underscore uniquement, ne commence jamais par un
    chiffre), en évitant les collisions entre libellés différents qui se
    ressembleraient une fois nettoyés — même principe que
    admin/routes_catalogue.py::_slugifier, mais sans dépendance à la base
    (ce module ne fait que mettre en forme des données déjà requêtées)."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    cle = re.sub(r"[^A-Za-z0-9_]+", "_", sans_accents).strip("_") or "Item"
    if cle[0].isdigit():
        cle = "N" + cle
    base, suffixe = cle, 2
    while cle in cles_existantes:
        cle = f"{base}_{suffixe}"
        suffixe += 1
    cles_existantes.add(cle)
    return cle


def _construire_feuille_listes(wb, taxonomie):
    """Feuille technique cachée "Listes" : hiérarchie Poste -> Catégorie ->
    Sous-catégorie réellement en base (pas l'ancienne structure École/
    Dispensaire du classeur de référence de l'association), et les plages
    nommées Excel qui en découlent — reproduit le mécanisme de listes
    déroulantes en cascade (INDIRECT + plages nommées) du fichier fourni,
    avec des données toujours à jour plutôt que figées."""
    ws = wb.create_sheet("Listes")
    cles = set()

    ws.cell(row=1, column=1, value="Poste")
    ws.cell(row=1, column=2, value="ClePoste")
    cle_poste = {}
    for i, poste in enumerate(taxonomie["postes"]):
        cle_poste[poste] = _cle_excel(poste, cles)
        ws.cell(row=i + 2, column=1, value=poste)
        ws.cell(row=i + 2, column=2, value=cle_poste[poste])
    if taxonomie["postes"]:
        wb.defined_names["ListePostes"] = DefinedName(
            "ListePostes", attr_text=f"'Listes'!$A$2:$A${len(taxonomie['postes']) + 1}"
        )

    col = 4  # colonne D : une colonne par poste, liste de ses catégories
    for poste in taxonomie["postes"]:
        categories = taxonomie["categories_par_poste"].get(poste, [])
        if not categories:
            continue
        lettre = get_column_letter(col)
        nom_plage = f"Cat_{cle_poste[poste]}"
        ws.cell(row=1, column=col, value=nom_plage)
        for i, nom in enumerate(categories):
            ws.cell(row=i + 2, column=col, value=nom)
        wb.defined_names[nom_plage] = DefinedName(
            nom_plage, attr_text=f"'Listes'!${lettre}$2:${lettre}${len(categories) + 1}"
        )
        col += 1

    col += 1  # colonne d'espacement

    # Table de correspondance (Poste|Catégorie) -> clé technique — nécessaire
    # car deux postes différents peuvent avoir une catégorie de même nom
    # (Categorie.__table_args__ : unicité sur poste_id+name, pas sur name seul).
    col_table = col
    ws.cell(row=1, column=col, value="ClefPosteCategorie")
    ws.cell(row=1, column=col + 1, value="CleCategorie")
    cle_categorie = {}
    ligne = 2
    for poste in taxonomie["postes"]:
        for nom in taxonomie["categories_par_poste"].get(poste, []):
            cle_categorie[(poste, nom)] = _cle_excel(f"{poste}_{nom}", cles)
            ws.cell(row=ligne, column=col, value=f"{poste}|{nom}")
            ws.cell(row=ligne, column=col + 1, value=cle_categorie[(poste, nom)])
            ligne += 1
    if ligne > 2:
        l1, l2 = get_column_letter(col_table), get_column_letter(col_table + 1)
        wb.defined_names["TableCategories"] = DefinedName(
            "TableCategories", attr_text=f"'Listes'!${l1}$2:${l2}${ligne - 1}"
        )
    col = col_table + 3  # 2 colonnes de la table + 1 d'espacement

    for poste in taxonomie["postes"]:
        for nom in taxonomie["categories_par_poste"].get(poste, []):
            sous = taxonomie["sous_categories_par_categorie"].get((poste, nom), [])
            if not sous:
                continue
            lettre = get_column_letter(col)
            nom_plage = f"Sc_{cle_categorie[(poste, nom)]}"
            ws.cell(row=1, column=col, value=nom_plage)
            for i, sc_nom in enumerate(sous):
                ws.cell(row=i + 2, column=col, value=sc_nom)
            wb.defined_names[nom_plage] = DefinedName(
                nom_plage, attr_text=f"'Listes'!${lettre}$2:${lettre}${len(sous) + 1}"
            )
            col += 1

    ws.sheet_state = "hidden"  # feuille technique, jamais destinée à être modifiée à la main


# Lignes de gabarit laissées vierges après les données déjà enregistrées, avec
# les mêmes listes déroulantes en cascade déjà en place — pour que le fichier
# exporté reste un vrai classeur de saisie continuable, comme l'original,
# et pas seulement un instantané figé du jour de l'export.
LIGNES_GABARIT_VIERGES = 200


def export_total_xlsx(lignes, bilan, date_debut, date_fin, taxonomie):
    """Classeur 3 feuilles calqué sur le fichier comptable de référence de
    l'association (Outils/Essai de compte pour akiba yanis.xlsx) : "Saisie"
    (grand livre détaillé, avec les mêmes listes déroulantes en cascade
    Poste -> Catégorie -> Sous-catégorie que l'original, reconstruites à
    partir des données réelles de l'appli plutôt que de l'ancienne structure
    École/Dispensaire), "BILAN" (totaux par poste + répartition
    poste -> catégorie, en valeurs figées à l'export — pas de formules
    vivantes, par choix explicite) et "Listes" (feuille technique cachée,
    support des listes déroulantes)."""
    wb = Workbook()

    ws_saisie = wb.active
    ws_saisie.title = "Saisie"
    _entete(ws_saisie, "Rapport total — Saisie", date_debut, date_fin)
    ws_saisie.append([])
    ws_saisie.append(["Mois", "Poste", "Catégorie", "Sous-catégorie", "Note", "Recettes", "Dépenses", "Projet"])
    for cell in ws_saisie[5]:
        cell.font = Font(bold=True)

    premiere_ligne = 6
    for ligne in lignes:
        ws_saisie.append(
            [
                ligne["mois"],
                ligne["poste"],
                ligne["categorie"],
                ligne["sous_categorie"],
                ligne["note"],
                ligne["recette"] or "",
                ligne["depense"] or "",
                ligne["projet"],
            ]
        )
    derniere_ligne_donnees = premiere_ligne + len(lignes) - 1 if lignes else premiere_ligne - 1
    derniere_ligne = derniere_ligne_donnees + LIGNES_GABARIT_VIERGES

    for lettre, largeur in zip("ABCDEFGH", [10, 22, 20, 20, 35, 12, 12, 18]):
        ws_saisie.column_dimensions[lettre].width = largeur

    _construire_feuille_listes(wb, taxonomie)

    # --- Listes déroulantes en cascade (Poste -> Catégorie -> Sous-catégorie),
    # colonnes techniques cachées N-Q calculant la plage nommée à utiliser pour
    # chaque ligne — même mécanisme INDIRECT() que le fichier de référence,
    # mais sourcé sur des plages nommées reconstruites dynamiquement (§ ci-
    # dessus) plutôt que sur une structure figée dans le classeur.
    if taxonomie["postes"] and derniere_ligne >= premiere_ligne:
        for r in range(premiere_ligne, derniere_ligne + 1):
            ws_saisie.cell(row=r, column=14, value=f'=IFERROR(VLOOKUP(B{r},Listes!$A:$B,2,FALSE),"")')
            ws_saisie.cell(row=r, column=15, value=f'=IF(N{r}="","","Cat_"&N{r})')
            ws_saisie.cell(
                row=r, column=16, value=f'=IFERROR(VLOOKUP(B{r}&"|"&C{r},TableCategories,2,FALSE),"")'
            )
            ws_saisie.cell(row=r, column=17, value=f'=IF(P{r}="","","Sc_"&P{r})')
        for lettre in ("N", "O", "P", "Q"):
            ws_saisie.column_dimensions[lettre].hidden = True

        dv_poste = DataValidation(type="list", formula1="ListePostes", allow_blank=True)
        ws_saisie.add_data_validation(dv_poste)
        dv_poste.add(f"B{premiere_ligne}:B{derniere_ligne}")

        dv_categorie = DataValidation(type="list", formula1=f"INDIRECT(O{premiere_ligne})", allow_blank=True)
        ws_saisie.add_data_validation(dv_categorie)
        dv_categorie.add(f"C{premiere_ligne}:C{derniere_ligne}")

        dv_sous_categorie = DataValidation(type="list", formula1=f"INDIRECT(Q{premiere_ligne})", allow_blank=True)
        ws_saisie.add_data_validation(dv_sous_categorie)
        dv_sous_categorie.add(f"D{premiere_ligne}:D{derniere_ligne}")

    # --- Petit outil de recherche Poste + Catégorie (confirmé utile par
    # l'utilisateur) — même principe que le "Détail affectation" du fichier de
    # référence, colonnes I-J en haut de la feuille.
    if taxonomie["postes"]:
        ws_saisie["I1"] = "Recherche Poste + Catégorie"
        ws_saisie["I1"].font = Font(bold=True)
        ws_saisie["I2"], ws_saisie["I3"] = "Poste", "Catégorie"
        ws_saisie["I4"], ws_saisie["I5"], ws_saisie["I6"] = "Recettes", "Dépenses", "Solde"
        ws_saisie["J4"] = "=SUMIFS(F:F,B:B,J2,C:C,J3)"
        ws_saisie["J5"] = "=SUMIFS(G:G,B:B,J2,C:C,J3)"
        ws_saisie["J6"] = "=J4-J5"
        ws_saisie.column_dimensions["I"].width = 12

        dv_widget_poste = DataValidation(type="list", formula1="ListePostes", allow_blank=True)
        ws_saisie.add_data_validation(dv_widget_poste)
        dv_widget_poste.add("J2")

        dv_widget_categorie = DataValidation(
            type="list",
            formula1='INDIRECT("Cat_"&VLOOKUP(J2,Listes!$A:$B,2,FALSE))',
            allow_blank=True,
        )
        ws_saisie.add_data_validation(dv_widget_categorie)
        dv_widget_categorie.add("J3")

    ws_bilan = wb.create_sheet("BILAN")
    _entete(ws_bilan, "Rapport total — BILAN", date_debut, date_fin)
    ws_bilan.append([])
    ws_bilan.append(["Poste", "Recettes", "Dépenses", "Solde"])
    for cell in ws_bilan[5]:
        cell.font = Font(bold=True)
    for p in bilan["postes"]:
        ws_bilan.append([p["poste"], p["recettes"], p["depenses"], p["solde"]])
    ws_bilan.append(["TOTAL", bilan["total_recettes"], bilan["total_depenses"], bilan["solde"]])
    for cell in ws_bilan[ws_bilan.max_row]:
        cell.font = Font(bold=True)

    ws_bilan.append([])
    ws_bilan.append(["AFFECTATIONS PAR POSTE"])
    ws_bilan[ws_bilan.max_row][0].font = Font(bold=True)
    ws_bilan.append(["Poste", "Catégorie", "Recettes", "Dépenses", "Solde"])
    for cell in ws_bilan[ws_bilan.max_row]:
        cell.font = Font(bold=True)
    for c in bilan["categories"]:
        ws_bilan.append([c["poste"], c["categorie"], c["recettes"], c["depenses"], c["solde"]])

    for lettre, largeur in zip("ABCDE", [22, 22, 14, 14, 14]):
        ws_bilan.column_dimensions[lettre].width = largeur

    return _vers_bytesio(wb)


def _vers_bytesio(wb):
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def _table_pdf(titre, date_debut, date_fin, entetes, lignes_texte, total_texte):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()

    logo = logo_flowable(largeur_mm=30)
    elements = [logo] if logo is not None else [Paragraph("AKIBA APP", styles["Title"])]
    elements += [
        Paragraph(titre, styles["Heading2"]),
        Paragraph(f"Période : {date_debut.isoformat()} au {date_fin.isoformat()}", styles["Normal"]),
        Spacer(1, 16),
    ]

    data = [entetes, *lignes_texte, total_texte]
    table = Table(data, hAlign="LEFT", colWidths=[220, 120, 120][: len(entetes)])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0e7df")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer


def export_ventes_pdf(lignes, total, date_debut, date_fin, group_by):
    lignes_texte = [[l["libelle"], str(l["quantite"]), f"{l['total']:,}".replace(",", " ")] for l in lignes]
    total_texte = ["TOTAL", "", f"{total:,}".replace(",", " ")]
    return _table_pdf(
        "Rapport des ventes",
        date_debut,
        date_fin,
        [group_by.capitalize(), "Quantité", "Montant"],
        lignes_texte,
        total_texte,
    )


def export_achats_pdf(lignes, total, date_debut, date_fin, group_by):
    lignes_texte = [[l["libelle"], str(l["nombre"]), f"{l['total']:,}".replace(",", " ")] for l in lignes]
    total_texte = ["TOTAL", "", f"{total:,}".replace(",", " ")]
    return _table_pdf(
        "Rapport des achats",
        date_debut,
        date_fin,
        [group_by.capitalize(), "Nombre d'achats", "Montant"],
        lignes_texte,
        total_texte,
    )
