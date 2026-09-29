"""Checks for Pdf Rename. No network, no real PDFs, no window needed.

Run from the app folder:
    python tests\\test_pdf_renamer.py

What it covers
  unit        name building, DOI ranking and trimming, title support, path cleaning
  resolver    404 vs 429 vs dropped connection vs timeout, and what each becomes
  end to end  a temp folder of handmade PDFs against a fake Crossref: confirmed
              files renamed, uncertain listed, scans left alone, duplicates
              suffixed, undo restores, apply renames the listed ones
  window      only when a display is available: the window runs a folder and
              shows the rows (skipped silently otherwise)
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import renamer_core as core  # noqa: E402

core.time.sleep = lambda *_: None      # no real backoff waits
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


# ------------------------------------------------------------ handmade PDFs --

def make_pdf(path: Path, lines, title_meta=None):
    """A one page PDF with Helvetica text that pypdf can extract, line by line."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 11 Tf 40 780 Td 14 TL\n"
    for ln in lines:
        content += f"({esc(ln)}) Tj T*\n"
    content += "ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    if title_meta is not None:
        objs.append(f"<< /Title ({esc(title_meta)}) /CreationDate (D:20230405) >>")
    out = "%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n"
    trailer = f"<< /Size {len(objs) + 1} /Root 1 0 R"
    if title_meta is not None:
        trailer += f" /Info {len(objs)} 0 R"
    trailer += " >>"
    out += f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


# ------------------------------------------------------------- fake Crossref --

class FakeResponse:
    def __init__(self, code, payload=None, retry_after=None):
        self.status_code = code
        self.headers = {"Retry-After": retry_after} if retry_after else {}
        self._payload = payload or {}

    def json(self):
        return self._payload


def work(title, year, family, doi):
    return {"message": {"title": [title], "issued": {"date-parts": [[year]]},
                        "author": [{"family": family}, {"family": "Other"}],
                        "container-title": ["Journal"], "DOI": doi}}


class FakeSession:
    """Answers by URL for /works/{doi}; title queries return one item list."""

    def __init__(self, by_doi=None, by_title=None, script=None):
        self.by_doi = by_doi or {}
        self.by_title = by_title or (lambda q: [])
        self.script = list(script or [])
        self.calls = []
        self.headers = {}
        self.lock = threading.Lock()

    def get(self, url, params=None, timeout=None):
        with self.lock:
            self.calls.append(url if params is None else (url, params.get("query.bibliographic")))
            if self.script:
                item = self.script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        if url.startswith(core.CROSSREF_WORK):
            doi = url[len(core.CROSSREF_WORK):]
            if doi in self.by_doi:
                return FakeResponse(200, self.by_doi[doi])
            return FakeResponse(404)
        items = [w["message"] for w in self.by_title(params["query.bibliographic"])]
        return FakeResponse(200, {"message": {"items": items}})


class FakeResolver(core.Resolver):
    def __init__(self, session):
        super().__init__()
        self._fake = session

    @property
    def session(self):
        return self._fake


# ----------------------------------------------------------------------- unit --

t = "Anisotropic mechanical response of triply periodic minimal surface lattices produced by laser powder bed fusion under compression"
for folder_len in (30, 120, 200):
    name = core.render_name("2021", t, folder_len)
    check(f"name fits path limit at folder length {folder_len}",
          folder_len + 1 + len(name) <= core.PATH_LIMIT + 4, f"{len(name)} chars")
check("name pattern", core.render_name("2021", "A short title: part/2", 30) == "2021_A short title - part-2.pdf",
      core.render_name("2021", "A short title: part/2", 30))
check("looks_renamed accepts the pattern", core.looks_renamed("2021_Anisotropic lattices.pdf"))
check("pattern with author renders", core.render_name("2021", "A title", 30, author="Lim et al",
      template="{author}_{year}_{title}") == "Lim et al_2021_A title.pdf")
check("pattern with brackets renders", core.render_name("2021", "A title", 30, author="Lim et al",
      template="{author} ({year}) {title}") == "Lim et al (2021) A title.pdf")
check("looks_renamed follows the chosen pattern",
      core.looks_renamed("Lim et al (2021) A title.pdf", "{author} ({year}) {title}")
      and not core.looks_renamed("2021_A title.pdf", "{author} ({year}) {title}"))
check("bad pattern is refused", core.validate_template("{yr}_{title}") != "" and core.validate_template("{author}") != "")
check("good pattern passes", core.validate_template("{year} - {title}") == "")
check("bad pattern falls back to default", core.render_name("2021", "A title", 30, template="{nope}") == "2021_A title.pdf")
check("looks_renamed rejects a bare year", not core.looks_renamed("2021.pdf"))
check("looks_renamed rejects other names", not core.looks_renamed("lim2021.pdf"))

