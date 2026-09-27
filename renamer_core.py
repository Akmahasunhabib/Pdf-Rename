#!/usr/bin/env python3
"""
Pdf Rename, back end.

No GUI imports live here. The window in pdf_renamer_app.py calls run_folder()
on a worker thread and reads back a RunResult. Keeping the two apart means the
logic can be tested on any machine, with a fake Crossref and handmade PDFs,
and the window stays a thin layer that only shows results.

What one file goes through
--------------------------
    read first pages + metadata   (pypdf, one open per file)
        |
        v
    every DOI printed on those pages, ranked by how often it appears
        |
        v
    Crossref /works/{doi}  -->  record (title, year, first author)
        |
        v
    does the record's title actually appear in the PDF text?
        |
        +-- yes, >= 60 percent of its words  --> CONFIRMED  --> renamed now
        |
        +-- no  --> try a title search, then list as NEEDS A LOOK
                    with a proposed name for the user to approve

The publication year is Crossref's "issued" field. The PDF's own creation
date is never used as a year, because it is the date the file was made, not
the date the paper came out.

A failed Crossref call (429, 5xx, timeout, no network) is reported as
"not resolved". It is never treated as "no record", and it never triggers a
weaker fallback, since a wrong year written quietly is worse than no rename.
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import requests
from pypdf import PdfReader

APP_NAME = "Pdf Rename"
APP_VERSION = "3.0"

CROSSREF_WORK = "https://api.crossref.org/works/"
CROSSREF_QUERY = "https://api.crossref.org/works"

# Crossref asks scripted users for a contact address. It routes them to a
# faster pool and lets them reach you if something misbehaves. Put your own
# address here, or set "contact_email" in the settings file, which wins.
CONTACT_EMAIL = "your.email@ttu.edu"
PLACEHOLDER_EMAILS = {"", "your.email@ttu.edu", "you@example.com"}

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
DOI_TRAIL = ".,;:)]}>'\""
TAG_RE = re.compile(r"<[^>]+>")
INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WS_RE = re.compile(r"\s+")
# Name patterns. {year} and {title} are required; {author} {journal} {doi}
# are optional. The first entry is the default.
TEMPLATES = [
    "{year}_{title}",
    "{year}_{author}_{title}",
    "{author}_{year}_{title}",
    "{year}_{journal}_{title}",
    "{author} ({year}) {title}",
]
DEFAULT_TEMPLATE = TEMPLATES[0]
TOKENS = ("year", "title", "author", "journal", "doi")
TOKEN_RE = re.compile(r"\{([a-z]+)\}")

# Windows tolerates 260 characters for a full path. Leave room.
PATH_LIMIT = 250
TITLE_CEILING = 130
RESERVE = 10                     # separator, ".pdf", " (2)" collision suffix

PAGES_TO_READ = 2
MAX_DOI_LOOKUPS = 3              # distinct DOIs tried per file
DOI_SUPPORT_THRESHOLD = 0.60     # title words that must appear in the PDF
TITLE_CONFIRM_THRESHOLD = 0.90   # title search similarity to confirm
TITLE_LIST_THRESHOLD = 0.75      # title search similarity to list for review
WORKERS = 4                      # parallel Crossref lookups

LOG_PREFIX = "_pdfrenamer_log_"
STAGING_PREFIX = "__pdfrenamer_staging_"

# Outcomes, in the order the window lists them.
RENAMED = "Renamed"
CONFIRMED = "Confirmed"          # internal, becomes RENAMED or FAILED
NEEDS_LOOK = "Needs a look"
NOT_RESOLVED = "Not resolved"
SKIPPED = "Skipped"
FAILED = "Failed"
OUTCOME_ORDER = [RENAMED, NEEDS_LOOK, FAILED, NOT_RESOLVED, SKIPPED]

SRC_DOI = "DOI in PDF"
SRC_DOI_WEAK = "DOI in PDF, title not seen in text"
SRC_TITLE = "Title search"
SRC_NONE = ""

LOOKUP_OK = "ok"
LOOKUP_NOT_FOUND = "not_found"
LOOKUP_FAILED = "failed"


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------

def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = Path(base) / "PDFRenamer"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return folder / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        current = load_settings()
        current.update(data)
        settings_path().write_text(json.dumps(current, indent=2), encoding="utf-8")
    except Exception:
        pass


def contact_email() -> str:
    value = str(load_settings().get("contact_email") or "").strip()
    return value or CONTACT_EMAIL


def polite_pool_ready() -> bool:
    address = contact_email()
    return address not in PLACEHOLDER_EMAILS and "@" in address


# ----------------------------------------------------------------------------
# Text helpers
# ----------------------------------------------------------------------------

def clean_biblio_text(text: str) -> str:
    """Crossref titles carry markup and entities. Strip both."""
    if not text:
        return ""
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text).strip()
    if text and text.isupper() and len(text) > 12:
        text = text.title()
    return text


def sanitize(text: str, budget: int, ceiling: int = TITLE_CEILING) -> str:
    """Make a fragment safe for a Windows filename, within a length budget."""
    if not text:
        return ""
    text = text.replace(":", " -").replace("/", "-").replace("\\", "-")
    text = INVALID_RE.sub("", text)
    text = WS_RE.sub(" ", text).strip().rstrip(". ")
    limit = max(20, min(ceiling, budget))
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(". ,")
    return text


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def word_set(text: str) -> set:
    return set(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def title_support(title: str, text: str) -> float:
    """Fraction of the title's words (longer than 3 letters) found in text."""
    words = [w for w in word_set(title) if len(w) > 3]
    if not words or not text:
        return 0.0
    body = word_set(text)
    return sum(1 for w in words if w in body) / len(words)


