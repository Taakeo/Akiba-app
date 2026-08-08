import sys
import types

import pytest


def _fake_win32print(comportement="ok"):
    """Simule le module win32print (Windows uniquement, non testable "en
    vrai" en CI) : enregistre les appels pour vérifier la séquence
    Open/StartDoc/StartPage/Write/EndPage/EndDoc/Close, ou simule un échec
    selon `comportement`."""
    module = types.SimpleNamespace()
    appels = []

    if comportement == "printer_introuvable":
        def open_printer(nom):
            raise RuntimeError("imprimante introuvable")
        module.OpenPrinter = open_printer
        module.appels = appels
        return module

    def open_printer(nom):
        appels.append(("OpenPrinter", nom))
        return "handle-fake"

    def start_doc(handle, level, doc_info):
        appels.append(("StartDocPrinter", handle, doc_info))
        return 1

    def start_page(handle):
        appels.append(("StartPagePrinter", handle))

    def write_printer(handle, data):
        appels.append(("WritePrinter", handle, data))
        if comportement == "write_echoue":
            raise RuntimeError("erreur d'écriture")

    def end_page(handle):
        appels.append(("EndPagePrinter", handle))

    def end_doc(handle):
        appels.append(("EndDocPrinter", handle))

    def close_printer(handle):
        appels.append(("ClosePrinter", handle))

    module.OpenPrinter = open_printer
    module.StartDocPrinter = start_doc
    module.StartPagePrinter = start_page
    module.WritePrinter = write_printer
    module.EndPagePrinter = end_page
    module.EndDocPrinter = end_doc
    module.ClosePrinter = close_printer
    module.appels = appels
    return module


def test_ouvrir_tiroir_envoie_la_commande_esc_pos(monkeypatch):
    from app.caisse.printer import COMMANDE_OUVERTURE_TIROIR, ouvrir_tiroir

    fake = _fake_win32print()
    monkeypatch.setitem(sys.modules, "win32print", fake)

    ouvrir_tiroir("POS-80")

    noms_appels = [a[0] for a in fake.appels]
    assert noms_appels == [
        "OpenPrinter",
        "StartDocPrinter",
        "StartPagePrinter",
        "WritePrinter",
        "EndPagePrinter",
        "EndDocPrinter",
        "ClosePrinter",
    ]
    write_call = next(a for a in fake.appels if a[0] == "WritePrinter")
    assert write_call[2] == COMMANDE_OUVERTURE_TIROIR


def test_ouvrir_tiroir_imprimante_introuvable_leve_erreur_claire(monkeypatch):
    from app.caisse.printer import ImprimanteError, ouvrir_tiroir

    fake = _fake_win32print("printer_introuvable")
    monkeypatch.setitem(sys.modules, "win32print", fake)

    with pytest.raises(ImprimanteError) as exc_info:
        ouvrir_tiroir("Imprimante Inexistante")

    assert "Imprimante Inexistante" in str(exc_info.value)


def test_ouvrir_tiroir_echec_ecriture_ferme_quand_meme_limprimante(monkeypatch):
    from app.caisse.printer import ImprimanteError, ouvrir_tiroir

    fake = _fake_win32print("write_echoue")
    monkeypatch.setitem(sys.modules, "win32print", fake)

    with pytest.raises(ImprimanteError):
        ouvrir_tiroir("POS-80")

    # Même en cas d'échec d'écriture, ClosePrinter doit avoir été appelé
    # (finally) pour ne pas laisser le handle ouvert.
    assert ("ClosePrinter", "handle-fake") in fake.appels
