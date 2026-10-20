"""Regression tests for autonomous grant / image enrichment. No network calls."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "enrich_publications", Path(__file__).resolve().parents[1] / "scripts/enrich_publications.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PROJECTS = [
    {"key": "hepaflex", "grants": ["101122345"]},
    {"key": "cns2023", "grants": ["CNS2023-144270"]},
    {"key": "flexwin", "grants": ["PID2023-151880OB-C31"]},
    {"key": "inkflex", "grants": ["PID2023-151880OB-C32"]},
    {"key": "esgent", "grants": ["ESGENT/010/2024"]},
]


class FundingTests(unittest.TestCase):
    def test_wiley_biedot_regression_five_grants(self):
        html = b"""<html><h2>Funding</h2><p>
        Projects 101122345, PID2023-151880OB-C31, PID2023-151880OB-C32,
        CNS2023-144270 and ESGENT 010/2024 funded this work.
        </p><h2>References</h2><p>unrelated</p></html>"""
        text = module.section_text_from_html(html)
        self.assertEqual(set(module.grants_in_text(text, PROJECTS)), set(p["key"] for p in PROJECTS))

    def test_wiley_memristor_regression(self):
        html = b"<h2>Acknowledgements</h2><p>CNS2023-144270 and ESGENT/010/2024.</p><h2>References</h2>"
        found = module.grants_in_text(module.section_text_from_html(html), PROJECTS)
        self.assertEqual(set(found), {"cns2023", "esgent"})

    def test_tei_funding(self):
        xml = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><back><div type="acknowledgement"><head>Acknowledgements</head><p>Grant 101122345.</p></div></back></text></TEI>'
        self.assertEqual(set(module.grants_in_text(module.text_from_tei(xml), PROJECTS)), {"hepaflex"})

    def test_no_false_numeric_prefix(self):
        self.assertFalse(module.grants_in_text("Contract 91011223456", PROJECTS))

    def test_grant_survives_year_after_punctuation(self):
        p = [{"key": "cns2023", "grants": ["CNS2023-144270"]},
             {"key": "esgent", "grants": ["ESGENT/010/2024"]}]
        text = ("This work was funded by CNS2023-144270 (2026), "
                "and ESGENT/010/2024 (2025).")
        self.assertEqual(set(module.grants_in_text(text, p)), {"cns2023", "esgent"})

    def test_numeric_grant_survives_following_year(self):
        p = [{"key": "hepaflex", "grants": ["101122345"]}]
        self.assertEqual(module.grants_in_text("Grant 101122345 (2024)", p),
                         {"hepaflex": "101122345"})

    def test_grant_does_not_match_a_longer_identifier(self):
        p = [{"key": "cns2023", "grants": ["CNS2023-144270"]},
             {"key": "hepaflex", "grants": ["101122345"]}]
        self.assertEqual(module.grants_in_text(
            "CNS2023-1442701 1011223456", p), {})

    def test_pdf_font_letter_spacing_for_gent_grant(self):
        p = [{"key":"esgent", "grants":["ESGENT/010/2024"]}]
        text = "Funded by E S G E N T /010/2024 (2025)."
        self.assertEqual(module.grants_in_text(text, p),
                         {"esgent":"ESGENT/010/2024"})

    def test_grant_matching_survives_pdf_line_wrapping(self):
        p = [{"key": "cns2023", "grants": ["CNS2023-144270"]}]
        self.assertEqual(module.grants_in_text(
            "Grant CNS2023-\n144270\nand other support", p),
            {"cns2023": "CNS2023-144270"})

    def test_license_noncommercial_cannot_be_republished(self):
        rec = {"license": "https://creativecommons.org/licenses/by-nc/4.0"}
        self.assertIsNone(module.metadata_licenses(rec, {}))

    @patch.object(module, "request_url", return_value=None)
    @patch.object(module, "download_publisher_page", return_value=None)
    @patch.object(module, "openalex_work", return_value={})
    def test_cached_evidence_restored_when_updater_has_no_awards(self, *_):
        rec = {"doi": "10.1/example", "projects": [], "image": None, "openAccess": None,
               "fundingEvidence": []}
        cache = {"fundingEvidence": [{"project": "cns2023", "grant": "CNS2023-144270",
                                      "source": "publisher-html", "url": "https://example.org"}],
                 "fundingStatus": "text-checked", "checked": module.date.today().isoformat()}
        out, _ = module.enrich_entry(rec, PROJECTS, cache, {"publications": {}})
        self.assertEqual(out["projects"], ["cns2023"])

    @patch.object(module, "request_url", return_value=None)
    @patch.object(module, "download_publisher_page", return_value=None)
    @patch.object(module, "openalex_work", return_value={})
    def test_manual_image_wins(self, *_):
        rec = {"doi": "10.1/example", "projects": [], "image": "https://cdn/manual.jpg",
               "openAccess": None, "fundingEvidence": []}
        out, _ = module.enrich_entry(rec, PROJECTS, {}, {"publications": {
            "10.1/example": {"image": "https://cdn/manual.jpg"}
        }})
        self.assertEqual(out["image"], "https://cdn/manual.jpg")

    def test_keyed_openalex_xml_and_pdf_supply_projects_and_artwork(self):
        xml = (b'<TEI><text><back><div type="acknowledgement">'
               b'<head>Funding</head><p>Support from 101122345 and CNS2023-144270.</p>'
               b'</div></back></text></TEI>')
        def fake_fetch(url, *_args, **_kwargs):
            if ".grobid-xml" in url:
                return xml, "https://content.openalex.org/works/W123.grobid-xml", "application/xml"
            if ".pdf" in url:
                return b"%PDF-fake", "https://content.openalex.org/works/W123.pdf", "application/pdf"
            return None
        rec = {"doi": "10.1/example", "projects": [], "image": None,
               "license": "https://creativecommons.org/licenses/by/4.0/",
               "openAccess": None, "fundingEvidence": [], "openalexId": "https://openalex.org/W123"}
        with patch.object(module, "KEY", "test-api-key"), \
             patch.object(module, "openalex_work", return_value={"id": "https://openalex.org/W123"}), \
             patch.object(module, "download_publisher_page", return_value=None), \
             patch.object(module, "openaire_grants", return_value=[]), \
             patch.object(module, "request_url", side_effect=fake_fetch), \
             patch.object(module, "extract_funding_from_pdf", return_value=[]), \
             patch.object(module, "first_figure_from_pdf", return_value=b"PNG-bytes"), \
             patch.object(module, "extract_image_to_webp", return_value=True):
            out, status = module.enrich_entry(rec, PROJECTS, {}, {"publications": {}})
        self.assertEqual(set(out["projects"]), {"hepaflex", "cns2023"})
        self.assertEqual(out["fundingStatus"], "text-checked")
        self.assertTrue(out["image"].startswith(module.RAW_IMAGES))
        self.assertEqual(out["imageType"], "figure-1")
        self.assertEqual(status["image"]["type"], "figure-1")

    def test_project_name_in_explicit_funding(self):
        grant_text = "Funding was provided by the Horizon Europe HEPAFLEX project."
        found = module.grants_in_text(grant_text, PROJECTS + [
            {"key": "named-hepaflex", "grants": [], "fundingAliases": ["HEPAFLEX"]}
        ])
        self.assertEqual(found["named-hepaflex"], "HEPAFLEX")
        self.assertNotIn("flexwin", found)

    def test_project_alias_respects_word_boundaries(self):
        p = [{"key": "hepaflex", "grants": ["101122345"],
              "fundingAliases": ["HEPAFLEX"]}]
        self.assertEqual(module.grants_in_text(
            "Financial support from HEPAFLEX.", p), {"hepaflex": "HEPAFLEX"})
        self.assertEqual(module.grants_in_text("NotHEPAFLEX2", p), {})

    @patch.object(module, "request_url")
    def test_semantic_scholar_open_access_pdf_fallback(self, fetch):
        fetch.return_value = (
            b'{"openAccessPdf":{"url":"https://repository.example.edu/article.pdf"}}',
            "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234/test",
            "application/json")
        rec = {"doi":"10.1234/test", "openAccess":{"pdf":None}}
        urls = module.accessible_pdf_candidates(
            {"locations":[{"pdf_url":"https://repo.example.org/open.pdf"}]},rec)
        self.assertEqual(urls, ["https://repo.example.org/open.pdf",
                               "https://repository.example.edu/article.pdf"])

    def test_elsevier_first_page_funding_pdf(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Rapid photonic processing", fontsize=12)
        page.insert_text((72, 120), "Funding", fontsize=12)
        page.insert_text((72, 145), "This work was funded by the HEPAFLEX project.")
        pdf = doc.tobytes()
        doc.close()
        sources = module.extract_funding_from_pdf(pdf, "https://repo.example.org/article.pdf")
        self.assertTrue(sources)
        found = module.grants_in_text(sources[0][1], [{"key":"hepaflex",
                        "grants":["101122345"],"fundingAliases":["HEPAFLEX"]}])
        self.assertEqual(found, {"hepaflex": "HEPAFLEX"})

    def test_elsevier_namespaced_funding_xml(self):
        xml = b"""<full-text xmlns:ce="http://www.elsevier.com/xml/common/dtd">
          <ce:acknowledgment>Horizon Europe project HEPAFLEX supported the work.</ce:acknowledgment>
          </full-text>"""
        evidence = module.text_from_tei(xml)
        p = [{"key":"hepaflex", "grants":["101122345"], "fundingAliases":["HEPAFLEX"]}]
        self.assertEqual(module.grants_in_text(evidence,p), {"hepaflex":"HEPAFLEX"})

    def test_elsevier_authenticated_request(self):
        xml = b"""<root xmlns:ce="http://www.elsevier.com/xml/common/dtd">
                <ce:acknowledgment>Supported by HEPAFLEX.</ce:acknowledgment></root>"""
        with patch.object(module,"ELSEVIER_KEY","secret-not-in-repo"), \
             patch.object(module,"request_url",
                 return_value=(xml,"https://api.elsevier.com/content/article/doi/test","text/xml")) as req:
            source = module.elsevier_article_funding("10.1016/j.solmat.2026.114703")
        self.assertEqual(source[0], "elsevier-tdm")
        self.assertIn("HEPAFLEX",source[1])
        self.assertEqual(req.call_args.kwargs["extra_headers"]["X-ELS-APIKey"], "secret-not-in-repo")

    def test_funding_html_excludes_article_body_topics(self):
        html = b"""<article><h2>Abstract</h2><p>HEPAFLEX is mentioned as a topic.</p>
               <h2>Funding</h2><p>Supported by another programme.</p><h2>References</h2>
               <p>HEPAFLEX grant appears in a cited reference.</p></article>"""
        text = module.section_text_from_html(html)
        self.assertNotIn("HEPAFLEX", text)

    def test_wiley_tdm_pdf_direct_success(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status_code = 200
        response.iter_content.return_value = [b"%PDF-a test document"]
        response.__enter__.return_value = response
        with patch.object(module, "WILEY_TDM_TOKEN", "test-token"), \
             patch.object(module.requests, "get", return_value=response) as req:
            pdf = module.wiley_tdm_pdf("10.1002/aelm.202500494")
        self.assertEqual(pdf[0], b"%PDF-a test document")
        self.assertIn("api.wiley.com/onlinelibrary/tdm/v1/articles/", pdf[1])
        self.assertEqual(req.call_args.kwargs["headers"]["Wiley-TDM-Client-Token"], "test-token")
        self.assertFalse(req.call_args.kwargs["allow_redirects"])

    def test_wiley_redirect_does_not_forward_token(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status_code = 302
        response.headers = {"Location": "https://example.org/signed-pdf"}
        response.__enter__.return_value = response
        with patch.object(module, "WILEY_TDM_TOKEN", "confidential-test-token"), \
             patch.object(module.requests, "get", return_value=response) as req, \
             patch.object(module, "request_url", return_value=(
                 b"%PDF-redirected", "https://example.org/signed-pdf", "application/pdf"
             )) as redirected:
            pdf = module.wiley_tdm_pdf("10.1002/sstr.202600020")
        self.assertEqual(pdf[0], b"%PDF-redirected")
        self.assertEqual(redirected.call_args.args[0], "https://example.org/signed-pdf")
        self.assertNotIn("extra_headers", redirected.call_args.kwargs)
        self.assertEqual(req.call_args.kwargs["headers"]["Wiley-TDM-Client-Token"], "confidential-test-token")

    def test_wiley_access_denial_without_pdf(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status_code = 404
        response.__enter__.return_value = response
        with patch.object(module, "WILEY_TDM_TOKEN", "test-token"), \
             patch.object(module.requests, "get", return_value=response):
            self.assertIsNone(module.wiley_tdm_pdf("10.1002/sstr.202600020"))

    def test_wiley_funding_populates_missing_projects_from_full_text(self):
        funding = ("acknowledgments", "CNS2023-144270 and ESGENT/010/2024 supported the work",
                   "https://api.wiley.com/onlinelibrary/tdm/v1/articles/10.1002/aelm.202500494")
        rec = {"doi": "10.1002/aelm.202500494", "projects": [],
               "image": None, "openAccess": None, "fundingEvidence": []}
        with patch.object(module, "WILEY_TDM_TOKEN", "test-token"), \
             patch.object(module, "KEY", ""), \
             patch.object(module, "openalex_work", return_value={}), \
             patch.object(module, "download_publisher_page", return_value=None), \
             patch.object(module, "openaire_grants", return_value=[]), \
             patch.object(module, "wiley_tdm_pdf", return_value=(b"%PDF-stub", funding[2])), \
             patch.object(module, "extract_funding_from_pdf", return_value=[funding]), \
             patch.object(module, "accessible_pdf_candidates", return_value=[]), \
             patch.object(module, "request_url", return_value=None), \
             patch.object(module, "european_pmc_xml", return_value=None):
            out, audit = module.enrich_entry(
                rec, PROJECTS, {}, {"publications": {}})
        self.assertEqual(set(out["projects"]), {"cns2023", "esgent"})
        self.assertEqual(audit["wileyTdmStatus"], "success")
        self.assertEqual(out["fundingStatus"], "text-checked")
        self.assertTrue(all(e["source"] == "wiley-tdm" for e in out["fundingEvidence"]))

    def test_wiley_memristor_grants_without_extractable_heading(self):
        """Grant identifiers in an unlabelled acknowledgement must be found."""
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((60, 80), "Conclusions and methods", fontsize=12)
        page.insert_text((60, 125), "The authors thank their colleagues.", fontsize=11)
        page.insert_text((60, 150), "The results are part of the grant CNS2023-144270", fontsize=11)
        page.insert_text((60, 175), "and funding via ESGENT/010/2024 from Generalitat Valenciana.", fontsize=11)
        pdf = doc.tobytes()
        doc.close()
        result = module.extract_funding_from_pdf(pdf, "https://example.org/memristors.pdf", PROJECTS)
        found = {}
        for _source, paragraph, _url in result:
            found.update(module.grants_in_text(paragraph, PROJECTS))
        self.assertEqual(set(found), {"cns2023", "esgent"})

    def test_references_alone_do_not_fund_article(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((60, 80), "References", fontsize=12)
        page.insert_text((60, 120), "1. Supported by grant CNS2023-144270", fontsize=11)
        pdf = doc.tobytes()
        doc.close()
        result = module.extract_funding_from_pdf(pdf, "https://example.org/references.pdf", PROJECTS)
        self.assertFalse(result)

    def test_graphical_abstract_alt_and_lazy_source(self):
        html = b"""<figure><img alt="Graphical Abstract" data-src="/toc.png"
                  src="/placeholder.gif"></figure>"""
        self.assertEqual(
            module.graphical_abstract_from_html(html, "https://publisher.example/doi/x"),
            ("https://publisher.example/toc.png", "graphical-abstract"))

    def test_generic_open_graph_image_is_not_toc(self):
        html = b'<meta property="og:image" content="/publisher-logo.jpg">'
        self.assertEqual(
            module.graphical_abstract_from_html(html, "https://publisher.example"),
            (None, None))

    def test_pdf_toc_selection_before_figure_fallback(self):
        import fitz
        from PIL import Image
        import io
        pic = Image.new("RGB", (720, 320), "#edf3f4")
        buf = io.BytesIO()
        pic.save(buf, format="PNG")
        doc = fitz.open()
        p = doc.new_page(width=600, height=800)
        p.insert_text((60, 130), "Graphical Abstract", fontsize=14)
        p.insert_image(fitz.Rect(70, 160, 520, 360), stream=buf.getvalue())
        p.insert_text((60, 500), "Figure 1. Example diagram", fontsize=12)
        pdf = doc.tobytes()
        doc.close()
        toc = module.toc_graphic_from_pdf(pdf)
        self.assertTrue(toc and toc.startswith(b"\x89PNG"))
        with patch.object(module, "toc_graphic_from_pdf", return_value=toc), \
             patch.object(module, "first_figure_from_pdf") as fallback:
            self.assertIsNotNone(module.toc_graphic_from_pdf(pdf))
            fallback.assert_not_called()

    def test_pdf_toc_vector_graphics_are_supported(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text((60, 120), "Graphical Abstract", fontsize=14)
        for i in range(30):
            x = 70 + (i % 10) * 34
            y = 175 + (i // 10) * 38
            page.draw_rect(fitz.Rect(x, y, x+24, y+26),
                           color=(0.3, 0.3, 0.3), fill=(0.8, 0.9, 0.9))
        pdf = doc.tobytes()
        doc.close()
        art = module.toc_graphic_from_pdf(pdf)
        self.assertTrue(art and art.startswith(b"\x89PNG"))

    def test_pdf_footnote_graphical_abstract_not_toc(self):
        import fitz
        from PIL import Image
        import io
        pic = Image.new("RGB", (720, 320), "white")
        buf = io.BytesIO()
        pic.save(buf, format="PNG")
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text((60, 700), "See the graphical abstract on the publisher website.", fontsize=10)
        page.insert_image(fitz.Rect(70, 610, 500, 680), stream=buf.getvalue())
        pdf = doc.tobytes()
        doc.close()
        self.assertIsNone(module.toc_graphic_from_pdf(pdf))

    def test_alpha_is_composited_on_white(self):
        import io
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            img = Image.new("RGBA", (400, 220), (0, 0, 0, 0))
            img.putpixel((200, 110), (0, 0, 0, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            output = Path(d) / "image.webp"
            self.assertTrue(module.extract_image_to_webp(buf.getvalue(), output))
            with Image.open(output) as res:
                self.assertGreater(min(res.convert("RGB").getpixel((15, 15))), 245)
                self.assertLess(max(res.convert("RGB").getpixel((200, 110))), 30)

    def test_wiley_pdf_retry_for_missing_image_after_successful_funding(self):
        rec = {"doi": "10.1002/nap2.70196", "projects": [],
               "image": None, "license": "https://creativecommons.org/licenses/by/4.0/",
               "openAccess": None, "fundingEvidence": []}
        prev = {"checked": module.date.today().isoformat(),
                "fundingStatus":"text-checked",
                "fundingMatcherVersion":module.FUNDING_MATCHER_VERSION,
                "fundingEvidence":[], "wileyTdmStatus":"success"}
        with patch.object(module, "WILEY_TDM_TOKEN", "stub"), \
             patch.object(module, "KEY", ""), \
             patch.object(module, "wiley_tdm_pdf", return_value=(b"%PDF-fake", "https://api.wiley.com/test")) as call, \
             patch.object(module, "openalex_work", return_value={}), \
             patch.object(module, "download_publisher_page", return_value=None), \
             patch.object(module, "openaire_grants", return_value=[]), \
             patch.object(module, "accessible_pdf_candidates", return_value=[]), \
             patch.object(module, "extract_funding_from_pdf", return_value=[]), \
             patch.object(module, "first_figure_from_pdf", return_value=b"stub"), \
             patch.object(module, "toc_graphic_from_pdf", return_value=None), \
             patch.object(module, "extract_image_to_webp", return_value=True):
            out, _ = module.enrich_entry(rec, PROJECTS, prev, {"publications": {}})
        call.assert_called_once_with("10.1002/nap2.70196")
        self.assertEqual(out["imageType"], "figure-1")

    def test_toc_priority(self):
        markup = b'<div class="graphical-abstract"><img data-src="/images/article-toc.png"/></div>'
        self.assertEqual(module.graphical_abstract_from_html(markup, "https://example.org/a")[0],
                         "https://example.org/images/article-toc.png")


if __name__ == "__main__":
    unittest.main()
