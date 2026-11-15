"""TOC / Figura 1: PMC Open Access (AWS) y pies de Figura 1 en manuscritos aceptados. Sin red."""
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "enrich_publications_images", Path(__file__).resolve().parents[1] / "scripts/enrich_publications.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

JATS = b"""<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
<abstract><p>Text.</p></abstract>
<abstract abstract-type="toc"><p>TOC</p><graphic xlink:href="d6ee05477c-ga.webp"/></abstract>
</article-meta></front><body>
<fig id="f2"><label>Fig. 2</label><graphic xlink:href="d6ee05477c-f2.webp"/></fig>
<fig id="f1"><label>Fig. 1</label><caption><p>Outdoor platform.</p></caption>
<graphic content-type="thumb" xlink:href="d6ee05477c-f1.gif"/>
<graphic xlink:href="d6ee05477c-f1.webp"/></fig>
</body></article>"""


def png(width=600, height=400):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 90)).save(buf, format="PNG")
    return buf.getvalue()


class FigureOneCaptionTests(unittest.TestCase):
    def test_caption_lines_are_recognised(self):
        for text in ("Figure 1: Outdoor platform and measurement chain.",   # EES (repositorio)
                     "12 Figure 1. Synthetic approach for CsPbI3",          # manuscrito con nº de línea
                     "a) b) Figure 1. a) Comparative XRD pattern",          # letras de panel unidas
                     "Fig. 1 Schematic of the device", "Fig. 1 (a) Device stack",
                     "FIGURE 1. Device", "Figure 1"):
            self.assertTrue(module.FIGURE_ONE_LINE.search(text), text)

    def test_body_text_is_not_a_caption(self):
        for text in ("Figure 1b shows the open-cavity holder", "Figure 1 shows the device",
                     "Figure 10. Stability", "Fig. 12 Schematic", "as shown in Figure 1.",
                     "pattern, showing a continuous drop in PCE over time, Figure 1a."):
            self.assertFalse(module.FIGURE_ONE_LINE.search(text), text)

    def test_figure_one_found_after_page_seven_with_line_numbers(self):
        import fitz
        doc = fitz.open()
        for i in range(9):
            page = doc.new_page()
            page.insert_text((72, 100), f"{i + 3} Body text of the accepted manuscript, page {i + 1}.")
        page = doc[8]
        page.insert_image(fitz.Rect(80, 150, 520, 450), stream=png())
        page.insert_text((72, 470), "12 Figure 1. Synthetic approach for CsPbI3 nanocomposites.")
        pdf = doc.tobytes()
        result = module.first_figure_from_pdf(pdf)
        self.assertTrue(result and result[:8] == b"\x89PNG\r\n\x1a\n")


