import sys, json, re, importlib.util
from pathlib import Path
from urllib.parse import quote
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("enr", ROOT / "scripts/enrich_publications.py")
enr = importlib.util.module_from_spec(spec); spec.loader.exec_module(enr)
import fitz
out = ROOT / "diag_out"; out.mkdir(exist_ok=True)
recs = {r["doi"].lower(): r for f in ("publications.json", "publications_2025.json")
        for r in json.loads((ROOT / "data" / f).read_text())}
for doi in sys.argv[1:]:
    rec = recs.get(doi, {"doi": doi})
    print("\n=====", doi, "license:", rec.get("license"))
    work = enr.openalex_work(doi) or {}
    print("OA:", (work.get("open_access") or {}), "best:", (work.get("best_oa_location") or {}).get("license"))
    print("metadata_licenses:", enr.metadata_licenses(rec, work))
    urls = enr.accessible_pdf_candidates(work, rec)
    wid = str(work.get("id") or rec.get("openalexId") or "").rsplit("/", 1)[-1]
    if enr.KEY and re.fullmatch(r"W\d+", wid):
        urls.append("https://content.openalex.org/works/" + wid + ".pdf?api_key=" + quote(enr.KEY))
    for i, u in enumerate(urls):
        r = enr.request_url(u, enr.MAX_PDF, "application/pdf")
        ok = bool(r and r[0][:4] == b"%PDF")
        print("cand", i, u.split("?")[0], "->", ("PDF %d bytes" % len(r[0])) if ok else ("not pdf" if r else "fail"))
        if not ok:
            continue
        pdf = r[0]
        (out / (doi.replace("/", "_") + f"_{i}.pdf")).write_bytes(pdf)
        print("  toc:", bool(enr.toc_graphic_from_pdf(pdf)), "fig1:", bool(enr.first_figure_from_pdf(pdf)))
        with fitz.open(stream=pdf, filetype="pdf") as d:
            print("  pages", len(d), "first-page text:", " ".join(d[0].get_text()[:200].split()))
            for pi in range(min(9, len(d))):
                p = d[pi]
                caps = [(round(b[1]), " ".join(b[4].split())[:70]) for b in p.get_text("blocks")
                        if b[6] == 0 and re.search(r"\b(fig(ure)?\.?\s*\d|graphical|toc\b)", b[4], re.I)][:6]
                imgs = [tuple(round(v) for v in rr) for info in p.get_images(full=True)
                        for rr in p.get_image_rects(info[0])][:8]
                print("   p%d caps=%s imgs=%s draws=%d" % (pi + 1, caps, imgs, len(p.get_drawings())))
    # Europe PMC
    q = quote("DOI:" + doi)
    s = enr.request_url("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=" + q + "&format=json&pageSize=2", 400000, "application/json")
    ents = json.loads(s[0]).get("resultList", {}).get("result", []) if s else []
    print("EPMC:", [(e.get("pmcid"), e.get("isOpenAccess")) for e in ents])
    x = enr.european_pmc_xml(doi)
    if x:
        xml = x[0].decode("utf-8", "replace")
        pmcid = re.search(r"(PMC\d+)", x[1]).group(1)
        hrefs = re.findall(r'<graphic[^>]*xlink:href="([^"]+)"', xml)
        print("  graphics:", hrefs[:6])
        for h in hrefs[:3]:
            base = re.sub(r"\.\w+$", "", h)
            for url in (f"https://europepmc.org/articles/{pmcid}/bin/{h}",
                        f"https://europepmc.org/articles/{pmcid}/bin/{base}.jpg",
                        f"https://europepmc.org/api/fulltextRepo?pprId={pmcid}&type=FILE&fileName={h}",
                        f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/bin/{base}.jpg"):
                r = enr.request_url(url, enr.MAX_IMAGE, "image/*")
                print("   ", url, "->", (r[2], len(r[0]), r[1]) if r else None)