text = ("Journal of Things 12 (2021) 100\nhttps://doi.org/10.1016/j.own.2021.001\n"
        "Anisotropic response of lattices\nA. Author, B. Other\n"
        "Cite as: doi:10.1016/j.own.2021.001\nReferences [1] doi:10.1016/j.cited.2018.777")
dois = core.find_dois(text, {})
check("own DOI (printed twice) ranks first", dois[0] == "10.1016/j.own.2021.001", str(dois))
check("cited DOI still listed second", dois[1] == "10.1016/j.cited.2018.777", str(dois))
check("metadata DOI appended", "10.1002/meta.1" in core.find_dois(text, {"/doi": "10.1002/meta.1"}))

for raw, want in {
    "10.1016/j.actbio.2021.01.001Received": "10.1016/j.actbio.2021.01.001",
    "10.1038/s41586-021-03819-2www.nature.com": "10.1038/s41586-021-03819-2",
    "10.1007/s10853-020-05236-8Abstract": "10.1007/s10853-020-05236-8",
}.items():
    check(f"doi trim  {raw[:40]}", want in core.doi_candidates(raw), str(core.doi_candidates(raw)))

check("title support high for own title", core.title_support("Anisotropic response of lattices", text) >= 0.6)
check("title support low for another paper", core.title_support("Electrochemical degradation of polyethylene", text) < 0.6)
check("surname found", core.surname_in_text("Author et al", text))
check("surname absent", not core.surname_in_text("Nobody et al", text))
check("junk embedded title dropped", core.embedded_title({"/Title": "Microsoft Word - manuscript_rev2.doc"}) == "")
check("real embedded title kept", core.embedded_title({"/Title": "Anisotropic response of lattices"}) != "")

sys.path.insert(0, str(HERE.parent))
try:
    import pdf_renamer_app as gui
    check("clean_path strips quotes", gui.clean_path('  "C:\\Users\\me\\papers\\"  ') == "C:\\Users\\me\\papers")
    check("clean_path handles file URL", gui.clean_path("file:///C:/Users/me/my%20papers").endswith("my papers"))
    HAVE_GUI = True
except Exception as exc:             # no tkinter on this machine
    HAVE_GUI = False
    print("skip  window checks (tkinter not importable here):", exc)

# ------------------------------------------------------------------- resolver --

D = "10.1016/j.jmbbm.2021.104417"
W = work("A paper", 2021, "Lim", D)

r = FakeResolver(FakeSession(script=[FakeResponse(200, W)]))
data, st = r.by_doi(D)
check("200 resolves", st == core.LOOKUP_OK and data["year"] == "2021")
r = FakeResolver(FakeSession(script=[FakeResponse(404), FakeResponse(200, W)]))
data, st = r.by_doi("10.1016/j.actbio.2021.01.001Received")
check("404 then trimmed doi", st == core.LOOKUP_OK and r.session.calls[1].endswith(".001"))
r = FakeResolver(FakeSession(script=[FakeResponse(429, retry_after="0.5"), FakeResponse(200, W)]))
check("429 retried", r.by_doi(D)[1] == core.LOOKUP_OK)
r = FakeResolver(FakeSession(script=[FakeResponse(503)] * 3))
check("exhausted 5xx is a failure", r.by_doi(D)[1] == core.LOOKUP_FAILED)
r = FakeResolver(FakeSession(script=[core.requests.exceptions.ConnectionError("x")]))
check("dropped connection is a failure and goes offline", r.by_doi(D)[1] == core.LOOKUP_FAILED and r.offline)
r = FakeResolver(FakeSession(script=[core.requests.exceptions.Timeout("x"), FakeResponse(200, W)]))
check("timeout retried, not offline", r.by_doi(D)[1] == core.LOOKUP_OK and not r.offline)
r = FakeResolver(FakeSession(script=[FakeResponse(404)] * 3))
check("real 404 is absence", r.by_doi(D)[1] == core.LOOKUP_NOT_FOUND)

# ----------------------------------------------------------------- end to end --

OWN = "10.1016/j.own.2021.001"
CITED = "10.1016/j.cited.2018.777"
OWN_TITLE = "Anisotropic mechanical response of lattice scaffolds"
CITED_TITLE = "Electrochemical degradation of polyethylene microplastics"
SEARCH_TITLE = "Design of gradient porosity bone scaffolds by additive manufacturing"

by_doi = {OWN: work(OWN_TITLE, 2021, "Lim", OWN),
          CITED: work(CITED_TITLE, 2018, "Zhang", CITED)}


def by_title(q):
    if "gradient porosity" in q.lower():
        return [work(SEARCH_TITLE, 2020, "Egan", "10.1000/search.1")]
    return []