def surname_in_text(author: str, text: str) -> bool:
    """author is 'Family' or 'Family et al'. True if Family is in the text."""
    family = (author or "").replace(" et al", "").strip()
    if len(family) < 3 or not text:
        return False
    return family.lower() in (text or "").lower()


def validate_template(template: str) -> str:
    """Return an error message, or "" when the pattern is usable."""
    t = (template or "").strip()
    if not t:
        return "The pattern is empty."
    found = TOKEN_RE.findall(t)
    unknown = [f for f in found if f not in TOKENS]
    if unknown:
        return "Unknown token {" + unknown[0] + "}. Use {year} {title} {author} {journal} {doi}."
    if "{year}" not in t or "{title}" not in t:
        return "The pattern needs both {year} and {title}."
    if INVALID_RE.search(TOKEN_RE.sub("", t)):
        return "The pattern contains a character Windows does not allow in file names."
    return ""


def render_name(year: str, title: str, folder_len: int, author: str = "",
                journal: str = "", doi: str = "", template: str = DEFAULT_TEMPLATE) -> str:
    """Fill the pattern, keeping the whole path inside the Windows limit.

    The fixed tokens are laid out first with a placeholder where the title
    goes, so the title gets exactly the room that is left. A final clamp on
    the finished name covers patterns with long literal text.
    """
    if not year or not title:
        return ""
    if validate_template(template):
        template = DEFAULT_TEMPLATE
    slot = "\x00TITLE\x00"
    parts = {
        "year": year,
        "title": slot,
        "author": sanitize(author, 40) or "Unknown",
        "journal": sanitize(journal, 45) or "Unknown",
        "doi": sanitize((doi or "").replace("/", "_"), 60) or "nodoi",
    }
    skeleton = template.format(**parts)
    fixed = len(skeleton) - len(slot)
    budget = PATH_LIMIT - folder_len - fixed - RESERVE
    name = skeleton.replace(slot, sanitize(title, budget))
    name = WS_RE.sub(" ", name).strip().rstrip(". ")
    room = max(8, PATH_LIMIT - folder_len - RESERVE)
    if len(name) > room:
        cut = name[:room]
        name = (cut.rsplit(" ", 1)[0] if " " in cut[20:] else cut).rstrip("_ -.,")
    return f"{name}.pdf"


def template_regex(template: str = DEFAULT_TEMPLATE) -> re.Pattern:
    """A regex that matches file names already produced by this pattern."""
    if validate_template(template):
        template = DEFAULT_TEMPLATE
    out, pos = "^", 0
    for m in TOKEN_RE.finditer(template):
        out += re.escape(template[pos:m.start()])
        out += r"(19|20)\d{2}" if m.group(1) == "year" else r".{3,}?"
        pos = m.end()
    out += re.escape(template[pos:]) + r"\.pdf$"
    return re.compile(out, re.IGNORECASE)