class PmcImagesTests(unittest.TestCase):
    def test_jats_toc_and_figure_one(self):
        self.assertEqual(module.jats_toc_and_figure_one(JATS),
                         ("d6ee05477c-ga.webp", "d6ee05477c-f1.webp"))

    def test_pmc_publisher_images_prefers_latest_version_and_full_size(self):
        listing = (b"<ListBucketResult>"
                   b"<Key>PMC13651458.1/PMC13651458.1.xml</Key>"
                   b"<Key>PMC13651458.2/PMC13651458.2.xml</Key>"
                   b"<Key>PMC13651458.2/d6ee05477c-f1.gif</Key>"
                   b"<Key>PMC13651458.2/d6ee05477c-f1.webp</Key>"
                   b"<Key>PMC13651458.2/d6ee05477c-ga.webp</Key>"
                   b"</ListBucketResult>")
        s3 = module.PMC_OA_S3
        responses = {
            s3 + "?list-type=2&prefix=PMC13651458.": (listing, "", "application/xml"),
            s3 + "PMC13651458.2/PMC13651458.2.xml": (JATS, "", "application/xml"),
            s3 + "PMC13651458.2/d6ee05477c-ga.webp": (b"TOC", "", "binary/octet-stream"),
            s3 + "PMC13651458.2/d6ee05477c-f1.webp": (b"FIG1", "", "binary/octet-stream"),
        }
        with patch.object(module, "europe_pmc_open_access_id", return_value="PMC13651458"), \
             patch.object(module, "request_url", side_effect=lambda url, *a, **k: responses.get(url)):
            found = module.pmc_publisher_images("10.1039/d6ee05477c")
        self.assertEqual([(b, t) for b, _u, t in found],
                         [(b"TOC", "graphical-abstract"), (b"FIG1", "figure-1")])
        self.assertTrue(found[0][1].endswith("PMC13651458.2/d6ee05477c-ga.webp"))

    def test_not_in_pmc_returns_nothing(self):
        with patch.object(module, "europe_pmc_open_access_id", return_value=None):
            self.assertEqual(module.pmc_publisher_images("10.1039/d6qm00873a"), [])

    def enrich(self, pmc_images, pdf_figure=b"PDF-FIG1", prev=None, license="http://creativecommons.org/licenses/by/3.0/"):
        rec = {"doi": "10.1039/d6ee05477c", "projects": [], "image": None,
               "license": license, "openAccess": None, "fundingEvidence": [],
               "publicationDate": "2026-10-06", "featured": {"summary": "x", "summary_en": "x"}}
        prev = prev or {"checked": module.date.today().isoformat(), "fundingStatus": "text-checked",
                        "fundingMatcherVersion": module.FUNDING_MATCHER_VERSION, "fundingEvidence": []}
        with patch.object(module, "KEY", ""), patch.object(module, "WILEY_TDM_TOKEN", ""), \
             patch.object(module, "openalex_work", return_value={}), \
             patch.object(module, "download_publisher_page", return_value=None), \
             patch.object(module, "accessible_pdf_candidates", return_value=["https://repo.example/a.pdf"]), \
             patch.object(module, "request_url", return_value=(b"%PDF-fake", "https://repo.example/a.pdf", "application/pdf")), \
             patch.object(module, "pmc_publisher_images", return_value=pmc_images) as pmc, \
             patch.object(module, "toc_graphic_from_pdf", return_value=None), \
             patch.object(module, "first_figure_from_pdf", return_value=pdf_figure), \
             patch.object(module, "extract_image_to_webp", side_effect=lambda blob, path: blob != b"TINY"):
            out, audit = module.enrich_entry(rec, [], prev, {"publications": {}})
        return out, audit, pmc

    def test_pmc_toc_beats_pdf_figure_one(self):
        out, audit, _ = self.enrich([(b"TOC", "https://s3/ga.webp", "graphical-abstract"),
                                     (b"FIG1", "https://s3/f1.webp", "figure-1")])
        self.assertEqual(out["imageType"], "graphical-abstract")
        self.assertEqual(out["imageSource"], "https://s3/ga.webp")
        self.assertEqual(audit["imageMatcherVersion"], module.IMAGE_MATCHER_VERSION)

    def test_pmc_figure_one_beats_pdf_render(self):
        out, _, _ = self.enrich([(b"FIG1", "https://s3/f1.webp", "figure-1")])
        self.assertEqual(out["imageSource"], "https://s3/f1.webp")

    def test_unusable_image_falls_back_to_next_source(self):
        out, _, _ = self.enrich([(b"TINY", "https://s3/ga.webp", "graphical-abstract")])
        self.assertEqual(out["imageType"], "figure-1")
        self.assertEqual(out["imageSource"], "https://repo.example/a.pdf")

    def test_without_reuse_licence_nothing_is_fetched(self):
        out, _, pmc = self.enrich([(b"TOC", "u", "graphical-abstract")], license=None)
        self.assertIsNone(out.get("image"))
        pmc.assert_not_called()

    def test_existing_figure_one_is_rechecked_for_toc_after_upgrade(self):
        prev = {"checked": module.date.today().isoformat(), "fundingStatus": "text-checked",
                "fundingMatcherVersion": module.FUNDING_MATCHER_VERSION, "fundingEvidence": [],
                "imageMatcherVersion": 6,
                "image": {"url": "old", "source": "pdf", "type": "figure-1", "license": "cc-by"}}
        out, _, _ = self.enrich([(b"TOC", "https://s3/ga.webp", "graphical-abstract")], prev=prev)
        self.assertEqual(out["imageType"], "graphical-abstract")


if __name__ == "__main__":
    unittest.main()
