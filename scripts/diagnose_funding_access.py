#!/usr/bin/env python3
"""Read-only, secret-safe diagnostics of two missing funding matches.

This script never writes PDFs, full text, article passages, or API credentials.
Use only in GitHub Actions, with the existing repository secrets.
"""
import importlib.util
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote
import requests

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("enrich_publications", root / "scripts" / "enrich_publications.py")
enrich = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enrich)

MEM_DOI = "10.1002/aelm.202500494"
SOLAR_DOI = "10.1016/j.solmat.2026.114703"
MAX_BYTES = 8_000_000


def local_name(tag):
    return tag.rsplit("}", 1)[-1].split(":")[-1].lower()


def digest_flags(text):
    compact = enrich.normalize(text)
    return {
        "has_CNS2023_full": "CNS2023144270" in compact,
        "has_CNS2023_suffix": "144270" in compact,
        "has_ESGENT_full": "ESGENT0102024" in compact,
        "has_ESGENT_text": "ESGENT" in compact,
        "has_GENT_text": "GENT" in compact,
        "has_0102024": "0102024" in compact,
        "has_HEPAFLEX": "HEPAFLEX" in compact,
        "has_101122345": "101122345" in compact,
    }


def show_flags(label, value):
    print(label + ": " + ", ".join(k + "=" + str(v) for k, v in value.items()), flush=True)


def wiley_diagnostic():
    print("WILEY_DIAG: token_configured=" + str(bool(os.getenv("WILEY_TDM_TOKEN"))), flush=True)
    if not os.getenv("WILEY_TDM_TOKEN"):
        return
    received = enrich.wiley_tdm_pdf(MEM_DOI)
    if not received:
        print("WILEY_DIAG: PDF unavailable for current runner", flush=True)
        return
    blob, endpoint = received
    print("WILEY_DIAG: valid_pdf=" + str(blob.startswith(b"%PDF")) + " bytes=" + str(len(blob)), flush=True)
    import fitz
    doc = fitz.open(stream=blob, filetype="pdf")
    try:
        ordered = [p.get_text(sort=True) for p in doc]
        original = [p.get_text(sort=False) for p in doc]
        print("WILEY_DIAG: page_count=" + str(len(doc))
              + " extracted_chars=" + str(sum(map(len, ordered)))
              + " first_page_chars=" + str(len(ordered[0]) if ordered else 0), flush=True)
        print("WILEY_DIAG: expected_title_words_found=" + str(
            all(word in enrich.normalize(ordered[0]) for word in ("COMPOSITIONAL", "MEMRISTORS"))
            if ordered else False), flush=True)
        show_flags("WILEY_DIAG: sorted_whole_pdf", digest_flags(" ".join(ordered)))
        show_flags("WILEY_DIAG: unsorted_whole_pdf", digest_flags(" ".join(original)))
        headings = re.compile(r"acknowledg|funding|financial support", re.I)
        print("WILEY_DIAG: pages_with_funding_headings=" +
              str([i + 1 for i, t in enumerate(ordered) if headings.search(t)]), flush=True)
        for idx, page_text in enumerate(ordered):
            flags = digest_flags(page_text)
            if not (flags["has_CNS2023_suffix"] or flags["has_ESGENT_text"]):
                continue
            refs = re.search(r"(?im)^[ \t]*(?:references|bibliography)[ \t]*$", page_text)
            fund = re.search(r"(?i)\b(?:acknowledg(?:e)?ments?|funding|financial support)\b", page_text)
            before_refs = page_text[:refs.start()] if refs else page_text
            after_heading = page_text[fund.start():] if fund else ""
            if refs and fund and fund.start() < refs.start():
                after_heading = page_text[fund.start():refs.start()]
            print("WILEY_DIAG: page=" + str(idx + 1)
                + " refs_header_at=" + str(refs.start() if refs else -1)
                + " funding_heading_at=" + str(fund.start() if fund else -1)
                + " cns_before_refs=" + str(digest_flags(before_refs)["has_CNS2023_full"])
                + " esgent_before_refs=" + str(digest_flags(before_refs)["has_ESGENT_full"])
                + " cns_after_funding_heading=" + str(digest_flags(after_heading)["has_CNS2023_full"])
                + " esgent_after_funding_heading=" + str(digest_flags(after_heading)["has_ESGENT_full"]), flush=True)
        projects = [
            {"key": "cns2023", "grants": ["CNS2023-144270"]},
            {"key": "esgent", "grants": ["ESGENT/010/2024", "CIESGT2024/010"]},
        ]
        sections = enrich.extract_funding_from_pdf(blob, endpoint, projects)
        matches = set()
        for _kind, body, _source in sections:
            matches.update(enrich.grants_in_text(body, projects))
        print("WILEY_DIAG: funding_sections=" + str(len(sections))
              + " matched_project_keys=" + ",".join(sorted(matches)), flush=True)
    finally:
        doc.close()


def elsevier_diagnostic():
    key = os.getenv("ELSEVIER_API_KEY", "")
    print("ELSEVIER_DIAG: key_configured=" + str(bool(key)), flush=True)
    if not key:
        return
    url = "https://api.elsevier.com/content/article/doi/" + quote(SOLAR_DOI, safe="/")
    # FULL refuses access explicitly rather than returning an abstract-only 200.
    try:
        with requests.get(url, params={"view": "FULL", "httpAccept": "text/xml"},
                          headers={"X-ELS-APIKey": key, "Accept": "text/xml",
                                   "User-Agent": enrich.HEADERS["User-Agent"]},
                          timeout=25, stream=True, allow_redirects=False) as response:
            print("ELSEVIER_DIAG: full_view_status=" + str(response.status_code)
                  + " content_type=" + response.headers.get("Content-Type", "unknown").split(";")[0], flush=True)
            if response.status_code != 200:
                # Deliberately do not print the error payload: it may echo authorization details.
                return
            size = 0
            chunks = []
            for block in response.iter_content(65536):
                size += len(block)
                if size > MAX_BYTES:
                    print("ELSEVIER_DIAG: XML larger than safe processing limit", flush=True)
                    return
                chunks.append(block)
        data = b"".join(chunks)
        print("ELSEVIER_DIAG: response_bytes=" + str(len(data)), flush=True)
        try:
            xml_root = ET.fromstring(data)
        except ET.ParseError:
            print("ELSEVIER_DIAG: XML parse failed", flush=True)
            return
        count = {}
        for el in xml_root.iter():
            tag = local_name(el.tag)
            if tag in ("body", "doc", "originaltext", "acknowledgment", "acknowledgement",
                       "ack", "funding-group", "funding-statement", "section", "sec"):
                count[tag] = count.get(tag, 0) + 1
        print("ELSEVIER_DIAG: recognized_XML_elements=" + str(count), flush=True)
        whole = " ".join(xml_root.itertext())
        section = enrich.text_from_tei(data)
        print("ELSEVIER_DIAG: xml_characters=" + str(len(whole))
              + " funding_section_characters=" + str(len(section)), flush=True)
        show_flags("ELSEVIER_DIAG: all_XML", digest_flags(whole))
        show_flags("ELSEVIER_DIAG: parsed_funding_only", digest_flags(section))
    except requests.RequestException as exc:
        print("ELSEVIER_DIAG: request_failed=" + type(exc).__name__, flush=True)


if __name__ == "__main__":
    wiley_diagnostic()
    elsevier_diagnostic()