def build_folder(root: Path):
    make_pdf(root / "paper1.pdf", ["Journal of Things 12 (2021) 100",
                                   f"https://doi.org/{OWN}", OWN_TITLE, "A. Lim, B. Other",
                                   f"Cite as: doi:{OWN}", f"[1] doi:{CITED}"])
    make_pdf(root / "paper1 copy.pdf", ["Journal of Things 12 (2021) 100",
                                        f"https://doi.org/{OWN}", OWN_TITLE, "A. Lim",
                                        f"Cite as: doi:{OWN}"])
    make_pdf(root / "search_ok.pdf", [SEARCH_TITLE, "P. F. Egan, A. Habib",
                                      "Abstract. Gradient porosity scaffolds ...",
                                      f"[1] doi:{CITED}"], title_meta=SEARCH_TITLE)
    make_pdf(root / "search_weak.pdf", [SEARCH_TITLE, "Anonymous authors",
                                        "Abstract. Gradient porosity scaffolds ..."],
             title_meta=SEARCH_TITLE)
    make_pdf(root / "scan.pdf", [])
    make_pdf(root / "2019_Already named paper.pdf", [f"doi:{OWN}", OWN_TITLE])
    (root / "notes.txt").write_text("not a pdf")
    (root / "2021_Anisotropic mechanical response of lattice scaffolds.pdf").write_bytes(b"%PDF-1.4 stray")


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    build_folder(root)
    progress = []
    res = core.run_folder(root, resolver=FakeResolver(FakeSession(by_doi, by_title)),
                          progress=lambda i, n, name: progress.append((i, n)))
    by_name = {r.name: r for r in res.records}

    check("progress reported for every file", progress and progress[-1] == (5, 5), str(progress))
    check("non PDF ignored", res.others == 1)
    check("already renamed file skipped", by_name["2019_Already named paper.pdf"].outcome == core.SKIPPED)
    p1 = by_name["paper1.pdf"]
    check("paper with its own DOI is confirmed and renamed", p1.outcome == core.RENAMED and p1.source == core.SRC_DOI, p1.note)
    check("year came from Crossref, not the file", p1.year == "2021")
    names = sorted(p.name for p in root.glob("*.pdf"))
    check("stray existing file not overwritten, duplicates suffixed",
          "2021_Anisotropic mechanical response of lattice scaffolds (2).pdf" in names
          and "2021_Anisotropic mechanical response of lattice scaffolds (3).pdf" in names, str(names))
    check("stray file content untouched",
          (root / "2021_Anisotropic mechanical response of lattice scaffolds.pdf").read_bytes() == b"%PDF-1.4 stray")
    so = by_name["search_ok.pdf"]
    check("title search with surname in text is confirmed", so.outcome == core.RENAMED and so.year == "2020", so.note)
    sw = by_name["search_weak.pdf"]
    check("title search without surname needs a look", sw.outcome == core.NEEDS_LOOK, sw.note)
    check("needs a look row has a proposed name", sw.proposed.startswith("2020_Design of gradient"), sw.proposed)
    check("needs a look file was not renamed", (root / "search_weak.pdf").exists())
    sc = by_name["scan.pdf"]
    check("scan is not resolved with a plain reason", sc.outcome == core.NOT_RESOLVED and "text layer" in sc.note, sc.note)
    check("log written", res.log_path and Path(res.log_path).exists())
    check("rows sorted renamed first", res.records[0].outcome == core.RENAMED)

    # apply the uncertain one after an edit
    sw.proposed = "2020_Edited by hand.pdf"
    core.apply_records(root, res.records)
    check("apply renames the listed row", sw.outcome == core.RENAMED and (root / "2020_Edited by hand.pdf").exists(), sw.note)

    # undo twice: first the apply, then the main run
    n1, e1, _ = core.undo_last(root)
    n2, e2, _ = core.undo_last(root)
    check("undo restores the apply, then the run", (n1, n2) == (1, 3) and not e1 and not e2, f"{n1},{e1},{n2},{e2}")
    check("all original names back", (root / "paper1.pdf").exists() and (root / "search_weak.pdf").exists()
          and (root / "paper1 copy.pdf").exists() and (root / "search_ok.pdf").exists())
    check("no logs left after full undo", not core.find_logs(root))
    check("no staging files left", not list(root.glob("__pdfrenamer_staging_*")))

with tempfile.TemporaryDirectory() as d:          # a custom pattern end to end
    root = Path(d)
    build_folder(root)
    res = core.run_folder(root, resolver=FakeResolver(FakeSession(by_doi, by_title)),
                          template="{author}_{year}_{title}")
    names = sorted(p.name for p in root.glob("*.pdf"))
    check("custom pattern applied on rename", any(n.startswith("Lim et al_2021_Anisotropic") for n in names), str(names))
    check("custom pattern: default-pattern file is no longer 'already renamed'",
          not any(r.outcome == core.SKIPPED and r.name == "2019_Already named paper.pdf" for r in res.records))

