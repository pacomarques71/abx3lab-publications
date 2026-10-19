#!/usr/bin/env python3
"""Enriquecimiento automático de publicaciones: financiación verificable e imágenes con licencia.
Ejecutar DESPUÉS de update_publications.py. No modifica contenidos de WordPress.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
IMAGES = ROOT / "images"
EVIDENCE = DATA / "publication_evidence.json"
RAW_IMAGES = "https://raw.githubusercontent.com/pacomarques71/abx3lab-publications/main/images/"
KEY = os.getenv("OPENALEX_API_KEY", "").strip()
ELSEVIER_KEY = os.getenv("ELSEVIER_API_KEY", "").strip()
HEADERS = {"User-Agent": "ABX3LabPublications/2.0 (scholarly metadata enrichment)",
           "Accept": "text/html,application/xml,application/pdf,image/*;q=0.8"}
TIMEOUT = 18
MAX_PDF = 24 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
CHECK_DAYS = 60
SECTION_NAMES = re.compile(r"acknowledg|funding|financial support|grant support|financial assistance|supporting fund|agradecim|financiaci", re.I)
FIGURE_CAPTION = re.compile(r"^\s*(?:fig(?:ure)?\.?\s*1\b|figure\s+1\b)", re.I)
ALLOWED_IMAGE_LICENSES = ("cc-by", "cc0", "public-domain", "cc-by-sa")


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalize(value):
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", str(value or "")).upper())


def grants_in_text(text, projects):
    """Match full grant IDs with punctuation variants, not arbitrary project names or substrings."""
    compact = normalize(text)
    found = {}
    for project in projects:
        for identifier in project.get("grants", []):
            grant = normalize(identifier)
            if not grant:
                continue
            for match in re.finditer(re.escape(grant), compact):
                before = compact[match.start() - 1:match.start()] if match.start() else ""
                after = compact[match.end():match.end() + 1]
                # Numeric ERC identifiers must not be part of longer numbers.
                if grant.isdigit() and (before.isdigit() or after.isdigit()):
                    continue
                # Avoid matching C31 in C310 or a truncated textual identifier.
                if not grant.isdigit() and (after.isdigit() and grant[-1].isdigit()):
                    continue
                found[project["key"]] = identifier
                break
            if project["key"] in found:
                break
    # Exact, distinctive project names explicitly written in a funding section
    # are valid evidence even if no agreement number is mentioned.
    # This is NEVER run against titles, abstracts, references or topic descriptions.
    for project in projects:
        if project["key"] in found:
            continue
        for alias in project.get("fundingAliases", []):
            if len(alias) < 6:
                continue
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", text or "", re.I):
                found[project["key"]] = alias
                break
    return found


def request_url(url, max_bytes=MAX_PDF, accept=None, extra_headers=None):
    """Fetch bounded public HTTP(S) resources; never fetch private-network URLs."""
    from ipaddress import ip_address
    p = urlparse(url)
    if p.scheme not in ("https", "http") or not p.hostname:
        return None
    if p.hostname in ("localhost",) or p.hostname.endswith((".local", ".internal")):
        return None
    try:
        if not ip_address(p.hostname).is_global:
            return None
    except ValueError:
        pass
    try:
        r = requests.get(url, headers={**HEADERS, **({"Accept": accept} if accept else {}), **(extra_headers or {})},
                         timeout=TIMEOUT, stream=True, allow_redirects=True)
        final = urlparse(r.url)
        if final.scheme not in ("http", "https") or not final.hostname:
            r.close()
            return None
        if r.status_code >= 400:
            print("  Fuente no disponible:", p.hostname, "HTTP", r.status_code, flush=True)
        r.raise_for_status()
        content = bytearray()
        for block in r.iter_content(65536):
            content.extend(block)
            if len(content) > max_bytes:
                r.close()
                return None
        r.close()
        return bytes(content), r.url, r.headers.get("Content-Type", "")
    except (requests.RequestException, ValueError) as exc:
        print("  Descarga fallida:", p.hostname, type(exc).__name__, flush=True)
        return None


def section_text_from_html(html_bytes):
    soup = BeautifulSoup(html_bytes, "html.parser")
    output = []
    for meta in soup.select("meta[name],meta[property]"):
        name = str(meta.get("name") or meta.get("property") or "").lower()
        if any(k in name for k in ("citation_grant", "citation_fund", "dc.description.sponsorship", "funding")):
            output.append(meta.get("content") or "")
    for node in soup.find_all(re.compile("^h[1-6]$")):
        if not SECTION_NAMES.search(node.get_text(" ", strip=True)):
            continue
        section = node.find_parent(["section", "article"])
        if section and len(section.get_text(" ", strip=True)) < 12000:
            output.append(section.get_text(" ", strip=True)[:8000])
        else:
            chunks = []
            for item in node.next_elements:
                if getattr(item, "name", None) in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    break
                if getattr(item, "name", None) in ("p", "li"):
                    chunks.append(item.get_text(" ", strip=True))
                if len(" ".join(chunks)) > 9000:
                    break
            output.append(" ".join(chunks))
    # Some journals use divs rather than heading elements.
    for block in soup.select("[id*=acknowledg], [id*=funding], [class*=acknowledg], [class*=funding]")[:20]:
        content = block.get_text(" ", strip=True)
        if 15 <= len(content) <= 9000:
            output.append(content)
    return "\n".join(dict.fromkeys(s for s in output if s))


def graphical_abstract_from_html(html_bytes, base_url):
    soup = BeautifulSoup(html_bytes, "html.parser")
    for candidate in soup.select("figure, div, section")[:2500]:
        marker = " ".join(str(candidate.get(k, "")) for k in ("class", "id", "aria-label"))
        if not re.search(r"(graphical.{0,8}abstract|toc[-_ ]?(image|graphic)|abstract[-_ ]?graphic)", marker, re.I):
            continue
        img = candidate.find("img")
        if img:
            src = img.get("data-src") or img.get("src") or img.get("data-original")
            if src:
                return urljoin(base_url, src), "graphical-abstract"
    for meta in soup.select("meta[name], meta[property]"):
        key = (meta.get("name") or meta.get("property") or "").lower()
        if "graphical" in key or "toc_image" in key:
            u = meta.get("content")
            if u and u.startswith(("http", "/")):
                return urljoin(base_url, u), "graphical-abstract"
    return None, None


def text_from_tei(xml_bytes):
    """Read funding sections in both modern TEI and legacy wrapped TEI."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""
    def name(e):
        return e.tag.rsplit("}", 1)[-1].lower()
    fragments = []
    for elem in root.iter():
        tag = name(elem)
        if tag not in ("div", "section", "sec", "note", "ack", "acknowledgement", "acknowledgment", "acknowledgments", "funding-group", "funding-statement"):
            continue
        heading = " ".join(" ".join(h.itertext()) for h in elem if name(h) in ("head", "title", "section-title"))
        kind = " ".join([elem.get("type", ""), elem.get("subtype", ""), heading])
        if tag in ("ack", "acknowledgement", "acknowledgment", "acknowledgments", "funding-group", "funding-statement") or SECTION_NAMES.search(kind):
            fragments.append(" ".join(elem.itertext())[:14000])
    return "\n".join(dict.fromkeys(fragments))


