import sys, json, re, importlib.util, io, zipfile
from pathlib import Path
from urllib.parse import quote
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("enr", ROOT / "scripts/enrich_publications.py")
enr = importlib.util.module_from_spec(spec); spec.loader.exec_module(enr)
def show(label, r):
    print("   ", label, "->", (r[2], len(r[0]), r[1][:120]) if r else None, flush=True)
    return r
for doi, pmcid, wid in [("10.1039/d6ee05477c", "PMC13651458", "W7220689702"),
                        ("10.1039/d5el00182j", "PMC12848990", "W7125242329"),
                        ("10.1039/d5ma01122a", None, "W7117514834"),
                        ("10.1039/d5el00064e", None, "W4414061071")]:
    print("\n=====", doi, flush=True)
    # PDF figure extraction with the new matcher
    for u in ["https://content.openalex.org/works/%s.pdf?api_key=%s" % (wid, quote(enr.KEY))]:
        r = enr.request_url(u, enr.MAX_PDF, "application/pdf")
        if r and r[0][:4] == b"%PDF":
            png = enr.first_figure_from_pdf(r[0])
            print("  new fig1:", bool(png), len(png or b""))
            if png:
                from PIL import Image
                im = Image.open(io.BytesIO(png)); print("   size", im.size)
                Path(ROOT/"diag_out").mkdir(exist_ok=True)
                (ROOT/"diag_out"/(doi.split("/")[1]+"-fig1.png")).write_bytes(png)
    j = doi.split("/")[1].upper(); jr = j[2:4] if False else re.match(r"D\d(\w\w)", j).group(1)
    yr = "2026" if j.startswith("D6") or doi.endswith(("00182j","01122a")) else "2025"
    show("rsc imageservice", enr.request_url(
        f"https://pubs.rsc.org/services/images/RSCpubs.ePlatform.Service.FreeContent.ImageService.svc/ImageService/Articleimage/{yr}/{jr}/{j}", enr.MAX_IMAGE, "image/*"))
    if not pmcid:
        continue
    show("oa.fcgi", r := enr.request_url(f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}", 200000, "application/xml"))
    if r: print("     ", r[0][:600])
    show("s3 list", r := enr.request_url(f"https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix={pmcid}.", 400000, "application/xml"))
    if r:
        keys = re.findall(rb"<Key>([^<]+)</Key>", r[0]); print("      keys:", keys[:25])
        for k in keys:
            if re.search(rb"-(ga|f1)\.(jpg|gif|png|webp)$", k):
                show("s3 obj " + k.decode(), enr.request_url("https://pmc-oa-opendata.s3.amazonaws.com/" + k.decode(), enr.MAX_IMAGE, "image/*"))
    show("epmc suppl inline", r := enr.request_url(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles?includeInlineImage=true", 40_000_000, "application/zip"))
    if r:
        try:
            z = zipfile.ZipFile(io.BytesIO(r[0])); print("      zip:", [(i.filename, i.file_size) for i in z.infolist()][:30])
        except Exception as e:
            print("      not zip", e, r[0][:200])
