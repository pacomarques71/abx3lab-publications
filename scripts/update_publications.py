#!/usr/bin/env python3
"""
Actualiza data/publications.json usando OpenAlex + Crossref.

Reglas:
- Fecha bibliográfica mínima: 2026-01-01 (número de revista si está disponible).
- Artículos ya publicados online pero asignados a un número futuro (p. ej.
  Elsevier, volumen de 2027): se incluyen con su fecha online hasta que llega
  la fecha del número; después pasan a la fecha del número.
- Solo artículos/reviews.
- Al menos 2 miembros del grupo.
- ORCID prioritario; aliases como fallback.
- Los miembros con ORCID=null cuentan como coautores, pero no se usan para descubrir trabajos.
- Archivo aparte (data/publications_2025.json) con las publicaciones de 2025, mismas reglas.
- Datos editoriales (data/publication_extras.json): líneas de investigación, destacados y
  enlaces a los perfiles del equipo. Proyectos (data/projects.json): se vinculan por los
  códigos de financiación que la editorial deposita en Crossref/OpenAlex (agradecimientos).

Uso:
    python scripts/update_publications.py

Variables opcionales:
    OPENALEX_API_KEY
    CROSSREF_MAILTO
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TEAM_FILE = ROOT / "data" / "publication_team.json"
EXCLUDED_FILE = ROOT / "data" / "excluded_publications.json"
OUTPUT_FILE = ROOT / "data" / "publications.json"
ARCHIVE_FILE = ROOT / "data" / "publications_2025.json"
EXTRAS_FILE = ROOT / "data" / "publication_extras.json"
PROJECTS_FILE = ROOT / "data" / "projects.json"

MIN_PUBLICATION_DATE = date(2026, 1, 1)
# Archivo de años anteriores: solo 2025, en un JSON aparte para no cambiar
# lo que leen la portada y /publicaciones/.
ARCHIVE_MIN_DATE = date(2025, 1, 1)
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
                wait = 1.5 * (attempt + 1)
                # Crossref limita las peticiones (429): esperar lo que indique.
                if isinstance(exc, HTTPError) and exc.code in (429, 503):
                    try:
                        wait = max(wait, float(exc.headers.get("Retry-After") or 0))
                    except (TypeError, ValueError):
                        pass
                    wait = max(wait, 4.0 * (attempt + 1))
                time.sleep(min(wait, 30))
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

# Títulos: Crossref los da en JATS, con <sub>/<sup>/<i> y saltos de línea e
# indentación entre etiquetas (p. ej. "PbI\n      <sub>2</sub>\n      /CsBr").
# Se dejan solo esas etiquetas de formato y se quitan los espacios que añade el
# XML, para que la web muestre "PbI<sub>2</sub>/CsBr" y no "PbI ₂ /CsBr".
TITLE_KEEP_TAGS = ("sub", "sup", "i", "b")
# Tras un subíndice el espacio se conserva ("CO<sub>2</sub> conversion"), salvo
# que siga la fórmula: un signo ("/CsBr", "–MAPbBr", "(Cl, Br)"), un elemento de
# una letra suelto ("Ti<sub>2</sub>N MXene") o un elemento seguido de paréntesis
# ("Cs<sub>2</sub>Pt(Cl, Br)<sub>6</sub>").
_FORMULA_CONTINUATION = re.compile(
    r"</(sub|sup)>\s+(?=[(\[/–—\-+·,.:;)]|[BCFHKNOPSUVWY](?![\w])|[A-Z][a-z]?[(\[])"
)

def clean_title(value: str | None) -> str | None:
    if not value:
        return value
    keep = "|".join(TITLE_KEEP_TAGS)
    # Quita cualquier otra etiqueta (<scp>, <mml:…>, <title>…) y conserva el texto.
    value = re.sub(rf"<(?!/?(?:{keep})>)[^>]*>", "", value)
    value = " ".join(value.split())
    value = re.sub(rf"<({keep})>\s+", r"<\1>", value)
    value = re.sub(rf"\s+</({keep})>", r"</\1>", value)
    value = re.sub(r"\s+<(sub|sup)>", r"<\1>", value)
    value = _FORMULA_CONTINUATION.sub(r"</\1>", value)
    return value.strip() or None

def load_previous_records() -> dict[str, dict]:
    """Última versión publicada de cada registro, por DOI (ambos ficheros)."""
    records = {}
    for path in (OUTPUT_FILE, ARCHIVE_FILE):
        if not path.exists():
            continue
        try:
            for record in json.loads(path.read_text(encoding="utf-8")):
                doi = normalize_doi(record.get("doi"))
                if doi:
                    records[doi.lower()] = record
        except (OSError, json.JSONDecodeError):
            continue
    return records

PREVIOUS_RECORDS: dict[str, dict] = {}

def previous_as_meta(previous: dict) -> dict:
    """Si Crossref falla, reutiliza los datos bibliográficos ya publicados."""
    return {
        "title": previous.get("title"),
        "authors": previous.get("authors") or [],
        "journal": previous.get("journal"),
        "publicationDate": previous.get("issueDate") or previous.get("publicationDate"),
        "onlinePublicationDate": previous.get("onlinePublicationDate"),
        "volume": previous.get("volume"),
        "issue": previous.get("issue"),
        "pages": previous.get("pages"),
        "license": previous.get("license"),
        "awards": [],
    }

def load_previous_titles() -> dict[str, str]:
    """Títulos de la última versión publicada, por DOI.

    Si Crossref no responde, OpenAlex solo da el título en texto plano y pierde
    los subíndices ("Ni(AcO) 2 –MAPbBr 3"). En ese caso se reutiliza el título
    que ya teníamos para ese DOI.
    """
    records = []
    for path in (OUTPUT_FILE, ARCHIVE_FILE):
        if not path.exists():
            continue
        try:
            records.extend(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    titles = {}
    for record in records:
        doi = normalize_doi(record.get("doi"))
        title = record.get("title")
        if doi and title and ("<sub>" in title or "<sup>" in title):
            titles[doi.lower()] = clean_title(title)
    return titles

PREVIOUS_TITLES: dict[str, str] = {}

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
    aliases_by_member = {}
    for member in team:
        oid = normalize_orcid(member.get("orcid"))
        if oid:
            by_orcid[oid] = member["name"]

        member_aliases = set()
        for alias in [member["name"], *member.get("aliases", [])]:
            normalized = normalize_text(alias)
            if normalized:
                aliases[normalized] = member["name"]
                member_aliases.add(normalized)

        aliases_by_member[member["name"]] = member_aliases

    return by_orcid, aliases, aliases_by_member

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
            f"type:article|review"
        )
        params = {
            "filter": filters,
            "sort": "publication_date:desc",
            "per_page": "200",
            "page": "1",
            "select": "id,doi,title,authorships,primary_location,biblio,type,publication_date,publication_year,open_access,best_oa_location,awards",
        }
        if OPENALEX_API_KEY:
            params["api_key"] = OPENALEX_API_KEY

        print(f"Consultando OpenAlex: {member['name']} ({orcid})")
        # OpenAlex dates early-online articles before their final journal issue.
        # Discover the full history, then apply the bibliographic date in Crossref.
        # Se recorren todas las páginas para no quedarse en los primeros 200 trabajos.
        # Paginación por número de página (page=): desde octubre de 2026 OpenAlex
        # exige API key para paginar con cursor= (HTTP 401 a partir de la 2.ª página).
        # page= funciona sin clave hasta 10 000 resultados, de sobra por autor.
        while True:
            url = f"{OPENALEX_BASE}/works?{urlencode(params)}"
            payload = fetch_json(url)
            results = payload.get("results", [])
            for work in results:
                works[openalex_work_key(work)] = work
            count = (payload.get("meta") or {}).get("count") or 0
            page = int(params["page"])
            seen = page * int(params["per_page"])
            if not results or seen >= count or seen >= 10_000:
                break
            params["page"] = str(page + 1)
            time.sleep(0.15)
        queried += 1

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
        msg = fetch_json(url, retries=4).get("message", {})
    except Exception as exc:
        print(f"  Aviso: Crossref no disponible para {doi}: {exc}")
        return {}

    dates = {}
    for key in ("published-online", "published-print", "published", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts")
        if parts and parts[0]:
            parsed = date_from_parts(parts[0])
            if parsed:
                dates[key] = parsed

    # Prefer the final issue date, not the earliest online appearance.
    # Online-only journals may supply their bibliographic year in published/issued.
    has_issue = bool(msg.get("volume") or msg.get("issue"))
    if has_issue:
        pub_date = (dates.get("published-print") or dates.get("published")
                    or dates.get("issued") or dates.get("published-online"))
    else:
        pub_date = (dates.get("published-online") or dates.get("published")
                    or dates.get("issued") or dates.get("published-print"))
    online_date = dates.get("published-online")
    # Fecha de registro del DOI en Crossref. Algunas editoriales (Elsevier) no
    # depositan published-online y solo indican el número futuro; "created"
    # aproxima entonces la fecha en que el artículo se hizo público.
    created_date = dates.get("created")

    authors = []
    for author in msg.get("author", []) or []:
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        full = " ".join(x for x in (given, family) if x)
        if full:
            authors.append(full)

    titles = msg.get("title") or []
    journals = msg.get("container-title") or []

    # Códigos de financiación depositados por la editorial (sección de agradecimientos).
    awards = []
    for funder in msg.get("funder", []) or []:
        awards.extend(a for a in (funder.get("award") or []) if a)
    licenses = [
        lic.get("URL") for lic in (msg.get("license") or [])
        if "creativecommons.org" in (lic.get("URL") or "")
    ]

    return {
        "title": titles[0] if titles else None,
        "authors": authors,
        "journal": html.unescape(journals[0]) if journals else None,
        "awards": awards,
        "license": licenses[0] if licenses else None,
        "publicationDate": pub_date.isoformat() if pub_date else None,
        "onlinePublicationDate": online_date.isoformat() if online_date else None,
        "createdDate": created_date.isoformat() if created_date else None,
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
    aliases_by_member: dict[str, set[str]],
    min_date: date = MIN_PUBLICATION_DATE,
) -> dict | None:
    doi = normalize_doi(work.get("doi"))
    if not doi:
        return None
    if doi.lower() in excluded_dois:
        return None

    meta = crossref_metadata(doi)
    previous = PREVIOUS_RECORDS.get(doi.lower())
    if not meta and previous:
        meta = previous_as_meta(previous)
    pub_date = None

    if meta.get("publicationDate"):
        try:
            pub_date = date.fromisoformat(meta["publicationDate"])
        except ValueError:
            pass

    pub_date = pub_date or fallback_openalex_date(work)
    if not pub_date or pub_date < min_date:
        return None

    # Preserve the earliest known online/public appearance separately. OpenAlex
    # can retain the exact online date when Crossref only supplies the issue year.
    online_dates = [d for d in (fallback_openalex_date(work),
                    date.fromisoformat(meta["onlinePublicationDate"])
                    if meta.get("onlinePublicationDate") else None) if d]
    online_date = min(online_dates) if online_dates else None

    # Número de revista con fecha futura: si el artículo ya es público, se muestra
    # y ordena por su fecha online hasta que llegue la fecha del número.
    issue_date = None
    if pub_date > MAX_PUBLICATION_DATE:
        # Sin fecha online pasada (Elsevier solo deposita el número futuro): usar
        # la fecha de registro del DOI en Crossref como aproximación.
        if (not online_date or online_date > MAX_PUBLICATION_DATE) and meta.get("createdDate"):
            created = date.fromisoformat(meta["createdDate"])
            if created <= MAX_PUBLICATION_DATE:
                online_date = created
        if not online_date or online_date > MAX_PUBLICATION_DATE:
            return None
        issue_date = pub_date
        pub_date = online_date

    oa_authors = [
        (a.get("author") or {}).get("display_name")
        for a in work.get("authorships", [])
        if (a.get("author") or {}).get("display_name")
    ]
    rendered_authors = meta.get("authors") or oa_authors

    # Store the exact author strings used in the rendered bibliography.
    # This lets the frontend highlight "Omar E. Solis" while groupAuthors
    # keeps the canonical identity "Omar Eduardo Solis Luna".
    group_author_display_names = []
    group_members = []
    for author in rendered_authors:
        normalized_author = normalize_text(author)
        member = next(
            (m for m in group_authors if normalized_author in aliases_by_member.get(m, set())),
            None,
        )
        if member:
            group_author_display_names.append(author)
            group_members.append({"name": member, "display": author})

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    biblio = work.get("biblio") or {}

    # Acceso abierto según OpenAlex (solo se guarda si hay una versión legible).
    oa = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}
    open_access = None
    if oa.get("is_oa") and (best.get("landing_page_url") or best.get("pdf_url") or oa.get("oa_url")):
        open_access = {
            "status": oa.get("oa_status"),
            "url": best.get("landing_page_url") or oa.get("oa_url"),
            "pdf": best.get("pdf_url"),
            "version": best.get("version"),
        }

    openalex_awards = []
    for award in work.get("awards") or []:
        for key in ("funder_award_id", "award_id", "display_name"):
            if award.get(key):
                openalex_awards.append(str(award[key]))

    return {
        "title": clean_title(meta.get("title")) or PREVIOUS_TITLES.get(doi.lower()) or clean_title(work.get("title")),
        "authors": rendered_authors,
        "groupAuthors": group_authors,
        "groupAuthorDisplayNames": group_author_display_names,
        "groupMembers": group_members,
        "journal": meta.get("journal") or html.unescape(source.get("display_name") or "") or None,
        "publicationDate": pub_date.isoformat(),
        "onlinePublicationDate": online_date.isoformat() if online_date else None,
        "issueDate": issue_date.isoformat() if issue_date else None,
        "year": pub_date.year,
        "volume": meta.get("volume") or biblio.get("volume"),
        "issue": meta.get("issue") or biblio.get("issue"),
        "pages": meta.get("pages") or biblio.get("first_page"),
        "doi": doi,
        "url": f"https://doi.org/{doi}",
        "type": "review" if work.get("type") == "review" else "article",
        "image": None,
        "openAccess": open_access,
        "license": meta.get("license"),
        "awards": sorted(set((meta.get("awards") or []) + openalex_awards)),
        "_previousProjects": (previous or {}).get("projects") or [],
    }

def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def normalize_grant(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").upper()
    return re.sub(r"[^A-Z0-9]", "", value)

def match_projects(awards: list[str], projects: list[dict]) -> list[str]:
    """Proyectos cuyo código de financiación aparece en los agradecimientos."""
    codes = {normalize_grant(a) for a in awards if a}
    found = []
    for project in projects:
        for grant in project.get("grants", []):
            g = normalize_grant(grant)
            if g and any(g == c or (len(g) >= 8 and g in c) for c in codes):
                found.append(project["key"])
                break
    return found

def plain_title(value: str | None) -> str:
    return re.sub(r"<[^>]+>", "", value or "").lower()

def apply_extras(record: dict, extras: dict, projects: list[dict]) -> dict:
    """Añade líneas, proyectos, destacado y perfiles del equipo (datos editoriales)."""
    doi = record["doi"].lower()
    manual = (extras.get("publications") or {}).get(doi, {})

    themes = manual.get("themes")
    if not themes:
        title = plain_title(record.get("title"))
        themes = [
            theme["key"] for theme in extras.get("themes", [])
            if any(k.lower() in title for k in theme.get("keywords", []))
        ]
    record["themes"] = themes

    linked = match_projects(record.pop("awards", []), projects)
    # Vínculos ya verificados en una ejecución anterior (si Crossref falla ahora).
    for key in record.pop("_previousProjects", []):
        if key not in linked:
            linked.append(key)
    for key in manual.get("projects", []):
        if key not in linked:
            linked.append(key)
    record["projects"] = [k for k in linked if k not in manual.get("excludeProjects", [])]

    record["featured"] = manual.get("featured")
    if manual.get("image"):
        record["image"] = manual["image"]
    for key in ("data", "code"):
        if manual.get(key):
            record[key] = manual[key]

    members = extras.get("members") or {}
    for member in record.get("groupMembers", []):
        member["profile"] = (members.get(member["name"]) or {}).get("profile")
    return record

def sort_records(records: list[dict]) -> list[dict]:
    return sorted(
        records,
        key=lambda r: (r.get("publicationDate") or "", r.get("title") or ""),
        reverse=True,
    )

def write_json(path: Path, records: list[dict]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)

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
    PREVIOUS_TITLES.update(load_previous_titles())
    PREVIOUS_RECORDS.update(load_previous_records())
    excluded_dois = load_excluded_dois()
    by_orcid, aliases, aliases_by_member = build_member_indexes(team)

    try:
        works = discover_works(team)
    except Exception as exc:
        print(f"\nERROR: no se ha modificado publications.json.\n{exc}", file=sys.stderr)
        raise SystemExit(1)

    candidates = []
    for work in works.values():
        group_authors = identify_group_authors(work, by_orcid, aliases)
        if len(group_authors) < MIN_GROUP_AUTHORS:
            continue
        candidates.append((work, group_authors))

    def build_record(candidate):
        work, group_authors = candidate
        return make_record(work, group_authors, excluded_dois, aliases_by_member,
                           min_date=ARCHIVE_MIN_DATE)

    print(f"Comprobando fechas bibliográficas de {len(candidates)} trabajos del grupo.")
    detected = []
    # Full-history discovery requires more Crossref lookups. Bound concurrency
    # so the weekly job remains practical without flooding the metadata service.
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index, record in enumerate(pool.map(build_record, candidates), 1):
            if record:
                detected.append(record)
            if index % 50 == 0:
                print(f"  Revisados {index}/{len(candidates)} trabajos.")

    by_doi = {r["doi"].lower(): r for r in detected}
    deduplicated = remove_wiley_language_duplicates(list(by_doi.values()))
    extras = load_json(EXTRAS_FILE, {})
    projects = load_json(PROJECTS_FILE, [])
    deduplicated = [apply_extras(r, extras, projects) for r in deduplicated]
    main_start = MIN_PUBLICATION_DATE.isoformat()
    final_records = sort_records([r for r in deduplicated if r["publicationDate"] >= main_start])
    archive_records = sort_records([r for r in deduplicated if r["publicationDate"] < main_start])

    if not final_records:
        print(
            "\nERROR: no se detectó ninguna publicación válida; "
            "por seguridad no se sobrescribe el JSON existente.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    write_json(OUTPUT_FILE, final_records)
    write_json(ARCHIVE_FILE, archive_records)

    print(f"\nActualización completada: {len(final_records)} publicaciones "
          f"(+ {len(archive_records)} de 2025 en {ARCHIVE_FILE.name}).")
    for record in final_records[:5]:
        print(f" - {record['publicationDate']} | {record['title']}")

if __name__ == "__main__":
    main()
