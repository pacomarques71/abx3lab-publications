#!/usr/bin/env python3
"""Enriquecimiento automático de publicaciones: financiación verificable e imágenes con licencia.
Ejecutar DESPUÉS de update_publications.py. No modifica contenidos de WordPress.
"""
from __future__ import annotations

import hashlib
import html
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
WILEY_TDM_TOKEN = os.getenv("WILEY_TDM_TOKEN", "").strip()
HEADERS = {"User-Agent": "ABX3LabPublications/2.0 (scholarly metadata enrichment)",
           "Accept": "text/html,application/xml,application/pdf,image/*;q=0.8"}
TIMEOUT = 18
MAX_PDF = 24 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
CHECK_DAYS = 60
FUNDING_MATCHER_VERSION = 2  # increment when grant parsing semantics change
IMAGE_MATCHER_VERSION = 9  # 9: recuperar Figuras 1 de PMC perdidas por un fallo de Europe PMC; 8: figuras vectoriales altas completas (antes, solo 225 pt sobre el pie); 7: TOC/Figura 1 de PMC y manuscritos aceptados
ACS_TOC_MATCHER_VERSION = 2  # retry ACS TOCs independently of other image sources
SECTION_NAMES = re.compile(r"acknowledg|funding|financial support|grant support|financial assistance|supporting fund|agradecim|financiaci", re.I)
FIGURE_CAPTION = re.compile(r"^\s*(?:fig(?:ure)?\.?\s*1\b|figure\s+1\b)", re.I)
# Pie de la Figura 1 dentro de una línea de texto del PDF. Admite el número de
# línea de los manuscritos aceptados («12 Figure 1. …») y las letras de panel
# que PyMuPDF une al pie («a) b) Figure 1. …»). Exige que tras el 1 venga
# puntuación de pie o mayúscula, para no confundir el texto «Figure 1b shows»
# o «Figure 1 shows» con el pie.
FIGURE_ONE_LINE = re.compile(
    r"^\s*(?:\d{1,4}\s+)?(?:\(?[a-z]\)\s*)*(?:Fig(?:ure)?|FIG(?:URE)?)\.?\s*1"
    r"(?=\s*[.:|\u2013\u2014]|\s+[A-Z(]|\s*$)"
)
FIGURE_SCAN_PAGES = 20
ALLOWED_IMAGE_LICENSES = ("cc-by", "cc0", "public-domain", "cc-by-sa")
# Artículos de Wiley sin licencia Creative Commons (licencia estándar, con
# cesión de copyright o licencia exclusiva): el acuerdo de Wiley permite a los
# autores reutilizar figuras sin pedir permiso, sin modificarlas, sin fines
# comerciales y con el crédito completo. Como todos los artículos de la web los
# firman miembros del grupo, se admite su imagen con el aviso de copyright
# («© 2026 Wiley‑VCH GmbH»), que la web muestra en el borde inferior.
WILEY_STANDARD_LICENSE = "wiley-standard-author-reuse"
# Revistas de Wiley‑VCH (código de revista del DOI 10.1002/<código>.<número>).
WILEY_VCH_CODES = {
    "adfm", "adma", "aenm", "advs", "anie", "ange", "smll", "smtd", "solr",
    "sstr", "aelm", "adom", "admi", "aesr", "aisy", "adsu", "adts", "admt",
    "lpor", "cssc", "cphc", "celc", "cctc", "chem", "ejic", "ejoc", "batt",
    "ente", "pssa", "pssb", "pssr", "ppsc", "mame", "marc", "macp", "elsa",
    "cplu", "asia", "open", "ctpp", "zaac", "adem", "apxr", "smsc", "eem2",
}
# Aviso de copyright del PDF de Wiley: «© 2026 Wiley-VCH GmbH»,
# «© 2026 Wiley Periodicals LLC», «© 2026 John Wiley & Sons Ltd».
WILEY_COPYRIGHT = re.compile(
    r"(?:©|\(c\)|Copyright\s*©?)\s*((?:19|20)\d{2})\s+"
    r"(Wiley[\s\u2010-\u2015-]*VCH\s+(?:Verlag\s+)?GmbH(?:\s*&\s*Co\.\s*KGaA)?|"
    r"Wiley\s+Periodicals,?\s+LLC|John\s+Wiley\s*&\s*Sons,?\s+(?:Ltd|Inc)\.?)",
    re.I,
)


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
    """Find full identifiers across punctuation/PDF line wraps, preserving boundaries.

    A purely normalized string loses the distinction between "CNS...270 2026"
    and "CNS...2702026". Match in a compact string but map each matched
    character back to its actual source-text offset before testing boundaries.
    This also handles PDF fonts that insert spaces inside otherwise valid IDs.
    """
    raw = unicodedata.normalize("NFKC", str(text or ""))
    chars = []
    offsets = []
    for idx, char in enumerate(raw):
        for expanded in char.upper():
            if ("A" <= expanded <= "Z") or ("0" <= expanded <= "9"):
                chars.append(expanded)
                offsets.append(idx)
    compact = "".join(chars)
    found = {}
    for project in projects:
        for identifier in project.get("grants", []):
            grant = normalize(identifier)
            if not grant:
                continue
            for match in re.finditer(re.escape(grant), compact):
                first = offsets[match.start()]
                last = offsets[match.end() - 1]
                # Avoid accidentally merging codes from distant unrelated text.
                if last - first > max(90, len(grant) * 5):
                    continue
                before = raw[first - 1:first] if first else ""
                after = raw[last + 1:last + 2]
                if grant.isdigit():
                    # E.g. GA101122345 is acceptable, 91011223456 is not.
                    if before.isdigit() or after.isdigit():
                        continue
                else:
                    if (before and before.isascii() and before.isalnum()) or (
                            after and after.isascii() and after.isalnum()):
                        continue
                found[project["key"]] = identifier
                break
            if project["key"] in found:
                break
    # Aliases are read exclusively from extracted funding/acknowledgement
    # sections, never from titles/abstracts or arbitrary text.
    for project in projects:
        if project["key"] in found:
            continue
        for alias in project.get("fundingAliases", []):
            if len(alias) < 6:
                continue
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(alias)
                         + r"(?![A-Za-z0-9])", raw, re.I):
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
        section = node.find_parent("section")
        if section and SECTION_NAMES.search((section.get("id") or "") + " " + node.get_text(" ", strip=True)) and len(section.get_text(" ", strip=True)) < 12000:
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
    """Only explicit TOC/graphical-abstract art, not generic social-share images."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    marker = re.compile(
        r"(?:graphical|visual)[\s_-]*abstract|abstract[\s_-]*graphic|"
        r"(?:table[\s_-]*of[\s_-]*contents?|toc)[\s_-]*(?:graphic|image|figure|art)",
        re.I
    )
    def image_url(img):
        for attr in ("data-src", "data-original", "data-lazy-src", "src"):
            u = img.get(attr)
            if u and not u.startswith(("data:", "blob:")):
                return urljoin(base_url, u)
        pic = img.find_parent("picture")
        for node in ([img] + (pic.find_all("source") if pic else [])):
            srcset = node.get("data-srcset") or node.get("srcset") or ""
            entries = [x.strip().split()[0] for x in srcset.split(",") if x.strip()]
            if entries:
                return urljoin(base_url, entries[-1])
        return None
    for node in soup.select("figure, picture, div, section")[:2500]:
        marks = []
        for attr in ("class", "id", "aria-label"):
            value = node.get(attr, "")
            marks.append(" ".join(value) if isinstance(value, list) else str(value))
        caption = node.find("figcaption")
        if caption:
            marks.append(caption.get_text(" ", strip=True)[:100])
        if marker.search(" ".join(marks)):
            img = node.find("img")
            url = image_url(img) if img else None
            if url:
                return url, "graphical-abstract"
    # ACS often labels the artwork with a "Visual Abstract" heading,
    # while the figure wrapper itself has no descriptive CSS class.
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if not re.fullmatch(r"(?:visual|graphical)\s+abstract\s*:?",
                            heading.get_text(" ", strip=True), flags=re.I):
            continue
        # A heading's immediately following block is the only trusted graphic.
        for sibling in list(heading.next_siblings)[:5]:
            if getattr(sibling, "name", None) in ("h1", "h2", "h3", "h4", "h5", "h6"):
                break
            img = sibling if getattr(sibling, "name", None) == "img" else (
                sibling.find("img") if getattr(sibling, "name", None) else None)
            if img:
                url = image_url(img)
                if url:
                    return url, "graphical-abstract"
    for img in soup.select("img[alt], img[title]"):
        if marker.search((img.get("alt") or "") + " " + (img.get("title") or "")):
            url = image_url(img)
            if url:
                return url, "graphical-abstract"
    for meta in soup.select("meta[name], meta[property]"):
        key = (meta.get("name") or meta.get("property") or "").lower()
        if marker.search(key):
            url = meta.get("content")
            if url and url.startswith(("http://", "https://", "/")):
                return urljoin(base_url, url), "graphical-abstract"
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


def wiley_standard_terms(doi, rec, oa_work):
    """Artículo de Wiley sin ninguna licencia Creative Commons (ni siquiera NC/ND)."""
    if not str(doi or "").lower().startswith("10.1002/"):
        return False
    licences = " ".join(str(x or "").lower() for x in (
        rec.get("license"),
        (oa_work.get("best_oa_location") or {}).get("license"),
        (oa_work.get("primary_location") or {}).get("license"),
    ))
    return "creativecommons" not in licences and "cc-" not in licences


def _clean_holder(holder):
    holder = re.sub(r"\s+", " ", holder).strip().rstrip(".")
    if re.match(r"wiley[\s\u2010-\u2015-]*vch", holder, re.I):
        return "Wiley\u2011VCH GmbH"  # guion que no se parte al final de línea
    if re.match(r"wiley\s+periodicals", holder, re.I):
        return "Wiley Periodicals LLC"
    if re.match(r"john\s+wiley", holder, re.I):
        return "John Wiley & Sons Ltd"
    return holder


def wiley_copyright_from_pdf(pdf):
    """Lee el aviso de copyright de la versión publicada (primeras y última páginas)."""
    if not pdf:
        return None
    try:
        import fitz
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            pages = list(range(min(3, doc.page_count)))
            if doc.page_count > 3:
                pages.append(doc.page_count - 1)
            for i in pages:
                m = WILEY_COPYRIGHT.search(doc[i].get_text("text") or "")
                if m:
                    return f"\u00a9 {m.group(1)} {_clean_holder(m.group(2))}"
    except (ImportError, RuntimeError, ValueError, OSError):
        return None
    return None


def wiley_copyright(doi, rec, pdf=None):
    """Aviso de copyright para el crédito de la imagen: del PDF o, si no, por la revista."""
    from_pdf = wiley_copyright_from_pdf(pdf)
    if from_pdf:
        return from_pdf
    year = str(rec.get("onlinePublicationDate") or rec.get("publicationDate")
               or rec.get("year") or "")[:4]
    code = str(doi).lower().split("/", 1)[-1].split(".", 1)[0]
    holder = "Wiley\u2011VCH GmbH" if code in WILEY_VCH_CODES else "Wiley"
    return f"\u00a9 {year} {holder}" if year.isdigit() else f"\u00a9 {holder}"


def publication_image_filename(doi, blob):
    """Stable DOI and content hash, so new artwork always gets a fresh URL."""
    article = hashlib.sha256(doi.lower().encode("utf-8")).hexdigest()[:20]
    content = hashlib.sha256(blob).hexdigest()[:12]
    return f"article-{article}-{content}.webp"


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
            if img.mode in ("RGBA", "LA") or "transparency" in img.info:
                overlay = img.convert("RGBA")
                canvas = Image.new("RGB", overlay.size, "white")
                canvas.paste(overlay, mask=overlay.getchannel("A"))
                img = canvas
            else:
                img = img.convert("RGB")
            img.thumbnail((768, 768), Image.Resampling.LANCZOS)
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path, "WEBP", quality=82, method=5)
        return True
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        return False


def _render_pdf_clip(page, rect):
    """Render a PDF region on an opaque white sRGB canvas."""
    try:
        import fitz
        r = fitz.Rect(rect) & page.rect
        if r.width < 130 or r.height < 70 or r.width / r.height > 6.5:
            return None
        pix = page.get_pixmap(clip=r, matrix=fitz.Matrix(2, 2),
                              colorspace=fitz.csRGB, alpha=False)
        return pix.tobytes("png")
    except (ImportError, RuntimeError, ValueError, OSError):
        return None


def _toc_label_rects(page):
    """Detect ACS TOC headings at line granularity, including split PDF blocks.

    A whole-text-block exact match misses a real label when a PDF merges the
    heading with another text line. Require label-shaped lines, not incidental
    citations to graphical abstracts inside body paragraphs.
    """
    import fitz

    pattern = re.compile(
        r"(?ix)^\s*(?:"
        r"(?:graphical|visual)\s+abstract"
        r"|(?:(?:toc|table\s+of\s+contents?)(?:\s*\(toc\))?)"
        r"(?:\s+(?:graphic|image|figure|art|entry|illustration))?"
        r"|for\s+(?:the\s+)?(?:table\s+of\s+contents?|toc)"
        r"(?:\s+(?:use\s+)?only)?"
        r")\s*[:.\-–—]?\s*$"
    )
    labels = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", []):
            txt = re.sub(
                r"\s+", " ",
                " ".join(span.get("text", "") for span in line.get("spans", []))
            ).strip()
            if txt:
                lines.append((txt, fitz.Rect(line["bbox"])))
        # Some PDF layouts split 'For Table of Contents' and 'Only'.
        for n, (txt, rect) in enumerate(lines):
            variants = [(txt, rect)]
            if n+1 < len(lines):
                nxt, box = lines[n+1]
                variants.append((txt+" "+nxt, rect | box))
            for candidate, region in variants:
                if pattern.fullmatch(candidate):
                    labels.append(region)
                    break
    return labels


def _toc_image_regions(page):
    """Return placed artwork rectangles, not raw image xrefs or publisher logos."""
    rects = []
    for item in page.get_images(full=True):
        for rect in page.get_image_rects(item[0]):
            if rect.width >= 110 and rect.height >= 65:
                if not any(abs(rect.x0-r.x0) < 2 and abs(rect.y0-r.y0) < 2
                           and abs(rect.x1-r.x1) < 2 and abs(rect.y1-r.y1) < 2
                           for r in rects):
                    rects.append(rect)
    return rects


def _toc_crop(page, box, inset=5):
    import fitz
    clip = fitz.Rect(box.x0-inset, box.y0-inset,
                     box.x1+inset, box.y1+inset) & page.rect
    if clip.width < 100 or clip.height < 60:
        return None
    return _render_pdf_clip(page, clip)


def abstract_panel_toc_from_pdf(pdf_bytes):
    """Extract genuine TOC artwork embedded beside the first-page abstract.

    ACS PDF articles can include the graphical TOC inline in the abstract
    panel, with no "Graphical Abstract" heading or final TOC page. Match an
    embedded raster visually aligned with the first-page ABSTRACT heading,
    and exclude journal logos, decorative icons and numbered figures.
    """
    try:
        import fitz
        from PIL import Image
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if not len(doc):
                return None
            page = doc[0]
            heading_boxes = []
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    value = " ".join(span.get("text", "") for span in line.get("spans", []))
                    if re.match(r"(?i)^\s*ABSTRACT\s*:", value):
                        heading_boxes.append(fitz.Rect(line["bbox"]))
            if not heading_boxes:
                return None
            for heading in heading_boxes:
                candidates = []
                for meta in page.get_images(full=True):
                    xref = meta[0]
                    if meta[2] < 380 or meta[3] < 280:
                        continue
                    for rect in page.get_image_rects(xref):
                        if not (
                            rect.x0 >= page.rect.width * .57
                            and rect.width >= 110
                            and rect.height >= 100
                            and heading.y0-18 <= rect.y0 <= heading.y0+75
                            and rect.y1 < page.rect.height * .72
                            and .70 <= rect.width/rect.height <= 2.2
                        ):
                            continue
                        candidates.append((rect.get_area(), xref))
                if candidates:
                    _, xref = max(candidates)
                    data = doc.extract_image(xref)["image"]
                    with Image.open(io.BytesIO(data)) as picture:
                        if min(picture.size) < 280:
                            continue
                        converted = io.BytesIO()
                        picture.convert("RGB").save(converted, format="PNG")
                        return converted.getvalue()
    except (ImportError, ValueError, RuntimeError, OSError, KeyError):
        return None
    return None


def toc_graphic_from_pdf(pdf_bytes):
    """Locate publisher TOC artwork before considering Figure 1.

    Use exact graphical-abstract headings first, including split lines. ACS
    sometimes includes a separate final page with only the TOC artwork and
    no searchable label; accept that layout with conservative safeguards.
    """
    inline_toc = abstract_panel_toc_from_pdf(pdf_bytes)
    if inline_toc:
        return inline_toc
    try:
        import fitz
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            n_pages = len(doc)
            page_ids = sorted(set(range(min(4, n_pages))) |
                              set(range(max(0, n_pages-4), n_pages)))
            # Explicit headings always have priority over unlabelled layouts.
            for idx in page_ids:
                page = doc[idx]
                artworks = _toc_image_regions(page)
                for label_rect in _toc_label_rects(page):
                    # Do not select a random 'Figure 1' from a different
                    # column: require overlap with a nearby heading-centered
                    # strip extending above or below the heading.
                    nearby = []
                    for rect in artworks:
                        vertical_gap = max(0, label_rect.y0-rect.y1,
                                           rect.y0-label_rect.y1)
                        horizontal_overlap = min(rect.x1, label_rect.x1+260) - max(
                            rect.x0, label_rect.x0-260)
                        if vertical_gap <= 420 and horizontal_overlap > 0:
                            nearby.append((vertical_gap, -rect.get_area(), rect))
                    if nearby:
                        chosen = min(nearby, key=lambda t: (t[0], t[1]))[2]
                        png = _toc_crop(page, chosen)
                        if png:
                            return png
                    # A vector TOC is also possible. Do not include text-heavy
                    # page regions merely because they mention "TOC".
                    for direction in (1, -1):
                        box = (fitz.Rect(35, label_rect.y1+4,
                                         page.rect.width-35,
                                         min(page.rect.height-30, label_rect.y1+380))
                               if direction == 1 else
                               fitz.Rect(35, max(30, label_rect.y0-380),
                                         page.rect.width-35, label_rect.y0-4))
                        if box.is_empty or box.width < 100 or box.height < 65:
                            continue
                        vectors = [draw["rect"] for draw in page.get_drawings()
                                   if draw["rect"].intersects(box)
                                   and draw["rect"].width < page.rect.width*.97]
                        if len(vectors) < 22:
                            continue
                        region = fitz.Rect(min(v.x0 for v in vectors)-5,
                                           min(v.y0 for v in vectors)-5,
                                           max(v.x1 for v in vectors)+5,
                                           max(v.y1 for v in vectors)+5) & box
                        if len(page.get_text("text", clip=region)) > 200:
                            continue
                        png = _toc_crop(page, region)
                        if png:
                            return png

            # A standalone, uncaptioned image on a short last page is typical
            # of accepted ACS manuscripts. Require genuine page-level
            # isolation; don't reclassify ordinary figures as a TOC.
            if n_pages >= 2:
                for idx in range(n_pages-1, max(-1, n_pages-3), -1):
                    page = doc[idx]
                    visible_text = re.sub(r"\s+", " ", page.get_text("text")).strip()
                    isolated = (
                        len(visible_text) <= 160 and
                        not re.search(r"\b(?:fig(?:ure)?\.?\s*\d+|scheme\s*\d+|"
                                      r"references|bibliography|"
                                      r"supporting\s+information)\b",
                                      visible_text, re.I)
                    )
                    candidates = [
                        rect for rect in _toc_image_regions(page)
                        if (rect.width >= page.rect.width*.43
                            and rect.height >= 95
                            and rect.get_area() >= page.rect.get_area()*.075
                            and 1.1 <= rect.width/rect.height <= 6.5)
                    ] if isolated else []
                    if len(candidates) == 1:
                        png = _toc_crop(page, candidates[0])
                        if png:
                            return png
                    # Some ACS versions append an uncaptioned landscape TOC
                    # underneath references on the final PDF page. Search
                    # that region even if the full page has dense prose.
                    if len(visible_text) > 160 and idx == n_pages-1:
                        for rect in _toc_image_regions(page):
                            if (rect.y0 < page.rect.height*.51
                                or rect.width < page.rect.width*.52
                                or rect.height < 90
                                or rect.width/rect.height < 1.25):
                                continue
                            band = fitz.Rect(0, max(0, rect.y0-85),
                                             page.rect.width,
                                             min(page.rect.height, rect.y1+85))
                            neighbours = page.get_text("text", clip=band)
                            if re.search(r"(?i)\b(?:fig(?:ure)?\.?\s*\d+|"
                                         r"scheme\s*\d+|table\s*\d+)\b",
                                         neighbours):
                                continue
                            if len(page.get_text("text", clip=rect)) > 130:
                                continue
                            png = _toc_crop(page, rect)
                            if png:
                                return png
                    # A final-page TOC may also consist entirely of vectors.
                    if isolated and not candidates:
                        vectors = [draw["rect"] for draw in page.get_drawings()
                                   if 12 < draw["rect"].width < page.rect.width*.95
                                   and 7 < draw["rect"].height < page.rect.height*.9]
                        if len(vectors) >= 25:
                            box = fitz.Rect(min(v.x0 for v in vectors),
                                            min(v.y0 for v in vectors),
                                            max(v.x1 for v in vectors),
                                            max(v.y1 for v in vectors))
                            if (box.width >= page.rect.width*.42
                                and box.height >= 100
                                and 1.1 <= box.width/box.height <= 6.5):
                                png = _toc_crop(page, box)
                                if png:
                                    return png
    except (ImportError, ValueError, RuntimeError, OSError):
        return None
    return None


def diagnose_acs_toc_pdf(pdf_bytes):
    """Log only heading-level evidence for missing ACS TOCs; never store full PDFs."""
    if not pdf_bytes:
        return
    try:
        import fitz
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            pages = sorted(set(range(min(2, len(doc)))) |
                           set(range(max(0, len(doc) - 3), len(doc))))
            for index in pages:
                page = doc[index]
                headings = []
                for block in page.get_text("blocks"):
                    if len(block) < 7 or block[6] != 0:
                        continue
                    txt = " ".join(block[4].split())
                    if re.search(r"\b(?:TOC|graphical abstract|visual abstract|table of contents)\b",
                                 txt, re.I):
                        headings.append((round(block[1]), txt[:90]))
                images = [tuple(round(v) for v in rect)
                          for entry in page.get_images(full=True)
                          for rect in page.get_image_rects(entry[0])
                          if rect.width > 100 and rect.height > 65]
                print("  ACS TOC diagnostic page", index + 1, "of", len(doc),
                      "labels=", headings[:8], "images=", images[:10], flush=True)
    except (ImportError, RuntimeError, ValueError, OSError):
        pass


def _figure_one_caption(page):
    """Return (x0, y0, x1, y1) of the first Figure 1 caption line on a page.

    x comes from the text block (column width); y from the caption line itself,
    so a caption merged with panel labels or line numbers is located exactly.
    """
    try:
        data = page.get_text("dict")
    except (RuntimeError, ValueError):
        return None
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        bx0, _by0, bx1, _by1 = block["bbox"]
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if FIGURE_ONE_LINE.search(text):
                return (bx0, line["bbox"][1], bx1, line["bbox"][3])
    return None


def first_figure_from_pdf(pdf_bytes):
    """Extract a raster figure near the *Figure 1* caption; never use a random publisher logo."""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        # Los manuscritos aceptados (RSC, repositorios) llevan portada y texto a
        # doble espacio: la Figura 1 puede estar en la página 8 o 9.
        for page in list(doc)[:FIGURE_SCAN_PAGES]:
            caption = _figure_one_caption(page)
            if not caption:
                continue
            images = []
            for info in page.get_images(full=True):
                for rect in page.get_image_rects(info[0]):
                    dist = caption[1] - rect.y1
                    if -15 <= dist < 260 and rect.width >= 125 and rect.height >= 85:
                        images.append((abs(dist), info[0]))
            if images:
                images.sort()
                # PDF extract_image can turn alpha/CMYK overlays black and
                # discard adjacent labels. Render the image's page rectangle.
                chosen = images[0][1]
                rectangles = page.get_image_rects(chosen)
                closest = min(rectangles, key=lambda r: abs(caption[1]-r.y1))
                clip = fitz.Rect(closest.x0-6, closest.y0-6, closest.x1+6,
                                 min(caption[1]-4, closest.y1+6))
                png = _render_pdf_clip(page, clip)
                if png:
                    doc.close()
                    return png
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
                # Las figuras vectoriales altas (p. ej. Angewandte) ocupan más de
                # 225 pt: primero se prueba la región completa, desde el párrafo de
                # texto más cercano por encima del pie (o desde el margen superior),
                # y si no parece una figura, la región corta de siempre.
                top = 50  # por debajo de la cabecera de página de la revista
                for b in page.get_text("blocks"):
                    if (len(b) > 6 and b[6] == 0 and b[3] <= y1 and b[2] > x0 and b[0] < x1
                            and len(" ".join(str(b[4]).split())) >= 250):
                        top = max(top, b[3] + 4)
                drawn = page.get_drawings()
                for y0, max_text in ((max(top, y1 - 560), 1400), (max(35, y1 - 225), 500)):
                    clip = fitz.Rect(x0, y0, x1, y1)
                    drawings = sum(1 for d in drawn if d["rect"].intersects(clip))
                    body = page.get_text("text", clip=clip)
                    if drawings >= 12 and len(body) < max_text and clip.height > 120:
                        out = _render_pdf_clip(page, clip)
                        if out:
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


def wiley_tdm_pdf(doi):
    """Retrieve an authorized Wiley PDF for transient TDM only.

    The client token is sent exclusively to api.wiley.com. Wiley redirects
    successful downloads; follow the redirected public HTTPS URL WITHOUT
    forwarding the token to the CDN. Do not commit or cache the source PDF.
    """
    if not WILEY_TDM_TOKEN or not doi.lower().startswith("10.1002/"):
        return None
    url = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/" + quote(doi, safe="/")
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/pdf",
        "Wiley-TDM-Client-Token": WILEY_TDM_TOKEN,
    }
    try:
        with requests.get(url, headers=headers, timeout=TIMEOUT,
                          stream=True, allow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                destination = urljoin(url, response.headers.get("Location") or "")
                parsed = urlparse(destination)
                if parsed.scheme != "https" or not parsed.hostname:
                    return None
                # Do not send Wiley's TDM token to the redirected host.
                result = request_url(destination, MAX_PDF, "application/pdf")
                if result and result[0].startswith(b"%PDF"):
                    return result[0], url
                return None
            if response.status_code != 200:
                print("  Wiley TDM access:", response.status_code, "for", doi, flush=True)
                return None
            blob = bytearray()
            for block in response.iter_content(65536):
                blob.extend(block)
                if len(blob) > MAX_PDF:
                    return None
            if bytes(blob).startswith(b"%PDF"):
                return bytes(blob), url
            print("  Wiley TDM returned no PDF:", doi, flush=True)
    except requests.RequestException as exc:
        print("  Wiley TDM download error:", type(exc).__name__, "for", doi, flush=True)
    return None


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
    urls = ["https://doi.org/" + quote(doi, safe="/")]
    # An ACS DOI redirect may be refused while its public abstract endpoint
    # still serves the Visual Abstract. Try both, never treat PDFs as HTML.
    if doi.lower().startswith("10.1021/"):
        urls.append("https://pubs.acs.org/doi/abs/" + quote(doi, safe="/"))
    for url in urls:
        result = request_url(url, max_bytes=3_000_000, accept="text/html")
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

def abstract_from_openalex(work):
    """Reconstruct a DOI-specific OpenAlex abstract from its inverted index."""
    inv = work.get("abstract_inverted_index") or {}
    if not isinstance(inv, dict) or not inv:
        return ""
    try:
        maximum = max(pos for positions in inv.values() for pos in positions)
        if maximum > 10000:
            return ""
        words = [""] * (maximum + 1)
        for token, positions in inv.items():
            for pos in positions:
                words[pos] = token
        return " ".join(words).strip()
    except (ValueError, TypeError, IndexError, KeyError):
        return ""


def abstract_from_publisher(html_bytes):
    """Read explicitly labeled abstracts; social previews are not scientific abstracts."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    for meta in soup.select("meta[name], meta[property]"):
        key = (meta.get("name") or meta.get("property") or "").lower()
        if key in ("citation_abstract", "dc.description.abstract", "dc.description"):
            value = meta.get("content") or ""
            if len(value) >= 140:
                return html.unescape(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))
    for node in soup.select("section[id*=abstract], section[class*=abstract]")[:12]:
        val = node.get_text(" ", strip=True)
        val = re.sub(r"^Abstract\s*", "", val, flags=re.I)
        if 140 <= len(val) <= 7000:
            return val
    return ""


