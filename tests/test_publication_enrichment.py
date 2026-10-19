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

    def test_license_noncommercial_cannot_be_republished(self):
        rec = {"license": "https://creativecommons.org/licenses/by-nc/4.0"}
        self.assertIsNone(module.metadata_licenses(rec, {}))

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

    @patch.object(module, "download_publisher_page", return_value=None)
    @patch.object(module, "openalex_work", return_value={})
    def test_manual_image_wins(self, *_):
        rec = {"doi": "10.1/example", "projects": [], "image": "https://cdn/manual.jpg",
               "openAccess": None, "fundingEvidence": []}
        out, _ = module.enrich_entry(rec, PROJECTS, {}, {"publications": {
            "10.1/example": {"image": "https://cdn/manual.jpg"}
        }})
        self.assertEqual(out["image"], "https://cdn/manual.jpg")

    def test_toc_priority(self):
        markup = b'<div class="graphical-abstract"><img data-src="/images/article-toc.png"/></div>'
        self.assertEqual(module.graphical_abstract_from_html(markup, "https://example.org/a")[0],
                         "https://example.org/images/article-toc.png")


if __name__ == "__main__":
    unittest.main()
