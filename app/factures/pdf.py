import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..pdf_utils import logo_flowable


def _montant(n):
    return f"{n:,}".replace(",", " ")


def generer_facture_pdf(facture):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()

    entete_texte = [Paragraph(facture.emetteur_raison_sociale or "AKIBA", styles["Title"])]

    coordonnees = []
    if facture.emetteur_adresse:
        coordonnees.append(facture.emetteur_adresse.replace("\n", "<br/>"))
    if facture.emetteur_telephone:
        coordonnees.append(f"Tél. {facture.emetteur_telephone}")
    if facture.emetteur_email:
        coordonnees.append(facture.emetteur_email)
    mentions = []
    if facture.emetteur_nif:
        mentions.append(f"NIF {facture.emetteur_nif}")
    if facture.emetteur_stat:
        mentions.append(f"STAT {facture.emetteur_stat}")
    if facture.emetteur_rcs:
        mentions.append(f"RCS {facture.emetteur_rcs}")

    for ligne in coordonnees:
        entete_texte.append(Paragraph(ligne, styles["Normal"]))
    if mentions:
        entete_texte.append(Paragraph(" — ".join(mentions), styles["Normal"]))

    logo = logo_flowable()
    if logo is not None:
        entete = Table([[logo, entete_texte]], colWidths=[45 * mm, 125 * mm])
        entete.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        elements = [entete]
    else:
        elements = entete_texte

    elements.append(Spacer(1, 16))
    elements.append(Paragraph(f"FACTURE N° {facture.numero}", styles["Heading1"]))
    elements.append(Paragraph(f"Date d'émission : {facture.date_emission.strftime('%d/%m/%Y')}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Facturé à :", styles["Heading3"]))
    elements.append(Paragraph(facture.client_nom, styles["Normal"]))
    elements.append(Paragraph(facture.client_adresse.replace("\n", "<br/>"), styles["Normal"]))
    elements.append(Spacer(1, 16))

    data = [["Ticket", "Article", "Qté", "Prix unitaire", "Total"]]
    for vente in facture.ventes:
        for ligne in vente.lignes:
            data.append(
                [
                    f"#{vente.id}",
                    ligne.produit_nom + (" (offert)" if ligne.offert else ""),
                    str(ligne.quantite),
                    _montant(ligne.prix_unitaire),
                    _montant(ligne.total_ligne),
                ]
            )

    table = Table(data, hAlign="LEFT", colWidths=[45, 210, 35, 80, 80])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0e7df")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 12))

    totaux = [["Sous-total", _montant(facture.sous_total)]]
    if facture.remise:
        totaux.append(["Remise", f"-{_montant(facture.remise)}"])
    totaux.append(["TOTAL", _montant(facture.total)])
    totaux_table = Table(totaux, hAlign="RIGHT", colWidths=[100, 100])
    totaux_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    elements.append(totaux_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