def discover_abstract(doi, work, page):
    """Find public article abstract: OpenAlex -> publisher -> Crossref -> Europe PMC."""
    value = abstract_from_openalex(work)
    if not value and page:
        value = abstract_from_publisher(page[0])
    if not value:
        response = request_url(
            "https://api.crossref.org/works/" + quote(doi, safe=""),
            350000, "application/json"
        )
        if response:
            try:
                value = json.loads(response[0]).get("message", {}).get("abstract", "")
            except (ValueError, AttributeError):
                pass
    if not value:
        response = request_url(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
            + "query=" + quote("DOI:" + doi) + "&resultType=core&format=json&pageSize=2",
            500000, "application/json"
        )
        if response:
            try:
                entries = json.loads(response[0]).get("resultList", {}).get("result", [])
                value = next((x.get("abstractText", "") for x in entries
                              if x.get("doi", "").lower() == doi), "")
            except (ValueError, TypeError, AttributeError):
                pass
    value = BeautifulSoup(html.unescape(value or ""), "html.parser").get_text(" ", strip=True)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) >= 90 else ""


SUMMARY_MAX_CHARS_EN = 210
SUMMARY_MAX_CHARS_ES = 220


def compact_summary(text, limit=SUMMARY_MAX_CHARS_EN):
    """Keep a concise, grammatical statement rather than a long abstract excerpt.

    Prefer sentences and complete independent clauses. Ellipsis is a last resort
    only when a publisher supplies an unusually long, unpunctuated sentence.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ])", text)
    if len(sentences) > 1 and len(sentences[0]) <= limit:
        return sentences[0].strip()
    # Preserve a whole finding before a subordinate clause or contrast.
    cuts = list(re.finditer(
        r";|,\s+(?=(?:whereas|while|which|although|enabling|allowing|"
        r"mientras|aunque|lo que|que permite)\b)", text, re.I))
    for match in reversed(cuts):
        if 90 <= match.start() <= limit:
            return text[:match.start()].rstrip(" ,;:—") + "."
    # A sufficiently long comma-delimited enumeration is preferable to clipping
    # at an arbitrary character. Avoid splitting short "Here, we..." phrases.
    for match in reversed(list(re.finditer(r",\s+", text))):
        if 90 <= match.start() <= limit:
            return text[:match.start()].rstrip(" ,;:—") + "."
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:—") + "…"


def summarize_abstract(abstract):
    """Choose a substantive, concise result statement for a 4–5 line card."""
    if not abstract:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", abstract)
    sentences = [sent.strip() for sent in sentences if len(sent.strip()) > 40]
    if not sentences:
        return ""
    markers = (
        ("achiev", 7), ("demonstrat", 6), ("reveal", 6),
        ("result", 5), ("show", 5), ("enable", 4),
        ("stable", 3), ("we present", 4), ("here,", 4),
        ("improv", 3), ("increase", 3), ("reduc", 3),
    )
    # Favor shorter scientific findings over long enumerations of measurements.
    candidates = [
        (sum(weight for needle, weight in markers if needle in sent.lower())
         + (5 if 90 <= len(sent) <= SUMMARY_MAX_CHARS_EN else 0),
         i, sent)
        for i, sent in enumerate(sentences)
    ]
    _, _, chosen = max(candidates, key=lambda item: (item[0], item[1]))
    return compact_summary(chosen, SUMMARY_MAX_CHARS_EN)


def translate_summary_es(text):
    """Best-effort automatic translation; caller preserves English on outage."""
    if not text:
        return ""
    endpoint = ("https://translate.googleapis.com/translate_a/single"
                "?client=gtx&sl=en&tl=es&dt=t&q=" + quote(text, safe=""))
    response = request_url(endpoint, 65000, "application/json")
    if response:
        try:
            segments = json.loads(response[0])[0]
            translated = "".join(segment[0] for segment in segments if segment and segment[0])
            return translated.strip()
        except (ValueError, TypeError, IndexError):
            pass
    return ""


def automatic_featured(abstract):
    summary_en = summarize_abstract(abstract)
    if not summary_en:
        return None
    summary_es = translate_summary_es(summary_en) or summary_en
    return {
        "summary": compact_summary(summary_es, SUMMARY_MAX_CHARS_ES),
        "summary_en": summary_en,
    }




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


PMC_OA_S3 = "https://pmc-oa-opendata.s3.amazonaws.com/"
FIG_ONE_LABEL = re.compile(r"^\s*fig(?:ure)?\.?\s*1\s*[.:]?\s*$", re.I)


def europe_pmc_open_access_id(doi):
    """PMCID of the open-access copy of a DOI, via the Europe PMC search API."""
    search = request_url("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
                         "query=" + quote("DOI:" + doi) + "&format=json&pageSize=2",
                         400000, "application/json")
    if not search:
        return None
    try:
        entries = json.loads(search[0]).get("resultList", {}).get("result", [])
    except (ValueError, TypeError, AttributeError):
        return None
    for entry in entries:
        pmcid = entry.get("pmcid") or ""
        if re.fullmatch(r"PMC\d+", pmcid) and entry.get("isOpenAccess") == "Y":
            return pmcid
    return None


def jats_toc_and_figure_one(xml_bytes):
    """Graphic names of the TOC (graphical abstract) and of Figure 1 in JATS XML."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None, None
    def local(tag):
        return tag.rsplit("}", 1)[-1]
    def href(node):
        for g in node.iter():
            if local(g.tag) != "graphic" or g.get("content-type") == "thumb":
                continue
            for key, value in g.attrib.items():
                if local(key) == "href" and value:
                    return value
        return None
    toc = fig1 = None
    for node in root.iter():
        name = local(node.tag)
        if (toc is None and name == "abstract" and
                (node.get("abstract-type") or "").lower() in ("toc", "graphical", "graphical-abstract")):
            toc = href(node)
        elif fig1 is None and name == "fig":
            label = next((c for c in node if local(c.tag) == "label"), None)
            if label is not None and FIG_ONE_LABEL.match("".join(label.itertext())):
                fig1 = href(node)
    return toc, fig1