def metadata_licenses(rec, oa_work):
    """Only images from publications with an explicit reusable licence are cached."""
    raw = str(rec.get("license") or "").lower()
    best = (oa_work.get("best_oa_location") or {}).get("license", "")
    primary = (oa_work.get("primary_location") or {}).get("license", "")
    licences = [raw, str(best).lower(), str(primary).lower()]
    for lic in licences:
        for allowed in ALLOWED_IMAGE_LICENSES:
            if allowed in lic or allowed.replace("-", "/") in lic or (
                allowed == "cc-by" and "creativecommons.org/licenses/by/" in lic
            ) or (allowed == "cc-by-sa" and "creativecommons.org/licenses/by-sa/" in lic):
                # Avoid NC/ND licenses: cropping/redistributing may be restricted.
                if "nc" not in lic and "nd" not in lic:
                    return lic
    return None


def extract_image_to_webp(blob, path):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not blob or len(blob) > MAX_IMAGE:
        return False
    try:
        with Image.open(io.BytesIO(blob)) as original:
            img = ImageOps.exif_transpose(original)
            if img.width < 250 or img.height < 150 or img.width / img.height > 5:
                return False
            if img.width * img.height > 30000000:
                return False
            img = img.convert("RGB")
            img.thumbnail((768, 768), Image.Resampling.LANCZOS)
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path, "WEBP", quality=82, method=5)
        return True
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        return False