with tempfile.TemporaryDirectory() as d:          # network down
    root = Path(d)
    build_folder(root)
    sess = FakeSession(script=[core.requests.exceptions.ConnectionError("down")] * 50)
    res = core.run_folder(root, resolver=FakeResolver(sess))
    check("offline: nothing renamed", res.count(core.RENAMED) == 0 and res.offline)
    check("offline: files not resolved with a reason",
          all("Crossref" in r.note for r in res.records if r.outcome == core.NOT_RESOLVED and r.name != "scan.pdf"))
    check("offline: no fallback to creation date year", all(not r.year for r in res.records))
    check("offline: original names intact", (root / "paper1.pdf").exists())

with tempfile.TemporaryDirectory() as d:          # cancel
    root = Path(d)
    build_folder(root)
    ev = threading.Event()
    ev.set()
    res = core.run_folder(root, resolver=FakeResolver(FakeSession(by_doi, by_title)), cancel=ev)
    check("cancel before start renames nothing", res.cancelled and res.count(core.RENAMED) == 0
          and (root / "paper1.pdf").exists())

with tempfile.TemporaryDirectory() as d:          # cancel mid run skips queued files
    root = Path(d)
    for i in range(40):
        (root / f"x{i}.pdf").write_bytes(b"x")
    seen, ev, real = [], threading.Event(), core.resolve_one

    def slow(p, *a, **k):
        seen.append(p)
        time.sleep(0.05)
        return core.Record(path=p)
    core.resolve_one = slow
    try:
        # Progress fires only after every file is queued: Stop pressed mid run.
        res = core.run_folder(root, cancel=ev, progress=lambda *a: ev.set())
    finally:
        core.resolve_one = real
    check("cancel mid run skips queued lookups", res.cancelled and len(seen) < 40, f"{len(seen)} of 40 looked up")

with tempfile.TemporaryDirectory() as d:          # apply keeps a long approved name
    root = Path(d)
    (root / "a.pdf").write_bytes(b"x")
    long_title = ("Anisotropic mechanical response of additively manufactured titanium lattice "
                  "scaffolds under compressive loading for load bearing orthopaedic implants")
    name = core.render_name("2021", long_title, len(str(root)), author="Lim et al",
                            template="{author}_{year}_{title}")
    rec = core.Record(path=root / "a.pdf", outcome=core.NEEDS_LOOK, proposed=name)
    core.apply_records(root, [rec])
    check("apply keeps the approved name, even past 130 characters",
          len(name) > 135 and Path(rec.new_path).name == name, f"{name} -> {Path(rec.new_path).name}")

with tempfile.TemporaryDirectory() as d:          # subfolders
    root = Path(d)
    sub = root / "deeper"
    sub.mkdir()
    build_folder(sub)
    res = core.run_folder(root, recurse=True, resolver=FakeResolver(FakeSession(by_doi, by_title)))
    check("subfolder files handled when asked", res.count(core.RENAMED) == 3)
    res2 = core.run_folder(root, recurse=False, resolver=FakeResolver(FakeSession(by_doi, by_title)))
    check("subfolders ignored by default", len(res2.records) == 0)

# --------------------------------------------------------------------- window --

if HAVE_GUI and (os.environ.get("DISPLAY") or sys.platform.startswith("win")):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        build_folder(root)
        core.Resolver = lambda: FakeResolver(FakeSession(by_doi, by_title))   # window uses this
        from tkinter import messagebox                                         # no modal dialogs
        for fn in ("showerror", "showinfo", "showwarning"):
            setattr(messagebox, fn, lambda *a, **k: print("DIALOG:", a[-1] if a else k))
        try:
            app = gui.App(str(root))
            app.update()
            app.start()
            deadline = time.time() + 20
            while (app.worker and app.worker.is_alive() or app.result is None) and time.time() < deadline:
                app.update()
                time.sleep(0.05)
            app.update()
            rows = [app.tree.item(i, "values") for i in app.tree.get_children()]
            check("window shows one row per PDF (7 incl. the stray)", len(rows) == 7, str(len(rows)))
            check("window renamed the confirmed files", app.result.count(core.RENAMED) == 3)
            check("apply button enabled for the uncertain row", str(app.apply_btn["state"]) == "normal")
            check("status line summarises", "Renamed 3" in app.status_var.get(), app.status_var.get())
            app.destroy()
        except Exception as exc:
            check("window smoke test", False, repr(exc))
else:
    print("skip  window smoke test (no display)")

bad = [n for n, ok in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(bad)} passed, {len(bad)} failed")
if bad:
    print("failing:", *bad, sep="\n  ")
sys.exit(1 if bad else 0)
