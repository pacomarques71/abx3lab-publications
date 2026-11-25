"""Imágenes de artículos de Wiley con licencia estándar y su aviso de copyright. Sin red."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "enrich_publications_wiley", Path(__file__).resolve().parents[1] / "scripts/enrich_publications.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

BRONZE = {"best_oa_location": {"license": None}, "primary_location": {"license": None}}


def pdf_with(text):
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Research Article")
    doc.new_page().insert_text((72, 760), text)
    blob = doc.tobytes()
    doc.close()
    return blob


class WileyStandardLicenceTests(unittest.TestCase):
    def test_wiley_without_cc_licence_is_standard(self):
        self.assertTrue(module.wiley_standard_terms("10.1002/adfm.79536", {"license": None}, BRONZE))

    def test_wiley_with_cc_nc_licence_is_not_standard(self):
        rec = {"license": "http://creativecommons.org/licenses/by-nc/4.0/"}
        self.assertFalse(module.wiley_standard_terms("10.1002/lpor.202401920", rec, {}))

    def test_other_publishers_are_not_affected(self):
        self.assertFalse(module.wiley_standard_terms("10.1021/acsenergylett.5c04010", {"license": None}, {}))
        self.assertFalse(module.wiley_standard_terms("10.1039/d6qm00873a", {"license": None}, {}))

    def test_copyright_read_from_pdf(self):
        pdf = pdf_with("Adv. Funct. Mater. 2026, e79536   © 2026 Wiley-VCH GmbH")
        self.assertEqual(module.wiley_copyright("10.1002/adfm.79536", {}, pdf),
                         "© 2026 Wiley‑VCH GmbH")

    def test_copyright_periodicals_from_pdf(self):
        pdf = pdf_with("© 2025 Wiley Periodicals LLC.")
        self.assertEqual(module.wiley_copyright("10.1002/ente.1", {}, pdf),
                         "© 2025 Wiley Periodicals LLC")

    def test_copyright_fallback_uses_online_year_and_journal(self):
        rec = {"onlinePublicationDate": "2025-09-30", "publicationDate": "2026-01-01"}
        self.assertEqual(module.wiley_copyright("10.1002/aenm.202503291", rec, None),
                         "© 2025 Wiley‑VCH GmbH")
        self.assertEqual(module.wiley_copyright("10.1002/xyz.1", {"year": 2026}, None),
                         "© 2026 Wiley")

    def enrich(self, doi, license=None, work=BRONZE, pdf_figure=b"PDF-FIG1"):
        rec = {"doi": doi, "projects": [], "image": None, "license": license,
               "openAccess": None, "fundingEvidence": [], "publicationDate": "2026-11-20",
               "onlinePublicationDate": "2026-11-20",
               "featured": {"summary": "x", "summary_en": "x"}}
        prev = {"checked": module.date.today().isoformat(), "fundingStatus": "text-checked",
                "fundingMatcherVersion": module.FUNDING_MATCHER_VERSION, "fundingEvidence": []}
        with patch.object(module, "KEY", ""), patch.object(module, "WILEY_TDM_TOKEN", ""), \
             patch.object(module, "openalex_work", return_value=work), \
             patch.object(module, "download_publisher_page", return_value=None), \
             patch.object(module, "accessible_pdf_candidates", return_value=["https://repo.example/a.pdf"]), \
             patch.object(module, "request_url", return_value=(b"%PDF-fake", "https://repo.example/a.pdf", "application/pdf")), \
             patch.object(module, "pmc_publisher_images", return_value=[]), \
             patch.object(module, "toc_graphic_from_pdf", return_value=None), \
             patch.object(module, "first_figure_from_pdf", return_value=pdf_figure), \
             patch.object(module, "extract_image_to_webp", return_value=True):
            return module.enrich_entry(rec, [], prev, {"publications": {}})

    def test_wiley_standard_article_gets_image_and_credit(self):
        out, audit = self.enrich("10.1002/adfm.79536")
        self.assertEqual(out["imageType"], "figure-1")
        self.assertEqual(out["imageLicense"], module.WILEY_STANDARD_LICENSE)
        self.assertEqual(out["imageCredit"], "© 2026 Wiley‑VCH GmbH")
        self.assertEqual(audit["image"]["credit"], "© 2026 Wiley‑VCH GmbH")

    def test_cc_by_article_has_no_copyright_credit(self):
        out, _ = self.enrich("10.1002/advs.78211", license="http://creativecommons.org/licenses/by/4.0/")
        self.assertTrue(out["image"])
        self.assertNotIn("imageCredit", out)

    def test_closed_article_of_other_publisher_still_has_no_image(self):
        out, _ = self.enrich("10.1039/d6qm00873a")
        self.assertIsNone(out.get("image"))


class TallVectorFigureTests(unittest.TestCase):
    def tall_vector_pdf(self):
        """Página A4 a dos columnas: párrafo arriba, figura vectorial de 380 pt y pie."""
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        para = ("Body text of the article that explains the experiment in detail. " * 8).strip()
        page.insert_textbox(fitz.Rect(40, 60, 290, 170), para, fontsize=8)
        for i in range(40):  # figura vectorial: barras y líneas entre y=190 y y=570
            y = 190 + i * 9.5
            page.draw_rect(fitz.Rect(50, y, 60 + i * 5, y + 6), color=(0.6, 0, 0), fill=(0.9, 0.6, 0.1))
        page.draw_line((45, 192), (280, 192), color=(0, 0, 0))
        page.insert_text((60, 200), "a)", fontsize=9)
        page.insert_text((40, 590), "Figure 1. Complexation energies in DMF and DMSO.", fontsize=8)
        blob = doc.tobytes()
        doc.close()
        return blob

    def test_tall_vector_figure_is_rendered_whole(self):
        from PIL import Image
        import io
        png = module.first_figure_from_pdf(self.tall_vector_pdf())
        self.assertIsNotNone(png)
        with Image.open(io.BytesIO(png)) as im:
            # Renderizado a 2x: la figura (≈380 pt) debe caber entera, no solo 225 pt.
            self.assertGreater(im.height, 2 * 360)


class ManualImageCreditTests(unittest.TestCase):
    @patch.object(module, "request_url", return_value=None)
    @patch.object(module, "download_publisher_page", return_value=None)
    @patch.object(module, "openalex_work", return_value={})
    def test_manual_image_credit_is_published(self, *_):
        rec = {"doi": "10.1039/d6qm00873a", "projects": [], "image": None, "license": None,
               "openAccess": None, "fundingEvidence": [], "publicationDate": "2026-10-28",
               "featured": {"summary": "x", "summary_en": "x"}}
        prev = {"checked": module.date.today().isoformat(), "fundingStatus": "text-checked",
                "fundingMatcherVersion": module.FUNDING_MATCHER_VERSION, "fundingEvidence": []}
        extras = {"publications": {"10.1039/d6qm00873a": {
            "image": "https://example.org/toc.webp",
            "imageCredit": "\u00a9 The Royal Society of Chemistry and the Chinese Chemical Society 2026"}}}
        out, _ = module.enrich_entry(rec, [], prev, extras)
        self.assertEqual(out["image"], "https://example.org/toc.webp")
        self.assertIn("Royal Society of Chemistry", out["imageCredit"])


if __name__ == "__main__":
    unittest.main()