def looks_renamed(name: str, template: str = DEFAULT_TEMPLATE) -> bool:
    return bool(template_regex(template).match(name))


def example_name(template: str = DEFAULT_TEMPLATE) -> str:
    """What a real paper would be called under this pattern, for the window."""
    return render_name("2021", "Anisotropic mechanical response of lattice scaffolds", 40,
                       author="Lim et al", journal="Acta Biomater", doi="10.1016/j.actbio.2021.01.001",
                       template=template)


# ----------------------------------------------------------------------------
# Reading the PDF
# ----------------------------------------------------------------------------

def read_pdf(path: Path) -> tuple:
    """Return (text of the first pages, metadata dict, error note)."""
    try:
        if path.stat().st_size == 0:
            return "", {}, "Empty file"
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return "", {}, "Password protected"
        chunks = []
        for page in reader.pages[:PAGES_TO_READ]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                chunks.append("")
        meta = {}
        try:
            for key, value in (reader.metadata or {}).items():
                meta[str(key)] = str(value) if value is not None else ""
        except Exception:
            pass
        return "\n".join(chunks), meta, ""
    except Exception as exc:
        return "", {}, f"Could not read PDF ({type(exc).__name__})"


def find_dois(text: str, meta: dict) -> list:
    """DOIs on the first pages, most frequent first, then earliest.

    The paper's own DOI is usually printed more than once (header, footer,
    citation box). A reference list DOI appears once. Metadata DOIs are
    appended last since publishers do not fill that field consistently.
    """
    counts, first_pos = {}, {}
    for m in DOI_RE.finditer(text or ""):
        doi = m.group(0).rstrip(DOI_TRAIL)
        counts[doi] = counts.get(doi, 0) + 1
        first_pos.setdefault(doi, m.start())
    ordered = sorted(counts, key=lambda d: (-counts[d], first_pos[d]))
    for value in (meta or {}).values():
        for m in DOI_RE.finditer(value or ""):
            doi = m.group(0).rstrip(DOI_TRAIL)
            if doi not in ordered:
                ordered.append(doi)
    return ordered[:MAX_DOI_LOOKUPS]


def doi_candidates(doi: str) -> list:
    """Trimmed forms of a DOI, longest first.

    Text extraction runs the DOI into whatever follows it on the page:
    10.1016/j.actbio.2021.01.001Received, or ...-8www.nature.com. A shorter
    form is only tried after the longer one comes back as a genuine 404.
    """
    out = []

    def add(value: str) -> None:
        value = (value or "").rstrip(DOI_TRAIL)
        if value and value not in out and DOI_RE.fullmatch(value):
            out.append(value)

    add(doi)
    lowered = doi.lower()
    for marker in ("www.", "http", ".pdf", "downloaded", "received", "abstract"):
        idx = lowered.find(marker, 8)
        if idx > 0:
            add(doi[:idx])
    glued = re.match(r"^(.*\d)[A-Za-z]{3,}$", doi)
    if glued:
        add(glued.group(1))
    return out[:3]


def embedded_title(meta: dict) -> str:
    title = clean_biblio_text(meta.get("/Title", ""))
    low = title.lower()
    junk_starts = ("microsoft word", "untitled", "document", "pdf", "none",
                   "print", "layout", "slide", "doi", "http")
    if len(title) < 12 or low.startswith(junk_starts) or ".doc" in low:
        return ""
    return title


