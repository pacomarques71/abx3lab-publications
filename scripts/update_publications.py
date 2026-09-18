#!/usr/bin/env python3
"""
Actualiza data/publications.json usando OpenAlex + Crossref.

Reglas:
- Fecha mínima: 2026-01-01.
- Solo artículos/reviews.
- Al menos 2 miembros del grupo.
- ORCID prioritario; aliases como fallback.
- Los miembros con ORCID=null cuentan como coautores, pero no se usan para descubrir trabajos.

Uso:
    python scripts/update_publications.py

Variables opcionales:
    OPENALEX_API_KEY
    CROSSREF_MAILTO
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TEAM_FILE = ROOT / "data" / "publication_team.json"
EXCLUDED_FILE = ROOT / "data" / "excluded_publications.json"
OUTPUT_FILE = ROOT / "data" / "publications.json"

MIN_PUBLICATION_DATE = date(2026, 1, 1)
MAX_PUBLICATION_DATE = date.today()
MIN_GROUP_AUTHORS = 2

OPENALEX_BASE = "https://api.openalex.org"
CROSSREF_BASE = "https://api.crossref.org"
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "").strip()
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "").strip()
USER_AGENT = "ABX3LabPublicationUpdater/1.0"

# Evita que la consola de Windows falle al imprimir títulos con caracteres Unicode.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def fetch_json(url: str, retries: int = 3) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error = None
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"No se pudo consultar {url}: {last_error}")

def normalize_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("–", "-").replace("—", "-")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())

def normalize_orcid(value: str | None) -> str | None:
    if not value:
        return None
    return (
        value.replace("https://orcid.org/", "")
        .replace("http://orcid.org/", "")
        .strip()
        .upper()
    ) or None

def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    return (
        value.replace("https://doi.org/", "")
        .replace("http://doi.org/", "")
        .strip()
    ) or None

def load_team() -> list[dict]:
    return json.loads(TEAM_FILE.read_text(encoding="utf-8"))

def load_excluded_dois() -> set[str]:
    if not EXCLUDED_FILE.exists():
        return set()
    values = json.loads(EXCLUDED_FILE.read_text(encoding="utf-8"))
    return {
        normalize_doi(value).lower()
        for value in values
        if normalize_doi(value)
    }

def build_member_indexes(team: list[dict]):
    by_orcid = {}
    aliases = {}
    for member in team:
        oid = normalize_orcid(member.get("orcid"))
        if oid:
            by_orcid[oid] = member["name"]
        for alias in [member["name"], *member.get("aliases", [])]:
            aliases[normalize_text(alias)] = member["name"]
    return by_orcid, aliases

def openalex_work_key(work: dict) -> str:
    doi = normalize_doi(work.get("doi"))
    return ("doi:" + doi.lower()) if doi else ("oa:" + str(work.get("id", "")).lower())

def discover_works(team: list[dict]) -> dict[str, dict]:
    works = {}
    queried = 0

    for member in team:
        orcid = normalize_orcid(member.get("orcid"))
        if not orcid:
            continue

        filters = (
            f"author.orcid:{orcid},"
            f"from_publication_date:{MIN_PUBLICATION_DATE.isoformat()},"
            f"type:article|review"
        )
        params = {
            "filter": filters,
            "sort": "publication_date:desc",
            "per_page": "100",
        }
        if OPENALEX_API_KEY:
            params["api_key"] = OPENALEX_API_KEY

        url = f"{OPENALEX_BASE}/works?{urlencode(params)}"
        print(f"Consultando OpenAlex: {member['name']} ({orcid})")
        payload = fetch_json(url)
        queried += 1

        for work in payload.get("results", []):
            works[openalex_work_key(work)] = work

        time.sleep(0.15)

    if queried == 0:
        raise RuntimeError("No hay ORCID configurados en publication_team.json.")

    return works

def identify_group_authors(work: dict, by_orcid: dict, aliases: dict) -> list[str]:
    found, seen = [], set()

    for authorship in work.get("authorships", []):
        author = authorship.get("author") or {}
        display_name = author.get("display_name") or ""
        oid = normalize_orcid(author.get("orcid"))

        canonical = None
        if oid and oid in by_orcid:
            canonical = by_orcid[oid]
        else:
            canonical = aliases.get(normalize_text(display_name))

        if canonical and canonical not in seen:
            seen.add(canonical)
            found.append(canonical)

    return found

def date_from_parts(parts) -> date | None:
    if not parts:
        return None
    try:
        y = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 1
        d = int(parts[2]) if len(parts) > 2 else 1
        return date(y, m, d)
    except (TypeError, ValueError, IndexError):
        return None

def crossref_metadata(doi: str) -> dict:
    encoded = quote(doi, safe="")
    params = {"mailto": CROSSREF_MAILTO} if CROSSREF_MAILTO else {}
    suffix = ("?" + urlencode(params)) if params else ""
    url = f"{CROSSREF_BASE}/works/{encoded}{suffix}"

    try:
        msg = fetch_json(url, retries=2).get("message", {})
    except Exception as exc:
        print(f"  Aviso: Crossref no disponible para {doi}: {exc}")
        return {}

    dates = []
    for key in ("published-online", "published-print", "published", "issued"):
        parts = (msg.get(key) or {}).get("date-parts")
        if parts and parts[0]:
            parsed = date_from_parts(parts[0])
            if parsed:
                dates.append(parsed)

    first_date = min(dates) if dates else None

    authors = []
    for author in msg.get("author", []) or []:
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        full = " ".join(x for x in (given, family) if x)
        if full:
            authors.append(full)

    titles = msg.get("title") or []
    journals = msg.get("container-title") or []

    return {
        "title": titles[0] if titles else None,
        "authors": authors,
        "journal": journals[0] if journals else None,
        "publicationDate": first_date.isoformat() if first_date else None,
        "volume": msg.get("volume"),
        "issue": msg.get("issue"),
        "pages": msg.get("page") or msg.get("article-number"),
    }

def fallback_openalex_date(work: dict) -> date | None:
    raw = work.get("publication_date")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    year = work.get("publication_year")
    if year:
        try:
            return date(int(year), 1, 1)
        except (TypeError, ValueError):
            pass
    return None

def make_record(
    work: dict,
    group_authors: list[str],
    excluded_dois: set[str],
) -> dict | None:
    doi = normalize_doi(work.get("doi"))
    if not doi:
        return None
    if doi.lower() in excluded_dois:
        return None

    meta = crossref_metadata(doi)
    pub_date = None

    if meta.get("publicationDate"):
        try:
            pub_date = date.fromisoformat(meta["publicationDate"])
        except ValueError:
            pass

    pub_date = pub_date or fallback_openalex_date(work)
    if (
        not pub_date
        or pub_date < MIN_PUBLICATION_DATE
        or pub_date > MAX_PUBLICATION_DATE
    ):
        return None

    oa_authors = [
        (a.get("author") or {}).get("display_name")
        for a in work.get("authorships", [])
        if (a.get("author") or {}).get("display_name")
    ]
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    biblio = work.get("biblio") or {}

    return {
        "title": meta.get("title") or work.get("title"),
        "authors": meta.get("authors") or oa_authors,
        "groupAuthors": group_authors,
        "journal": meta.get("journal") or source.get("display_name"),
        "publicationDate": pub_date.isoformat(),
        "year": pub_date.year,
        "volume": meta.get("volume") or biblio.get("volume"),
        "issue": meta.get("issue") or biblio.get("issue"),
        "pages": meta.get("pages") or biblio.get("first_page"),
        "doi": doi,
        "url": f"https://doi.org/{doi}",
        "type": "review" if work.get("type") == "review" else "article",
        "image": None,
    }

def remove_wiley_language_duplicates(records: list[dict]) -> list[dict]:
    """
    Wiley publica algunos artículos como pares equivalentes:
    10.1002/ange.<suffix> (Angewandte Chemie)
    10.1002/anie.<suffix> (Angewandte Chemie International Edition)

    Si existen ambos DOI con el mismo sufijo, conserva la versión International Edition.
    """
    doi_set = {record["doi"].lower() for record in records if record.get("doi")}
    cleaned = []

    for record in records:
        doi = record.get("doi", "").lower()
        if doi.startswith("10.1002/ange."):
            international_doi = doi.replace("10.1002/ange.", "10.1002/anie.", 1)
            if international_doi in doi_set:
                continue
        cleaned.append(record)

    return cleaned

def main():
    team = load_team()
    excluded_dois = load_excluded_dois()
    by_orcid, aliases = build_member_indexes(team)

    try:
        works = discover_works(team)
    except Exception as exc:
        print(f"\nERROR: no se ha modificado publications.json.\n{exc}", file=sys.stderr)
        raise SystemExit(1)

    detected = []
    for work in works.values():
        group_authors = identify_group_authors(work, by_orcid, aliases)
        if len(group_authors) < MIN_GROUP_AUTHORS:
            continue
        record = make_record(work, group_authors, excluded_dois)
        if record:
            detected.append(record)

    by_doi = {r["doi"].lower(): r for r in detected}
    deduplicated = remove_wiley_language_duplicates(list(by_doi.values()))
    final_records = sorted(
        deduplicated,
        key=lambda r: (r.get("publicationDate") or "", r.get("title") or ""),
        reverse=True,
    )

    if not final_records:
        print(
            "\nERROR: no se detectó ninguna publicación válida; "
            "por seguridad no se sobrescribe el JSON existente.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    tmp = OUTPUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(final_records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUTPUT_FILE)

    print(f"\nActualización completada: {len(final_records)} publicaciones.")
    for record in final_records[:5]:
        print(f" - {record['publicationDate']} | {record['title']}")

if __name__ == "__main__":
    main()
