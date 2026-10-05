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

    def test_old_and_future_issue_dates_are_excluded(self):
        for year in (2025, 2027):
            with self.subTest(year=year):
                self.assertIsNone(self.record({
                    "volume": "7", "published-print": {"date-parts": [[year, 2]]},
                }, "2025-10-15"))

    def test_discovery_reaches_older_pages_without_online_date_filter(self):
        pages = [
            {"results": [{"doi": "10.1002/new"}], "meta": {"next_cursor": "next"}},
            {"results": [{"doi": "10.1002/old", "publication_date": "2025-10-15"}],
             "meta": {"next_cursor": None}},
        ]
        with patch.object(updater, "fetch_json", side_effect=pages) as fetch, \
             patch.object(updater.time, "sleep"):
            works = updater.discover_works([{"name": "Kevin", "orcid": "0000-0003-3150-5004"}])
        self.assertIn("doi:10.1002/old", works)
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all("from_publication_date" not in call.args[0] for call in fetch.call_args_list))


if __name__ == "__main__":
    unittest.main()