def guess_title(text: str) -> str:
    """Longest plausible heading line near the top. Always needs checking."""
    if not text:
        return ""
    lines = [WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    candidates = [
        ln for ln in lines[:25]
        if 25 <= len(ln) <= 250
        and not ln.lower().startswith(("doi", "http", "www", "abstract", "keywords"))
        and sum(c.isdigit() for c in ln) < len(ln) * 0.3
    ]
    if not candidates:
        return ""
    return max(candidates[:10], key=len)


# ----------------------------------------------------------------------------
# Crossref
# ----------------------------------------------------------------------------

def parse_message(msg: dict) -> dict:
    title = clean_biblio_text((msg.get("title") or [""])[0])
    year = ""
    for key in ("issued", "published-print", "published-online", "published"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    author = ""
    authors = msg.get("author") or []
    if authors:
        first = authors[0]
        author = clean_biblio_text(first.get("family") or first.get("name") or "")
        if len(authors) > 1 and author:
            author = f"{author} et al"
    journal = ""
    for key in ("short-container-title", "container-title"):
        vals = msg.get(key) or []
        if vals and vals[0]:
            journal = clean_biblio_text(vals[0])
            break
    return {"title": title, "year": year, "author": author,
            "journal": journal, "doi": msg.get("DOI", "")}


class Resolver:
    """Crossref client. Separates "no record" from "the call failed".

    Thread safe: each worker thread gets its own requests.Session. The
    offline flag is shared on purpose, so one dead network stops every
    thread from hammering it.
    """

    def __init__(self):
        self._local = threading.local()
        self.offline = False
        self.failures = 0
        self.calls = 0

    @property
    def session(self):
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update(
                {"User-Agent": f"PdfRename/{APP_VERSION} (mailto:{contact_email()})"}
            )
            self._local.session = s
        return s

    def _get(self, url, params=None, timeout=15, attempts=3):
        delay = 1.0
        for attempt in range(attempts):
            if self.offline:
                return None, LOOKUP_FAILED
            self.calls += 1
            try:
                r = self.session.get(url, params=params, timeout=timeout)
            except requests.exceptions.Timeout:
                # Before ConnectionError: ConnectTimeout subclasses both, and
                # a slow reply is not evidence that the network is down.
                if attempt + 1 == attempts:
                    return None, LOOKUP_FAILED
                time.sleep(delay)
                delay *= 2
                continue
            except requests.exceptions.ConnectionError:
                self.offline = True
                return None, LOOKUP_FAILED
            except Exception:
                return None, LOOKUP_FAILED

            if r.status_code == 200:
                return r, LOOKUP_OK
            if r.status_code in (400, 404):
                return None, LOOKUP_NOT_FOUND
            if r.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                wait = r.headers.get("Retry-After")
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = delay
                time.sleep(min(max(wait, 0.5), 10.0))
                delay *= 2
                continue
            return None, LOOKUP_FAILED
        return None, LOOKUP_FAILED

    def by_doi(self, doi: str):
        status = LOOKUP_NOT_FOUND
        for candidate in doi_candidates(doi):
            r, status = self._get(CROSSREF_WORK + candidate)
            if status == LOOKUP_OK:
                try:
                    return parse_message(r.json().get("message", {})), status
                except ValueError:
                    return None, LOOKUP_FAILED
            if status == LOOKUP_FAILED:
                self.failures += 1
                return None, status
        return None, status

    def by_title(self, title: str):
        if not title:
            return None, LOOKUP_NOT_FOUND
        r, status = self._get(
            CROSSREF_QUERY,
            params={"query.bibliographic": title, "rows": 3,
                    "select": "title,issued,author,container-title,"
                              "short-container-title,DOI,published-print,"
                              "published-online"},
            timeout=20,
        )
        if status != LOOKUP_OK:
            if status == LOOKUP_FAILED:
                self.failures += 1
            return None, status
        try:
            items = r.json().get("message", {}).get("items", []) or []
        except ValueError:
            return None, LOOKUP_FAILED
        best, best_score = None, 0.0
        for item in items:
            parsed = parse_message(item)
            score = similarity(title, parsed["title"])
            if score > best_score:
                best, best_score = parsed, score
        if best and best_score >= TITLE_LIST_THRESHOLD:
            best["match_score"] = best_score
            return best, LOOKUP_OK
        return None, LOOKUP_NOT_FOUND


# ----------------------------------------------------------------------------
# One file
# ----------------------------------------------------------------------------

@dataclass
class Record:
    path: Path
    outcome: str = NOT_RESOLVED
    source: str = SRC_NONE
    year: str = ""
    title: str = ""
    author: str = ""
    journal: str = ""
    doi: str = ""
    note: str = ""
    proposed: str = ""
    new_path: str = ""
    support: float = 0.0
    score: float = 0.0

    @property
    def name(self) -> str:
        return self.path.name

    def take(self, data: dict) -> None:
        self.year = data.get("year", "")
        self.title = data.get("title", "")
        self.author = data.get("author", "")
        self.journal = data.get("journal", "")
        self.doi = data.get("doi", "") or self.doi


def resolve_one(path: Path, resolver: Resolver, folder_len: int,
                template: str = DEFAULT_TEMPLATE) -> Record:
    """Decide what one PDF is. Pure function apart from Crossref calls."""
    rec = Record(path=path)
    text, meta, read_error = read_pdf(path)
    if read_error:
        rec.note = read_error
        return rec

    lookup_failed = False
    weak = None                      # best DOI hit whose title is not in the text

    for doi in find_dois(text, meta):
        data, status = resolver.by_doi(doi)
        if status == LOOKUP_FAILED:
            lookup_failed = True
            rec.note = "Crossref could not be reached"
            break
        if not (data and data["year"] and data["title"]):
            continue
        support = title_support(data["title"], text)
        if support >= DOI_SUPPORT_THRESHOLD:
            rec.take(data)
            rec.support = support
            rec.source = SRC_DOI
            rec.outcome = CONFIRMED
            break
        if weak is None or support > weak[1]:
            weak = (data, support)

    if rec.outcome != CONFIRMED and not lookup_failed:
        probe = embedded_title(meta) or guess_title(text)
        if probe:
            data, status = resolver.by_title(probe)
            if status == LOOKUP_FAILED:
                lookup_failed = True
                rec.note = "Crossref could not be reached"
            elif data and data["year"] and data["title"]:
                score = data.get("match_score", 0.0)
                support = title_support(data["title"], text)
                rec.take(data)
                rec.support, rec.score = support, score
                rec.source = SRC_TITLE
                if (score >= TITLE_CONFIRM_THRESHOLD
                        and support >= DOI_SUPPORT_THRESHOLD
                        and surname_in_text(data["author"], text)):
                    rec.outcome = CONFIRMED
                else:
                    rec.outcome = NEEDS_LOOK
                    rec.note = (f"Found by title search (similarity {score:.2f}). "
                                f"No DOI confirmed it. Check the year and title.")

    if rec.outcome == NOT_RESOLVED and weak is not None and not lookup_failed:
        data, support = weak
        rec.take(data)
        rec.support = support
        rec.source = SRC_DOI_WEAK
        rec.outcome = NEEDS_LOOK
        rec.note = (f"A DOI in the PDF resolved, but only {support:.0%} of that "
                    f"title's words appear in the text. It may belong to a cited "
                    f"paper. Check before applying.")

    if rec.outcome == NOT_RESOLVED and not rec.note:
        if not text.strip():
            rec.note = "No text layer (scanned?). Name it by hand."
        else:
            rec.note = "No DOI found and no title match. Name it by hand."

    if rec.year and rec.title:
        rec.proposed = render_name(rec.year, rec.title, folder_len, author=rec.author,
                                   journal=rec.journal, doi=rec.doi, template=template)
        if rec.proposed.lower() == rec.name.lower():
            rec.outcome = SKIPPED
            rec.note = "Already has the right name"
    return rec


# ----------------------------------------------------------------------------
# The folder
# ----------------------------------------------------------------------------

@dataclass
class RunResult:
    folder: Path
    records: list = field(default_factory=list)
    others: int = 0
    offline: bool = False
    log_path: str = ""
    cancelled: bool = False

    def count(self, outcome: str) -> int:
        return sum(1 for r in self.records if r.outcome == outcome)


def collect(folder: Path, recurse: bool, recheck: bool, template: str = DEFAULT_TEMPLATE):
    """Return (pdfs to look at, records already decided, other file count)."""
    walker = folder.rglob("*") if recurse else folder.iterdir()
    todo, decided, others = [], [], 0
    for p in sorted(walker):
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        name = p.name
        if name.startswith((LOG_PREFIX, STAGING_PREFIX)):
            continue
        if p.suffix.lower() != ".pdf":
            others += 1
            continue
        if not recheck and looks_renamed(name, template):
            decided.append(Record(path=p, outcome=SKIPPED,
                                  note="Already in the chosen pattern"))
            continue
        todo.append(p)
    return todo, decided, others


def assign_unique_names(records: list) -> None:
    """Two files can want the same name. Give the second one a suffix.

    Names are unique per parent folder, case insensitive, and never collide
    with a file that already exists there unless that file is itself being
    renamed in this run.
    """
    live = [r for r in records if r.proposed and r.outcome in (CONFIRMED, NEEDS_LOOK)]
    moving = {os.path.normcase(str(r.path)) for r in live}
    taken = {}
    for rec in live:
        parent = rec.path.parent
        base, name, n = rec.proposed[:-4], rec.proposed, 2
        while True:
            key = os.path.normcase(str(parent / name))
            exists = (parent / name).exists() and key not in moving
            if key not in taken and not exists:
                break
            name = f"{base} ({n}).pdf"
            n += 1
        taken[key] = True
        rec.proposed = name


def execute_plan(plan: list):
    """Rename (src, dst) pairs without ever overwriting a file.

    Handles chains (A -> B while B -> C) and swaps by moving every file to a
    staging name first. Targets blocked by a file outside the plan are dropped
    before anything moves, iterating because dropping one can strand another.
    Path.rename overwrites silently on POSIX and raises on Windows, so
    existence is always checked explicitly.
    """
    done, errors = [], []
    runnable = list(plan)
    while True:
        sources = {os.path.normcase(str(src)) for src, _ in runnable}
        blocked = [(src, dst) for src, dst in runnable
                   if dst.exists() and os.path.normcase(str(dst)) not in sources]
        if not blocked:
            break
        for src, _ in blocked:
            errors.append((src, "a file with the new name already exists"))
        runnable = [pair for pair in runnable if pair not in blocked]

    chained = any(os.path.normcase(str(dst)) in sources for _, dst in runnable)

    if not chained:
        for src, dst in runnable:
            if dst.exists():
                errors.append((src, "a file with the new name already exists"))
                continue
            try:
                src.rename(dst)
                done.append((src, dst))
            except PermissionError:
                errors.append((src, "file is open in another program, or the folder is read only"))
            except Exception as exc:
                errors.append((src, str(exc)))
        return done, errors

    stamp = datetime.now().strftime("%H%M%S")
    staged = []
    for i, (src, dst) in enumerate(runnable):
        tmp = src.parent / f"{STAGING_PREFIX}{stamp}_{i}__.pdf"
        try:
            src.rename(tmp)
            staged.append((src, tmp, dst))
        except PermissionError:
            errors.append((src, "file is open in another program, or the folder is read only"))
        except Exception as exc:
            errors.append((src, str(exc)))
    for src, tmp, dst in staged:
        try:
            if dst.exists():
                raise FileExistsError("a file with the new name appeared during the run")
            tmp.rename(dst)
            done.append((src, dst))
        except Exception as exc:
            errors.append((src, str(exc)))
            if not src.exists():
                try:
                    tmp.rename(src)
                except Exception:
                    errors.append((src, f"left as {tmp.name}"))
            else:
                errors.append((src, f"left as {tmp.name}"))
    return done, errors


def rename_records(records: list) -> None:
    """Rename every record with a proposed name, updating outcomes in place."""
    todo = [r for r in records if r.proposed and r.outcome in (CONFIRMED, NEEDS_LOOK)]
    plan = [(r.path, r.path.parent / r.proposed) for r in todo]
    done, errors = execute_plan(plan)
    by_src = {os.path.normcase(str(r.path)): r for r in todo}
    for src, dst in done:
        rec = by_src[os.path.normcase(str(src))]
        rec.outcome = RENAMED
        rec.new_path = str(dst)
    for src, why in errors:
        rec = by_src.get(os.path.normcase(str(src)))
        if rec is not None and rec.outcome != RENAMED:
            rec.outcome = FAILED
            rec.note = why


def write_log(folder: Path, records: list) -> str:
    # Two logs in the same second (a run, then "apply") must not share a
    # name, or the second silently replaces the first and undo loses a step.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = folder / f"{LOG_PREFIX}{stamp}.csv"
    n = 2
    while log.exists():
        log = folder / f"{LOG_PREFIX}{stamp}_{n}.csv"
        n += 1
    try:
        with open(log, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["original_path", "new_path", "outcome", "source",
                        "year", "title", "doi", "note"])
            for r in records:
                w.writerow([str(r.path), r.new_path, r.outcome, r.source,
                            r.year, r.title, r.doi, r.note])
        return str(log)
    except Exception:
        return ""


def run_folder(folder: Path, recurse: bool = False, recheck: bool = False,
               progress=None, cancel: threading.Event = None,
               resolver: Resolver = None, template: str = DEFAULT_TEMPLATE) -> RunResult:
    """Scan a folder, rename every confirmed PDF, list the rest.

    progress(i, n, filename) is called as files finish. cancel is a
    threading.Event; when set, no new lookups start and nothing is renamed.
    """
    folder = Path(folder)
    result = RunResult(folder=folder)
    if validate_template(template):
        template = DEFAULT_TEMPLATE
    todo, decided, result.others = collect(folder, recurse, recheck, template)
    result.records.extend(decided)
    resolver = resolver or Resolver()
    cancel = cancel or threading.Event()

    def task(p: Path):
        # Every file is queued at once, so the cancel check has to happen
        # here, when a worker picks the file up, or Stop waits for them all.
        if cancel.is_set():
            return None
        # Budget against the file's own folder: with subfolders included
        # the parent can be deeper than the folder that was chosen.
        return resolve_one(p, resolver, len(str(p.parent)), template)

    resolved = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {}
        for p in todo:
            if cancel.is_set():
                break
            futures[pool.submit(task, p)] = p
        for i, fut in enumerate(as_completed(futures), start=1):
            p = futures[fut]
            try:
                rec = fut.result()
            except Exception as exc:
                rec = Record(path=p, note=f"Unexpected error: {exc}")
            if rec is not None:
                resolved[p] = rec
            if progress:
                progress(i, len(futures), p.name)

    result.records.extend(resolved[p] for p in todo if p in resolved)
    result.offline = resolver.offline
    result.cancelled = cancel.is_set()

    if result.cancelled:
        for r in result.records:
            if r.outcome == CONFIRMED:
                r.outcome = NEEDS_LOOK
                r.note = "Run was cancelled before renaming"
        return result

    assign_unique_names(result.records)
    confirmed = [r for r in result.records if r.outcome == CONFIRMED]
    rename_records(confirmed)
    result.log_path = write_log(folder, result.records)
    result.records.sort(key=lambda r: (OUTCOME_ORDER.index(r.outcome)
                                       if r.outcome in OUTCOME_ORDER else 99,
                                       r.name.lower()))
    return result


def apply_records(folder: Path, records: list) -> str:
    """Rename user approved NEEDS_LOOK records. Returns the log path.

    Only this step's files go in the new log, so one Undo reverses the apply
    and a second Undo reverses the run before it.
    """
    pending = [r for r in records if r.outcome == NEEDS_LOOK and r.proposed]
    for r in pending:
        if not r.proposed.lower().endswith(".pdf"):
            r.proposed += ".pdf"
        # The whole name, not just a title, so the title ceiling does not
        # apply: only the path limit render_name already respected.
        room = max(8, PATH_LIMIT - len(str(r.path.parent)) - RESERVE)
        r.proposed = sanitize(r.proposed[:-4], room, ceiling=room) + ".pdf"
    assign_unique_names(records)
    rename_records(pending)
    return write_log(Path(folder), [r for r in pending if r.outcome in (RENAMED, FAILED)])


# ----------------------------------------------------------------------------
# Undo
# ----------------------------------------------------------------------------

def find_logs(folder: Path) -> list:
    try:
        return sorted(Path(folder).glob(f"{LOG_PREFIX}*.csv"), reverse=True)
    except Exception:
        return []


def undo_last(folder: Path):
    """Put the names from the newest log back. Returns (restored, errors, log)."""
    logs = find_logs(folder)
    if not logs:
        return 0, [], None
    log = logs[0]
    with open(log, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("outcome") == RENAMED]
    plan, errors = [], []
    for row in rows:
        current, original = Path(row["new_path"]), Path(row["original_path"])
        if not current.exists():
            errors.append((current, "no longer present"))
            continue
        plan.append((current, original))
    done, run_errors = execute_plan(plan)
    errors.extend(run_errors)
    if len(done) == len(rows) and not errors:
        try:
            log.unlink()
        except Exception:
            pass
    return len(done), [(p.name, why) for p, why in errors], log