def pmc_publisher_images(doi):
    """Publisher TOC and Figure 1 from the PMC Open Access dataset on AWS.

    NCBI publishes every PMC open-access article (JATS XML and the original
    figure files) in a public S3 bucket. Unlike the publisher sites,
    Europe PMC or PMC web pages, it does not block GitHub Actions. Returns a
    list of (bytes, source_url, type) in priority order: TOC, then Figure 1.
    """
    pmcid = europe_pmc_open_access_id(doi)
    if not pmcid:
        return []
    listing = request_url(PMC_OA_S3 + "?list-type=2&prefix=" + quote(pmcid + "."),
                          2_000_000, "application/xml")
    if not listing:
        return []
    keys = [k.decode("utf-8", "replace") for k in re.findall(rb"<Key>([^<]+)</Key>", listing[0])]
    versions = sorted({int(m.group(1)) for k in keys
                       for m in [re.match(re.escape(pmcid) + r"\.(\d+)/", k)] if m})
    if not versions:
        return []
    folder = f"{pmcid}.{versions[-1]}/"
    files = [k for k in keys if k.startswith(folder)]
    xml = request_url(PMC_OA_S3 + folder + f"{pmcid}.{versions[-1]}.xml", 8_000_000,
                      "application/xml")
    if not xml:
        return []
    found = []
    for name, typ in zip(jats_toc_and_figure_one(xml[0]), ("graphical-abstract", "figure-1")):
        if not name:
            continue
        stem = re.sub(r"\.(?:jpe?g|gif|png|webp|tiff?)$", "", name.rsplit("/", 1)[-1], flags=re.I)
        matches = [k for k in files
                   if re.fullmatch(re.escape(folder + stem) + r"\.(?:jpe?g|png|webp|gif)", k, re.I)]
        # Prefer full-size formats over the GIF thumbnails.
        matches.sort(key=lambda k: k.lower().endswith(".gif"))
        for key in matches:
            url = PMC_OA_S3 + key
            res = request_url(url, MAX_IMAGE, "image/*")
            if res and res[0]:
                found.append((res[0], url, typ))
                break
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