def first_figure_from_pdf(pdf_bytes):
    """Extract a raster figure near the *Figure 1* caption; never use a random publisher logo."""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in list(doc)[:7]:
            blocks = page.get_text("blocks")
            captions = [b for b in blocks if len(b) > 4 and b[6] == 0 and FIGURE_CAPTION.search(b[4])]
            if not captions:
                continue
            caption = captions[0]
            images = []
            for info in page.get_images(full=True):
                for rect in page.get_image_rects(info[0]):
                    dist = caption[1] - rect.y1
                    if -15 <= dist < 260 and rect.width >= 125 and rect.height >= 85:
                        images.append((abs(dist), info[0]))
            if images:
                images.sort()
                png = doc.extract_image(images[0][1])
                doc.close()
                return png.get("image")
            # Vector figures do not have an embedded bitmap. Render only a
            # graphics-rich region immediately above the Figure 1 caption,
            # rejecting ordinary columns of text to avoid accidental screenshots.
            try:
                width = page.rect.width
                left_col = caption[0] < width / 2
                two_columns = (caption[2] - caption[0]) < width * .62
                if two_columns:
                    x0 = 30 if left_col else width / 2 + 5
                    x1 = width / 2 - 5 if left_col else width - 30
                else:
                    x0, x1 = 30, width - 30
                y1 = max(80, caption[1] - 8)
                y0 = max(35, y1 - 225)
                clip = fitz.Rect(x0, y0, x1, y1)
                drawings = sum(1 for d in page.get_drawings()
                               if d["rect"].intersects(clip))
                body = page.get_text("text", clip=clip)
                if drawings >= 12 and len(body) < 500 and clip.height > 120:
                    out = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8),
                                          clip=clip, alpha=False).tobytes("png")
                    doc.close()
                    return out
            except (RuntimeError, ValueError, OSError):
                pass
        doc.close()
    except (ImportError, ValueError, RuntimeError, OSError):
        return None
    return None



def elsevier_article_funding(doi):
    """Official Elsevier XML TDM API, optional authenticated access."""
    if not ELSEVIER_KEY or not doi.lower().startswith("10.1016/"):
        return None
    url = "https://api.elsevier.com/content/article/doi/" + quote(doi, safe="/") + "?httpAccept=text/xml"
    res = request_url(
        url, 7_000_000, "application/xml,text/xml",
        extra_headers={"X-ELS-APIKey": ELSEVIER_KEY}
    )
    if not res:
        return None
    tx = text_from_tei(res[0])
    return ("elsevier-tdm", tx, "https://doi.org/" + doi) if tx else None


def accessible_pdf_candidates(work, rec):
    """Use repository copies, not just the publisher's often bot-blocked PDF link."""
    urls = [(rec.get("openAccess") or {}).get("pdf")]
    for location in [work.get("best_oa_location") or {}, work.get("primary_location") or {}] + (work.get("locations") or []):
        if not isinstance(location, dict):
            continue
        for key in ("pdf_url",):
            urls.append(location.get(key))
    # Semantic Scholar often lists a different public OA copy (including preprints).
    doi = rec.get("doi", "")
    if doi:
        res = request_url(
            "https://api.semanticscholar.org/graph/v1/paper/DOI:"
            + quote(doi, safe="/") + "?fields=openAccessPdf,externalIds", 250000, "application/json"
        )
        if res:
            try:
                j = json.loads(res[0])
                pdf = j.get("openAccessPdf") or {}
                if isinstance(pdf, dict):
                    urls.append(pdf.get("url"))
            except (ValueError, TypeError, AttributeError):
                pass
    unique = []
    for url in urls:
        if url and url.startswith(("https://", "http://")) and url not in unique:
            unique.append(url)
    return unique[:7]


def download_publisher_page(doi):
    result = request_url("https://doi.org/" + quote(doi, safe="/"), max_bytes=3_000_000,
                         accept="text/html")
    if result and ("html" in result[2].lower() or b"<html" in result[0][:2000].lower()):
        return result
    return None


def openalex_work(doi):
    url = "https://api.openalex.org/works/https://doi.org/" + quote(doi, safe="/")
    if KEY:
        url += "?api_key=" + quote(KEY)
    res = request_url(url, 800000, "application/json")
    try:
        return json.loads(res[0]) if res else {}
    except (ValueError, TypeError):
        return {}



