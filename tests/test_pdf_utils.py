def test_logo_flowable_retourne_une_image_proportionnee(app):
    from app.pdf_utils import logo_flowable

    with app.app_context():
        logo = logo_flowable(largeur_mm=35)
        assert logo is not None
        # Largeur fixée à 35mm (en points ReportLab, 1mm ≈ 2.8346pt)
        assert 95 < logo.drawWidth < 100
        assert logo.drawHeight > 0
