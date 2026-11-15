"""Regressions for early-online articles assigned to a later journal issue."""
import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "updater", Path(__file__).resolve().parents[1] / "scripts/update_publications.py"
)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class PublicationDatesTest(unittest.TestCase):
    def record(self, metadata, online_date):
        work = {"doi": "https://doi.org/10.1002/example", "publication_date": online_date}
        with patch.object(updater, "fetch_json", return_value={"message": metadata}), \
             patch.object(updater, "MAX_PUBLICATION_DATE", date(2026, 10, 5)):
            return updater.make_record(work, ["Kevin Mego", "Pedro Atienzar"], set(), {})

    def test_wiley_2025_online_2026_issue_is_included(self):
        record = self.record({
            "volume": "7", "issue": "2",
            "published-online": {"date-parts": [[2025, 10, 15]]},
            "published-print": {"date-parts": [[2026, 2]]},
            "published": {"date-parts": [[2025, 10, 15]]},
        }, "2025-10-15")
        self.assertEqual(record["year"], 2026)
        self.assertEqual(record["publicationDate"], "2026-02-01")
        self.assertEqual(record["onlinePublicationDate"], "2025-10-15")

    def test_rsc_year_only_retains_exact_online_date(self):
        record = self.record({
            "volume": "7", "issue": "4",
            "published-online": {"date-parts": [[2026]]},
            "published": {"date-parts": [[2026]]},
        }, "2025-12-29")
        self.assertEqual(record["year"], 2026)
        self.assertEqual(record["onlinePublicationDate"], "2025-12-29")

    def test_online_article_without_issue(self):
        record = self.record({"published-online": {"date-parts": [[2026, 9, 1]]}}, "2026-09-01")
        self.assertEqual(record["publicationDate"], "2026-09-01")

    def test_old_issue_dates_are_excluded(self):
        self.assertIsNone(self.record({
            "volume": "7", "published-print": {"date-parts": [[2025, 2]]},
        }, "2025-10-15"))

    def test_future_issue_not_yet_online_is_excluded(self):
        self.assertIsNone(self.record({
            "volume": "7", "published-print": {"date-parts": [[2027, 2]]},
            "created": {"date-parts": [[2026, 11, 20]]},
        }, "2027-02-01"))

    def test_elsevier_future_issue_already_online_is_included(self):
        # 10.1016/j.solmat.2026.114703: Crossref only has vol. 309 (January 2027)
        # and the DOI registration date; no published-online.
        metadata = {
            "volume": "309", "article-number": "114703",
            "published-print": {"date-parts": [[2027, 1]]},
            "published": {"date-parts": [[2027, 1]]},
            "issued": {"date-parts": [[2027, 1]]},
            "created": {"date-parts": [[2026, 9, 17]]},
        }
        record = self.record(metadata, "2027-01-01")
        self.assertEqual(record["publicationDate"], "2026-09-17")
        self.assertEqual(record["onlinePublicationDate"], "2026-09-17")
        self.assertEqual(record["issueDate"], "2027-01-01")
        self.assertEqual(record["year"], 2026)

        # Once the issue date has passed, the bibliographic date applies again.
        work = {"doi": "https://doi.org/10.1016/example", "publication_date": "2027-01-01"}
        with patch.object(updater, "fetch_json", return_value={"message": metadata}), \
             patch.object(updater, "MAX_PUBLICATION_DATE", date(2027, 1, 15)):
            later = updater.make_record(work, ["Pablo P. Boix", "Teresa Ripollés Sanchis"], set(), {})
        self.assertEqual(later["publicationDate"], "2027-01-01")
        self.assertIsNone(later["issueDate"])

    def rsc_record(self, metadata, openalex_date, today=date(2026, 11, 15)):
        work = {"doi": "https://doi.org/10.1039/d6ee05477c", "publication_date": openalex_date}
        with patch.object(updater, "fetch_json", return_value={"message": metadata}), \
             patch.object(updater, "MAX_PUBLICATION_DATE", today):
            return updater.make_record(work, ["Rafael Abargues López", "Pablo P. Boix"], set(), {})

    def test_rsc_year_only_uses_doi_registration_date(self):
        # 10.1039/d6ee05477c (Energy Environ. Sci. 19, 7447): Crossref solo da
        # [[2026]] y OpenAlex copia 2026-01-01. Salía fechado el 1 de enero, al
        # final de la lista, fuera de «Selección reciente» y de la portada.
        record = self.rsc_record({
            "published-online": {"date-parts": [[2026]]},
            "published": {"date-parts": [[2026]]},
            "issued": {"date-parts": [[2026]]},
            "created": {"date-parts": [[2026, 10, 6]]},
        }, "2026-01-01")
        self.assertEqual(record["publicationDate"], "2026-10-06")
        self.assertEqual(record["onlinePublicationDate"], "2026-10-06")
        self.assertIsNone(record["issueDate"])
        self.assertEqual(record["year"], 2026)

    def test_rsc_year_only_prefers_exact_openalex_date(self):
        record = self.rsc_record({
            "volume": "10", "published": {"date-parts": [[2026]]},
            "created": {"date-parts": [[2026, 3, 4]]},
        }, "2026-03-02")
        self.assertEqual(record["publicationDate"], "2026-03-02")
        self.assertEqual(record["onlinePublicationDate"], "2026-03-02")

    def test_rsc_year_only_online_previous_year_keeps_volume_year(self):
        record = self.rsc_record({
            "volume": "7", "published": {"date-parts": [[2026]]},
            "created": {"date-parts": [[2025, 12, 29]]},
        }, "2025-12-29")
        self.assertEqual(record["publicationDate"], "2026-01-01")
        self.assertEqual(record["onlinePublicationDate"], "2025-12-29")
        self.assertEqual(record["year"], 2026)

    def test_month_precision_issue_date_is_unchanged(self):
        record = self.rsc_record({
            "volume": "7", "issue": "7",
            "published-print": {"date-parts": [[2026, 7]]},
            "published-online": {"date-parts": [[2026, 6, 20]]},
            "created": {"date-parts": [[2026, 6, 20]]},
        }, "2026-06-20")
        self.assertEqual(record["publicationDate"], "2026-07-01")
        self.assertEqual(record["onlinePublicationDate"], "2026-06-20")

    def test_discovery_reaches_older_pages_without_online_date_filter(self):
        first_page = [{"doi": f"10.1002/new{i}"} for i in range(200)]
        pages = [
            {"results": first_page, "meta": {"count": 201}},
            {"results": [{"doi": "10.1002/old", "publication_date": "2025-10-15"}],
             "meta": {"count": 201}},
        ]
        with patch.object(updater, "fetch_json", side_effect=pages) as fetch, \
             patch.object(updater.time, "sleep"):
            works = updater.discover_works([{"name": "Kevin", "orcid": "0000-0003-3150-5004"}])
        self.assertIn("doi:10.1002/old", works)
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all("from_publication_date" not in call.args[0] for call in fetch.call_args_list))
        # Sin cursor: OpenAlex pide API key para cursor= desde octubre de 2026.
        self.assertTrue(all("cursor=" not in call.args[0] for call in fetch.call_args_list))
        self.assertIn("page=2", fetch.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