def openaire_grants(doi, projects):
    """OpenAIRE Graph: linked grants for this exact DOI (never text-topic inference)."""
    url = ("https://api.openaire.eu/graph/v4/research-products?"
           "filter=" + quote("ids.doi:" + doi, safe=":") + "&page_size=2")
    res = request_url(url, 2_000_000, "application/json")
    if not res:
        return []
    try:
        results = json.loads(res[0]).get("results") or []
    except (ValueError, TypeError, AttributeError):
        return []
    found = []
    for entry in results:
        for grant in entry.get("grants") or []:
            if not isinstance(grant, dict):
                continue
            codes = [str(grant.get(k) or "") for k in ("code", "grantCode", "projectCode", "number")]
            for code in codes:
                if not code:
                    continue
                for project, expected in grants_in_text(code, projects).items():
                    ev = {"project": project, "grant": expected, "source": "openaire",
                          "url": res[1].split("?")[0]}
                    if ev not in found:
                        found.append(ev)
    return found


def european_pmc_xml(doi):
    """JATS from Europe PMC OA corpus, a no-key alternative for eligible papers."""
    q = quote("DOI:" + doi)
    search = request_url("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
                         "query=" + q + "&format=json&pageSize=2", 400000, "application/json")
    if not search:
        return None
    try:
        entries = json.loads(search[0]).get("resultList", {}).get("result", [])
    except (ValueError, TypeError, AttributeError):
        return None
    for entry in entries:
        pmcid = entry.get("pmcid") or ""
        if not re.fullmatch(r"PMC\d+", pmcid) or entry.get("isOpenAccess") != "Y":
            continue
        res = request_url("https://www.ebi.ac.uk/europepmc/webservices/rest/" + pmcid + "/fullTextXML",
                          6_000_000, "application/xml")
        if res:
            return res
    return None


def extract_funding_from_pdf(pdf, url):
    out = []
    try:
        import fitz
        doc = fitz.open(stream=pdf, filetype="pdf")
        # In Elsevier papers funding can appear near the front of the manuscript,
        # rather than exclusively among its final pages.
        for pg in list(doc)[:40]:
            txt = pg.get_text(sort=True)
            header = re.search(
                r"(?im)^[ \t]*(?:acknowledg(?:e)?ments?|funding(?: information| statement)?|"
                r"financial support)(?:[ \t]*[:.]|[ \t]*\n)",
                txt
            )
            if header:
                body = txt[header.start():header.start() + 11000]
                body = re.split(
                    r"(?im)^[ \t]*(?:references|bibliography|supplementary materials?|"
                    r"author contributions|conflicts? of interest)(?:[ \t]*[:.]|[ \t]*\n)",
                    body, maxsplit=1
                )[0]
                out.append(("oa-pdf", body, url))
        doc.close()
    except (ImportError, RuntimeError, ValueError, OSError):
        pass
    return out