def extract_funding_from_pdf(pdf, url, projects=None):
    """Extract declarations of funding, including unlabelled Wiley PDF paragraphs.

    The main pass identifies headed acknowledgement/funding sections. A second,
    more conservative pass identifies passages containing both an explicitly
    supported project grant identifier and language of financial support. This
    is needed when PDF reading order breaks the section heading into columns.
    Do not scan/reference-match titles or citation lists on their own.
    """
    out = []
    projects = projects or []
    funding_phrases = re.compile(
        r"(?i)\b(?:funded(?:\s+in\s+part|\s+partially)?\s+by|"
        r"(?:financially\s+)?supported\s+by|funding\s+(?:from|via|by)|"
        r"funding\s+(?:agreement|grant)|grant\s+(?:agreement|number|no\.?)|"
        r"funding|financial\s+support|grants?|acknowledg(?:e)?ments?|"
        r"part\s+of\s+the\s+grant)\b"
    )
    stop = re.compile(
        r"(?im)^[ \t]*(?:references|bibliography|supplementary materials?|"
        r"author contributions|conflicts? of interest|data availability)"
        r"(?:[ \t]*[:.]|[ \t]*\n)"
    )
    try:
        import fitz
        doc = fitz.open(stream=pdf, filetype="pdf")
        for pg in list(doc)[:40]:
            txt = pg.get_text(sort=True)
            # Some publishers embed a heading mid-line or split it across
            # a text block; requiring column 0 loses genuine declarations.
            header = re.search(
                r"(?i)\b(?:acknowledg(?:e)?ments?|funding(?: information| statement)?|"
                r"financial support)\b",
                txt
            )
            if header:
                body = txt[header.start():header.start() + 11000]
                body = stop.split(body, maxsplit=1)[0]
                if len(body.strip()) >= 35:
                    out.append(("oa-pdf", body, url))
            if projects:
                # Only accept grants in a local, explicit funding statement.
                # This catches grant IDs with PDF reading-order problems but
                # avoids matching arbitrary mentions in the references.
                refs = re.search(r"(?im)^[ \t]*references[ \t]*$", txt)
                eligible = txt[:refs.start()] if refs else txt
                for marker in funding_phrases.finditer(eligible):
                    passage = eligible[max(0, marker.start()-220):marker.end()+450]
                    if grants_in_text(passage, projects):
                        entry = ("oa-pdf-funding-context", passage, url)
                        if entry not in out:
                            out.append(entry)
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
    # Recheck cached evidence after substantive parser upgrades; old text-checked
    # status means the OLD matcher ran, not that the new matcher has been tried.
    if prev.get("fundingMatcherVersion") != FUNDING_MATCHER_VERSION:
        revisit = True
    # Retry unresolved articles weekly, whether they have missing projects or images.
    if prev.get("fundingStatus") != "text-checked":
        revisit = True
    # When a Wiley TDM token is added later, revisit even previously checked
    # articles; metadata and OA repositories can miss additional grants.
    prior_image = prev.get("image") or {}
    acs_figure_fallback = (doi.startswith("10.1021/") and
                           prior_image.get("type") == "figure-1")
    try:
        last_toc_check = date.fromisoformat(
            prev.get("tocChecked") or prev.get("checked") or "1900-01-01"
        )
    except ValueError:
        last_toc_check = date(1900, 1, 1)
    # A lightweight scheduled retry for pending ACS TOCs avoids rerunning
    # the entire OpenAlex publication discovery and grant enrichment.
    forced_toc_retry = (acs_figure_fallback and
                        os.getenv("ABX_RETRY_TOC", "").lower() == "true")
    weekly_toc_retry = (forced_toc_retry or
                        (acs_figure_fallback and
                         last_toc_check <= date.today() - timedelta(days=7)))
    needs_picture = not manual.get("image") and (
        not prior_image or
        (prior_image.get("type") == "figure-1" and
         (revisit or weekly_toc_retry or
          (prev.get("acsTocMatcherVersion") != ACS_TOC_MATCHER_VERSION
           if doi.startswith("10.1021/")
           else prev.get("imageMatcherVersion") != IMAGE_MATCHER_VERSION)))
    )
    featured = rec.get("featured") or prev.get("featured")
    needs_summary = (rec.get("publicationDate", "") >= "2026-01-01" and
                     (not isinstance(featured, dict) or
                      not featured.get("summary") or not featured.get("summary_en")))
    wiley_due = bool(WILEY_TDM_TOKEN and doi.startswith("10.1002/")
                     and (prev.get("wileyTdmStatus") != "success"
                          or prev.get("fundingStatus") != "text-checked"
                          or revisit or needs_picture))
    if wiley_due:
        revisit = True
    work = {}
    page = None
    status = prev.get("fundingStatus") or "metadata-only"
    img_origin = prev.get("image")
    lic = prev.get("license")
    wiley_status = prev.get("wileyTdmStatus", "not-configured")
    if revisit or needs_picture or needs_summary:
        work = openalex_work(doi)
        if not work:
            print("  OpenAlex DOI lookup empty:", doi, flush=True)
        page = download_publisher_page(doi)
        sources = []
        # Existing text-checked funding evidence is cached. Re-running
        # TEI/funder APIs solely to replace an image wastes OpenAlex quota.
        if revisit:
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
        wiley_pdf_used = False
        if wiley_due:
            wiley_response = wiley_tdm_pdf(doi)
            if wiley_response:
                pdf, pdfurl = wiley_response
                wiley_pdf_used = True
                wiley_status = "success"
                sources.extend((("wiley-tdm", section, pdfurl)
                    for _source, section, _url in extract_funding_from_pdf(pdf, pdfurl, projects)))
                print("  Wiley TDM PDF retrieved:", doi, flush=True)
            else:
                wiley_status = "unavailable"
        urls = accessible_pdf_candidates(work, rec) if pdf is None else []
        wid = str(work.get("id") or rec.get("openalexId") or "").rsplit("/", 1)[-1]
        if KEY and re.fullmatch(r"W\d+", wid):
            urls.append("https://content.openalex.org/works/" + wid + ".pdf?api_key=" + quote(KEY))
        for candidate in urls:
            response = request_url(candidate, MAX_PDF, "application/pdf")
            if response and response[0][:4] == b"%PDF":
                pdf, pdfurl = response[0], candidate.split("?")[0]
                break
        if pdf is not None and not wiley_pdf_used and revisit:
            sources.extend(extract_funding_from_pdf(pdf, pdfurl, projects))
        if not sources and revisit:
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
        elif revisit and status != "text-checked":
            status = "metadata-only"
        if needs_summary:
            abstract = discover_abstract(doi, work, page)
            automatic = automatic_featured(abstract) if abstract else None
            if automatic:
                featured = {**automatic, **(featured or {})}
                print("  Automated summary available:", doi, flush=True)
            else:
                print("  Abstract unavailable for automatic summary:", doi, flush=True)
        if needs_picture:
            lic = metadata_licenses(rec, work)
            credit = None
            if not lic and wiley_standard_terms(doi, rec, work):
                lic = WILEY_STANDARD_LICENSE
                credit = wiley_copyright(doi, rec, pdf)
            if lic:
                def html_toc():
                    if not page:
                        return None
                    url, kind = graphical_abstract_from_html(page[0], page[1])
                    if not url:
                        return None
                    res = request_url(url, max_bytes=MAX_IMAGE, accept="image/*")
                    if res and res[2].lower().startswith("image/"):
                        return res[0], url, kind
                    return None

                pmc_cache = []
                def pmc(kind):
                    # Imágenes originales de la editorial en el conjunto Open Access
                    # de PMC (artículos con financiación europea). Se consulta una
                    # sola vez y solo si hace falta.
                    if not pmc_cache:
                        pmc_cache.append(pmc_publisher_images(doi))
                    return next((i for i in pmc_cache[0] if i[2] == kind), None)

                def pdf_toc():
                    png = toc_graphic_from_pdf(pdf) if pdf else None
                    return (png, pdfurl, "graphical-abstract") if png else None

                def pdf_figure_one():
                    if pdf and doi == "10.1021/acsami.6c11506":
                        diagnose_acs_toc_pdf(pdf)
                    png = first_figure_from_pdf(pdf) if pdf else None
                    return (png, pdfurl, "figure-1") if png else None

                # Orden: TOC (web de la editorial, PMC, PDF) y, si no hay TOC,
                # Figura 1 (PMC, PDF). Si una imagen no se puede convertir (p. ej.
                # demasiado pequeña), se prueba la siguiente fuente.
                blob = None
                for source in (html_toc, lambda: pmc("graphical-abstract"), pdf_toc,
                               lambda: pmc("figure-1"), pdf_figure_one):
                    found = source()
                    if not found:
                        continue
                    candidate, srcurl, typ = found
                    # Nunca sustituir la Figura 1 original de PMC por una renderizada
                    # del PDF: si PMC no responde en una revisión (p. ej. Europe PMC
                    # caído), se conserva la imagen anterior.
                    if (typ == "figure-1" and prior_image.get("type") == "figure-1"
                            and "pmc-oa-opendata" in str(prior_image.get("source", ""))
                            and "pmc-oa-opendata" not in str(srcurl)):
                        break
                    # Content-addressed asset prevents stale GitHub/browser/CDN
                    # caches when the genuine TOC replaces a provisional Figure 1.
                    file_name = publication_image_filename(doi, candidate)
                    if extract_image_to_webp(candidate, IMAGES / file_name):
                        blob = candidate
                        img_origin = {"url": RAW_IMAGES + file_name, "source": srcurl,
                                      "type": typ, "license": lic, "doi": doi}
                        if credit:
                            img_origin["credit"] = credit
                        break
                if blob is None and doi == "10.1021/acsami.6c11506" and prior_image.get("type") == "figure-1":
                    reason = ("PDF no accesible" if pdf is None else
                              "el TOC no se ha localizado en el PDF")
                    print("  TOC NO RESUELTO:", doi, "-", reason,
                          "; ACS HTML no accesible" if page is None else "",
                          "; se mantiene Figura 1 provisional", flush=True)
    exclude = set(manual.get("excludeProjects", []))
    keys = set(rec.get("projects") or []) | {e["project"] for e in evidence}
    keys |= set(manual.get("projects", []))
    rec["projects"] = [p["key"] for p in projects if p["key"] in keys and p["key"] not in exclude]
    # Evidence contains codes, sources and links, never complete copyrighted acknowledgement text.
    rec["fundingEvidence"] = sorted(evidence, key=lambda e: (e["project"], e["source"], e["grant"]))
    rec["fundingStatus"] = status
    rec["featured"] = featured
    rec.pop("imageCredit", None)
    if manual.get("image"):
        rec["image"] = manual["image"]
    elif img_origin:
        if img_origin.get("credit"):
            rec["imageCredit"] = img_origin["credit"]
        rec["image"] = img_origin["url"]
        rec["imageSource"] = img_origin["source"]
        rec["imageType"] = img_origin["type"]
        rec["imageLicense"] = img_origin["license"]
    audit = {"checked": today if (revisit or needs_picture or needs_summary) else prev.get("checked", today),
             "fundingStatus": status, "fundingEvidence": rec["fundingEvidence"],
             "featured": featured,
             "imageMatcherVersion": IMAGE_MATCHER_VERSION,
             "acsTocMatcherVersion": ACS_TOC_MATCHER_VERSION
                                     if doi.startswith("10.1021/") else None,
             "tocChecked": today if acs_figure_fallback and needs_picture
                           else prev.get("tocChecked"),
             "image": img_origin, "license": lic,
             "wileyTdmStatus": wiley_status,
             "fundingMatcherVersion": FUNDING_MATCHER_VERSION}
    return rec, audit


def main():
    projects = load(DATA / "projects.json", [])
    extras = load(DATA / "publication_extras.json", {})
    cache = load(EVIDENCE, {})
    updated = dict(cache)
    total, images = 0, 0
    pending_acs_only = os.getenv("ABX_ONLY_PENDING_ACS_TOC", "").lower() == "true"
    for filename in ("publications.json", "publications_2025.json"):
        path = DATA / filename
        records = load(path, [])
        for rec in records:
            old_img = rec.get("image")
            doi = rec.get("doi", "").lower()
            if not doi:
                continue
            if pending_acs_only:
                previous_image = (cache.get(doi, {}).get("image") or {})
                if (not doi.startswith("10.1021/") or
                        previous_image.get("type") != "figure-1"):
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
