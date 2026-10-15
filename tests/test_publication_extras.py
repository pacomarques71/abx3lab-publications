"""Proyectos por código de financiación, líneas de investigación y destacados."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "updater", Path(__file__).resolve().parents[1] / "scripts/update_publications.py"
)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

PROJECTS = [
    {"key": "phoenixpv", "grants": ["101171478"]},
    {"key": "flexwin", "grants": ["PID2023-151880OB-C31"]},
    {"key": "inkflex", "grants": ["PID2023-151880OB-C32"]},
    {"key": "esgent", "grants": ["ESGENT/010/2024"]},
]
EXTRAS = {
    "themes": [
        {"key": "fotonica", "keywords": ["waveguide"]},
        {"key": "estabilidad", "keywords": ["self-heal"]},
    ],
    "publications": {
        "10.1/featured": {
            "themes": ["estabilidad"],
            "projects": ["inkflex"],
            "featured": {"order": 1, "title": "Breve"},
        }
    },
    "members": {"Pablo P. Boix": {"profile": "/equipo/#pablo-boix"}},
}


class ProjectMatchTest(unittest.TestCase):
    def test_codes_with_unicode_hyphens_and_slashes(self):
        awards = ["PID2023‐151880OB‐C31", "ESGENT010/2024", "European Research Council 101171478"]
        self.assertEqual(updater.match_projects(awards, PROJECTS), ["phoenixpv", "flexwin", "esgent"])

    def test_unrelated_codes_do_not_match(self):
        self.assertEqual(updater.match_projects(["PID2020-119628RB-C31", "852722"], PROJECTS), [])


class ApplyExtrasTest(unittest.TestCase):
    def record(self, doi, title, awards=()):
        return {
            "doi": doi, "title": title, "awards": list(awards),
            "groupMembers": [{"name": "Pablo P. Boix", "display": "Pablo P. Boix"}],
        }

    def test_manual_data_wins_over_keywords(self):
        r = updater.apply_extras(self.record("10.1/FEATURED", "Planar waveguide", ["101171478"]), EXTRAS, PROJECTS)
        self.assertEqual(r["themes"], ["estabilidad"])
        self.assertEqual(r["projects"], ["phoenixpv", "inkflex"])
        self.assertEqual(r["featured"]["title"], "Breve")
        self.assertNotIn("awards", r)
        self.assertEqual(r["groupMembers"][0]["profile"], "/equipo/#pablo-boix")

    def test_keyword_fallback_for_new_articles(self):
        r = updater.apply_extras(self.record("10.1/new", "Photon recycling in a <i>waveguide</i>"), EXTRAS, PROJECTS)
        self.assertEqual(r["themes"], ["fotonica"])
        self.assertEqual(r["projects"], [])
        self.assertIsNone(r["featured"])


class PublisherPdfTest(unittest.TestCase):
    CC = {"license": "http://creativecommons.org/licenses/by/4.0/"}

    def test_wiley_open_access_gets_direct_pdf(self):
        best = {"version": "publishedVersion", "pdf_url": None}
        self.assertEqual(
            updater.publisher_pdf("10.1002/sstr.202600020", best, self.CC),
            "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/sstr.202600020",
        )

    def test_no_pdf_without_creative_commons_licence(self):
        best = {"version": "publishedVersion"}
        self.assertIsNone(updater.publisher_pdf("10.1002/anie.7703450", best, {"license": None}))

    def test_no_publisher_pdf_for_accepted_manuscripts_or_other_publishers(self):
        self.assertIsNone(updater.publisher_pdf("10.1002/x.1", {"version": "acceptedVersion"}, self.CC))
        self.assertIsNone(updater.publisher_pdf("10.1016/j.x.1", {"version": "publishedVersion"}, self.CC))


if __name__ == "__main__":
    unittest.main()