def enrich_entry(rec, projects, prev, extras):
    doi = rec["doi"].lower()
    manual = (extras.get("publications") or {}).get(doi, {})
    today = date.today().isoformat()
    cached_funding = prev.get("fundingEvidence", [])
    evidence = [e for e in cached_funding if e.get("project") and e.get("grant") and e.get("source")]
    for e in rec.get("fundingEvidence", []):
        if e not in evidence:
            evidence.append(e)
    revisit = True
    try:
        revisit = date.fromisoformat(prev.get("checked", "1900-01-01")) <= date.today() - timedelta(days=CHECK_DAYS)
    except ValueError:
        pass
    # Retry unresolved articles weekly, whether they have missing projects or images.
    if prev.get("fundingStatus") != "text-checked":
        revisit = True
    needs_picture = not manual.get("image") and not prev.get("image")
    work = {}
    page = None
    status = prev.get("fundingStatus") or "metadata-only"
    img_origin = prev.get("image")
    lic = prev.get("license")
    if revisit or needs_picture:
        work = openalex_work(doi)
        if not work:
            print("  OpenAlex DOI lookup empty:", doi, flush=True)
        page = download_publisher_page(doi)
        sources = []
        for ev in openaire_grants(doi, projects):
            if ev not in evidence:
                evidence.append(ev)
        official_xml = elsevier_article_funding(doi)
        if official_xml:
            sources.append(official_xml)
        if page:
            tx = section_text_from_html(page[0])
            if tx:
                sources.append(("publisher-html", tx, page[1]))
        if KEY and (work.get("id") or rec.get("openalexId")):
            wid = str(work.get("id") or rec["openalexId"]).rsplit("/", 1)[-1]
            xml = request_url("https://content.openalex.org/works/" + wid + ".grobid-xml?api_key=" + quote(KEY), 6_000_000)
            if xml:
                tx = text_from_tei(xml[0])
                if tx:
                    sources.append(("openalex-tei", tx, xml[1].split("?")[0]))
        # Prefer publisher/repository OA copies and public preprints, then
        # authenticated OpenAlex's PDF archive if one exists.
        pdf = None
        pdfurl = None
        urls = accessible_pdf_candidates(work, rec)
        wid = str(work.get("id") or rec.get("openalexId") or "").rsplit("/", 1)[-1]
        if KEY and re.fullmatch(r"W\d+", wid):
            urls.append("https://content.openalex.org/works/" + wid + ".pdf?api_key=" + quote(KEY))
        for candidate in urls:
            response = request_url(candidate, MAX_PDF, "application/pdf")
            if response and response[0][:4] == b"%PDF":
                pdf, pdfurl = response[0], candidate.split("?")[0]
                break
        if pdf is not None:
            sources.extend(extract_funding_from_pdf(pdf, pdfurl))
        if not sources:
            # Another legal OA full-text channel (JATS) for eligible papers.
            pmc = european_pmc_xml(doi)
            if pmc:
                tx = text_from_tei(pmc[0])
                if tx:
                    sources.append(("europe-pmc-jats", tx, pmc[1]))
        if sources:
            status = "text-checked"
            for name, tx, url in sources:
                for key, grant in grants_in_text(tx, projects).items():
                    e = {"project": key, "grant": grant, "source": name, "url": url}
                    if e not in evidence:
                        evidence.append(e)
        elif revisit:
            status = "metadata-only"
        if needs_picture:
            lic = metadata_licenses(rec, work)
            if lic:
                blob = None
                typ = None
                srcurl = None
                if page:
                    srcurl, typ = graphical_abstract_from_html(page[0], page[1])
                    if srcurl:
                        img_result = request_url(srcurl, max_bytes=MAX_IMAGE, accept="image/*")
                        if img_result and img_result[2].lower().startswith("image/"):
                            blob = img_result[0]
                        else:
                            srcurl, typ = None, None
                if blob is None and pdf:
                    blob = first_figure_from_pdf(pdf)
                    if blob:
                        srcurl, typ = pdfurl, "figure-1"
                if blob:
                    file_name = "article-" + hashlib.sha256(doi.encode()).hexdigest()[:20] + ".webp"
                    target = IMAGES / file_name
                    if extract_image_to_webp(blob, target):
                        img_origin = {"url": RAW_IMAGES + file_name, "source": srcurl,
                                      "type": typ, "license": lic, "doi": doi}
    exclude = set(manual.get("excludeProjects", []))
    keys = set(rec.get("projects") or []) | {e["project"] for e in evidence}
    keys |= set(manual.get("projects", []))
    rec["projects"] = [p["key"] for p in projects if p["key"] in keys and p["key"] not in exclude]
    # Evidence contains codes, sources and links, never complete copyrighted acknowledgement text.
    rec["fundingEvidence"] = sorted(evidence, key=lambda e: (e["project"], e["source"], e["grant"]))
    rec["fundingStatus"] = status
    if manual.get("image"):
        rec["image"] = manual["image"]
    elif img_origin:
        rec["image"] = img_origin["url"]
        rec["imageSource"] = img_origin["source"]
        rec["imageType"] = img_origin["type"]
        rec["imageLicense"] = img_origin["license"]
    audit = {"checked": today if (revisit or needs_picture) else prev.get("checked", today),
             "fundingStatus": status, "fundingEvidence": rec["fundingEvidence"],
             "image": img_origin, "license": lic}
    return rec, audit


def main():
    projects = load(DATA / "projects.json", [])
    extras = load(DATA / "publication_extras.json", {})
    cache = load(EVIDENCE, {})
    updated = dict(cache)
    total, images = 0, 0
    for filename in ("publications.json", "publications_2025.json"):
        path = DATA / filename
        records = load(path, [])
        for rec in records:
            old_img = rec.get("image")
            doi = rec.get("doi", "").lower()
            if not doi:
                continue
            new_rec, evidence = enrich_entry(rec, projects, cache.get(doi, {}), extras)
            rec.update(new_rec)
            updated[doi] = evidence
            total += 1
            if rec.get("image") and not old_img:
                images += 1
            print(doi, "projects=", ",".join(rec["projects"]) or "-",
                  "image=", bool(rec.get("image")), "funding=", rec["fundingStatus"], flush=True)
        save(path, records)
    save(EVIDENCE, updated)
    print(f"Enrichment: {total} publications, {images} newly linked images; automatic retry for unresolved cases.")


if __name__ == "__main__":
    main()
