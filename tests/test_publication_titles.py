"""Títulos con fórmulas químicas: subíndices sin espacios sobrantes."""
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

INDENT = "\n                    "


class CleanTitleTest(unittest.TestCase):
    def test_crossref_jats_titles(self):
        cases = {
            # Títulos reales de Crossref (octubre 2026).
            f"Rapid Laser-Based Deposition of PbI{INDENT}<sub>2</sub>{INDENT}/CsBr Inorganic Scaffolds":
                "Rapid Laser-Based Deposition of PbI<sub>2</sub>/CsBr Inorganic Scaffolds",
            f"OER Activity Promoted by Organic Ligand‐Free Cs{INDENT}<sub>2</sub>{INDENT}Pt(Cl, Br){INDENT}<sub>6</sub>{INDENT}Perovskite Photocatalyst":
                "OER Activity Promoted by Organic Ligand‐Free Cs<sub>2</sub>Pt(Cl, Br)<sub>6</sub> Perovskite Photocatalyst",
            f"CsPbBr{INDENT}<sub>3</sub>{INDENT}nanocrystals supported on a partially oxidized Ti{INDENT}<sub>2</sub>{INDENT}N MXene for photothermal CO{INDENT}<sub>2</sub>{INDENT}conversion":
                "CsPbBr<sub>3</sub> nanocrystals supported on a partially oxidized Ti<sub>2</sub>N MXene for photothermal CO<sub>2</sub> conversion",
            f"Photon Recycling–Driven Photodetection Enhancement in Ni(AcO){INDENT}<sub>2</sub>{INDENT}–MAPbBr{INDENT}<sub>3</sub>{INDENT}Nanocomposite Waveguides":
                "Photon Recycling–Driven Photodetection Enhancement in Ni(AcO)<sub>2</sub>–MAPbBr<sub>3</sub> Nanocomposite Waveguides",
            f"Ambient{INDENT}<i>operando</i>{INDENT}self-healing in tin perovskite solar cells":
                "Ambient <i>operando</i> self-healing in tin perovskite solar cells",
        }
        for raw, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(updater.clean_title(raw), expected)

    def test_words_after_subscript_keep_their_space(self):
        self.assertEqual(updater.clean_title("CO<sub>2</sub> In Situ Study"), "CO<sub>2</sub> In Situ Study")
        self.assertEqual(updater.clean_title("MAPbI<sub>3</sub> A Review"), "MAPbI<sub>3</sub> A Review")

    def test_other_tags_are_removed(self):
        self.assertEqual(
            updater.clean_title("<scp>Sn</scp>‐based   perovskites<mml:math>x</mml:math>"),
            "Sn‐based perovskitesx",
        )

    def test_plain_title_unchanged(self):
        title = "Ambient operando self-healing in tin perovskite solar cells"
        self.assertEqual(updater.clean_title(title), title)


class TitleFallbackTest(unittest.TestCase):
    def test_previous_title_is_kept_when_crossref_fails(self):
        work = {
            "doi": "https://doi.org/10.1002/nap2.70196",
            "title": "Photon Recycling–Driven Photodetection Enhancement in Ni(AcO) 2 –MAPbBr 3 Nanocomposite Waveguides",
            "publication_date": "2026-07-02",
        }
        previous = "Photon Recycling–Driven Photodetection Enhancement in Ni(AcO)<sub>2</sub>–MAPbBr<sub>3</sub> Nanocomposite Waveguides"
        with patch.object(updater, "fetch_json", side_effect=RuntimeError("Crossref caído")), \
             patch.object(updater, "MAX_PUBLICATION_DATE", date(2026, 10, 14)), \
             patch.dict(updater.PREVIOUS_TITLES, {"10.1002/nap2.70196": previous}, clear=True):
            record = updater.make_record(work, ["Kevin Mego", "Pedro Atienzar"], set(), {})
        self.assertEqual(record["title"], previous)


if __name__ == "__main__":
    unittest.main()
