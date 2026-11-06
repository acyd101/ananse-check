"""Check the Bank of Ghana website for new notices on unlicensed digital credit
providers, and add any new loan apps to data/unlicensed-loan-apps.csv.

Run by .github/workflows/update-bog-list.yml, or by hand:
    pip install -r tools/requirements.txt
    python3 tools/update_from_bog.py

What it does, in order:
 1. Reads the Bank of Ghana search results for "unlicensed digital credit".
 2. Opens each notice page and collects its PDF.
 3. SELF-CHECK: re-reads the newest notice already in the CSV and checks that it
    gets exactly the same names. If not, the Bank may have changed its format,
    so it changes nothing and reports a problem.
 4. Reads each PDF it hasn't seen before: the notice number, the date and the
    numbered table of app names. Every new list must pass strict checks
    (numbers 1..N with no gaps, every name found in the PDF text, two reading
    methods agreeing) or it is reported as a problem instead of being added.
 5. Appends the new rows, logs every PDF it read in data/processed-notices.csv,
    refreshes the built-in copy in index.html, and writes .bog-update/status.json
    and .bog-update/summary.md for the workflow.

It only ever ADDS names the Bank of Ghana itself published. It never removes rows.
"""
import argparse, csv, datetime, io, json, os, re, subprocess, sys, time, urllib.parse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_QUERY = "unlicensed digital credit"
MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
          "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
CSV_FIELDS = ["name", "notice", "notice_date", "notice_url"]
LOG_FIELDS = ["notice", "notice_date", "pdf_url", "apps_found", "checked_on"]
HEADER_WORDS = {"no", "name of loan app", "name of loan apps", "name"}


# ---------------------------------------------------------------- fetching
def make_session():
    s = requests.Session()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    contact = f" (+https://github.com/{repo})" if repo else ""
    s.headers["User-Agent"] = "AnanseCheck-updater/1.0" + contact
    return s


def fetch(session, url, binary=False, tries=3):
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content if binary else r.text
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"Could not download {url}: {last}")


def notice_pages(session, base):
    """Notice page URLs from the search results (up to 5 result pages)."""
    pages, q = [], urllib.parse.quote_plus(SEARCH_QUERY)
    for n in range(1, 6):
        url = f"{base}/?s={q}" if n == 1 else f"{base}/page/{n}/?s={q}"
        html = fetch(session, url)
        if not html:
            break
        found = 0
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            text = " ".join(a.get_text(" ").split()).lower()
            href = urllib.parse.urljoin(url, a["href"])
            if "unlicensed digital credit" in text and href.startswith(base) and href not in pages:
                pages.append(href)
                found += 1
        if not found:
            break
    return pages


def pdf_links(session, page_url):
    html = fetch(session, page_url) or ""
    out = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = urllib.parse.urljoin(page_url, a["href"])
        if href.lower().split("?")[0].endswith(".pdf") and "unlicensed" in href.lower() and href not in out:
            out.append(href)
    return out


# ---------------------------------------------------------------- reading a notice PDF
def clean(s):
    return " ".join(str(s or "").split())


def squash(s):
    return re.sub(r"\s+", "", str(s or ""))


def number_from_filename(url):
    m = re.search(r"Notice-No\.?\s*(\d+)-BOG-SEC-GOV-(\d{4})", urllib.parse.unquote(url), re.I)
    return (int(m.group(2)), int(m.group(1))) if m else None


def read_notice_number(text, date_year):
    m = re.search(r"NOTICENO\.?BG/GOV/SEC/(?:(\d{4})/)?(\d{1,3})(?!\d)", squash(text).upper())
    if not m:
        return None
    year = int(m.group(1)) if m.group(1) else date_year
    return (year, int(m.group(2))) if year else None


def read_date(text):
    pat = r"(\d{1,2})(?:ST|ND|RD|TH)?(" + "|".join(MONTHS) + r"),?(\d{4})"
    hits = list(re.finditer(pat, squash(text).upper()))
    if not hits:
        return None
    d, mon, y = hits[-1].groups()          # the signature date sits at the end
    try:
        return datetime.date(int(y), MONTHS.index(mon) + 1, int(d)).isoformat()
    except ValueError:
        return None


def pairs_from_tables(pdf):
    pairs = []
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            for row in table:
                cells = [clean(c) for c in row if c is not None and clean(c)]
                i = 0
                while i < len(cells) - 1:
                    if re.fullmatch(r"\d{1,3}", cells[i]) and not re.fullmatch(r"\d{1,3}", cells[i + 1]):
                        pairs.append((int(cells[i]), cells[i + 1]))
                        i += 2
                    else:
                        i += 1
    return pairs


def pairs_from_text(text):
    starts = list(re.finditer(r"NAME\s+OF\s+LOAN\s+APPS?", text, re.I))
    if not starts:
        return []
    seg = text[starts[-1].end():]
    end = re.search(r"The\s+Bank\s+reiterates|The\s+Bank\s+of\s+Ghana\s+will|The\s+general\s+public", seg, re.I)
    seg = clean(seg[: end.start()] if end else seg)
    return [(int(n), clean(name)) for n, name in
            re.findall(r"(?:^|(?<=\s))(\d{1,3})\s+(.+?)(?=\s+\d{1,3}\s+|\s*$)", seg)]


def check_pairs(pairs, raw_text):
    """Return (names in number order, list of problems)."""
    problems = []
    if not pairs:
        return [], ["no numbered names found"]
    by_no = {}
    for n, name in pairs:
        if n in by_no and by_no[n] != name:
            problems.append(f"number {n} appears twice ({by_no[n]!r} and {name!r})")
        by_no[n] = name
    nums = sorted(by_no)
    if nums != list(range(1, len(nums) + 1)):
        problems.append(f"numbers are not 1..{len(nums)} without gaps: {nums}")
    if len(nums) > 200:
        problems.append(f"{len(nums)} names is more than expected")
    flat = squash(raw_text).lower()
    for n in nums:
        name = by_no[n]
        if not (2 <= len(name) <= 60) or not re.search(r"[A-Za-z]", name) or name.lower() in HEADER_WORDS:
            problems.append(f"number {n}: {name!r} does not look like an app name")
        elif squash(name).lower() not in flat:
            problems.append(f"number {n}: {name!r} is not in the PDF text")
    return [by_no[n] for n in nums], problems


def reconcile(a, b):
    """Combine two readings of the same numbered list.

    PDF table cells sometimes crop long names ("Quic" for "Quick Eazzy"),
    so when one reading is only a cut-off start of the other, keep the
    longer one. Returns (names, how many were cut short), or (None, 0)
    when the readings really disagree.
    """
    if len(a) != len(b):
        return None, 0
    out, cut = [], 0
    for x, y in zip(a, b):
        sx, sy = squash(x).lower(), squash(y).lower()
        if sx == sy:
            out.append(x)
        elif sy.startswith(sx) or sx.startswith(sy):
            out.append(x if len(sx) > len(sy) else y)
            cut += 1
        else:
            return None, 0
    return out, cut


def parse_notice(pdf_bytes, url):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        table_pairs = pairs_from_tables(pdf)
    if not squash(text):
        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages)

    date = read_date(text)
    number = read_notice_number(text, int(date[:4]) if date else None)
    from_file = number_from_filename(url)
    problems = []
    if not date:
        problems.append("could not read the notice date")
    if not number:
        number = from_file
        if not number:
            problems.append("could not read the notice number")
    elif from_file and from_file != number:
        problems.append(f"notice number in the PDF ({number}) does not match the file name ({from_file})")
    notice = f"BG/GOV/SEC/{number[0]}/{number[1]}" if number else None

    has_list = bool(re.search(r"NAME\s+OF\s+LOAN\s+APP", text, re.I)) or bool(table_pairs)
    if not has_list:
        return {"notice": notice, "notice_date": date, "names": [], "problems": problems, "method": "no list in this notice"}

    t_names, t_prob = check_pairs(table_pairs, text)
    x_names, x_prob = check_pairs(pairs_from_text(text), text)
    if not t_prob and not x_prob:
        names, cut = reconcile(t_names, x_names)
        if names is None:
            names = t_names
            problems.append("the two reading methods disagree: table=" + json.dumps(t_names) + " text=" + json.dumps(x_names))
        method = "table and text agree"
        if cut:
            method += f" ({cut} name(s) were cut short by one reader; the full name was kept)"
    elif not t_prob:
        names, method = t_names, "table"
    elif not x_prob:
        names, method = x_names, "text"
    else:
        names, method = [], "failed"
        problems += ["table reading: " + "; ".join(t_prob), "text reading: " + "; ".join(x_prob)]
    return {"notice": notice, "notice_date": date, "names": names, "problems": problems, "method": method}


# ---------------------------------------------------------------- files
def read_csv(path, fields):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: (r.get(k) or "").strip() for k in fields} for r in csv.DictReader(f)]


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BOG_BASE_URL", "https://www.bog.gov.gh"))
    ap.add_argument("--root", default=ROOT)
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    data_csv = os.path.join(args.root, "data", "unlicensed-loan-apps.csv")
    log_csv = os.path.join(args.root, "data", "processed-notices.csv")
    out_dir = os.path.join(args.root, ".bog-update")
    os.makedirs(out_dir, exist_ok=True)
    today = datetime.date.today().isoformat()

    rows = read_csv(data_csv, CSV_FIELDS)
    log = read_csv(log_csv, LOG_FIELDS)
    known_notices = {r["notice"] for r in rows} | {r["notice"] for r in log if r["notice"]}
    seen_urls = {r["notice_url"] for r in rows} | {r["pdf_url"] for r in log}
    status = {"status": "no-change", "checked_on": today, "new_apps": 0, "notices": [], "problems": []}
    session = make_session()

    def finish():
        # "updated" = new rows were added (any problems are reported as well);
        # "problem" = nothing was added and something needs a human; "no-change" = all fine, nothing new
        if status["problems"] and status["status"] != "updated":
            status["status"] = "problem"
        if status["status"] != "problem":
            # shown on the website ("last checked ..."); left alone when the check could not finish
            all_rows = read_csv(data_csv, CSV_FIELDS)
            newest_row = max(all_rows, key=lambda r: (r["notice_date"], r["notice"])) if all_rows else {}
            with open(os.path.join(args.root, "data", "last-checked.json"), "w", encoding="utf-8") as f:
                json.dump({"checked_on": today, "latest_notice": newest_row.get("notice", ""),
                           "latest_notice_date": newest_row.get("notice_date", "")}, f, indent=2)
                f.write("\n")
        with open(os.path.join(out_dir, "status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)
        lines = []
        if status["notices"]:
            lines.append(f"Added **{status['new_apps']}** loan apps from new Bank of Ghana notices.\n")
            for n in status["notices"]:
                lines.append(f"### Notice {n['notice']} ({n['notice_date']}), {len(n['names'])} apps")
                lines.append(f"[Notice PDF]({n['pdf_url']}) · read by: {n['method']}\n")
                lines += [f"{i}. {name}" for i, name in enumerate(n["names"], 1)]
                lines.append("")
        if status["problems"]:
            lines.append("## Problems: nothing was added for these\n")
            lines += [f"- {p}" for p in status["problems"]]
            lines.append("\nNothing is ever added when a check fails. Look at the notice yourself and add the rows by hand if needed (see README).")
        if not lines:
            lines.append("No new notices.")
        with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("\n".join(lines))

    # 1-2. find the notice PDFs
    try:
        pdfs = []
        for page in notice_pages(session, base):
            for u in pdf_links(session, page):
                if u not in pdfs:
                    pdfs.append(u)
    except RuntimeError as e:
        status["problems"].append(f"Could not reach the Bank of Ghana website: {e}")
        return finish()
    if not pdfs:
        status["problems"].append("Found no notice PDFs on the Bank of Ghana search page. The page layout may have changed.")
        return finish()

    # 3. self-check against the newest notice we already have
    if rows:
        newest = max(rows, key=lambda r: (r["notice_date"], r["notice"]))
        expected = [r["name"] for r in rows if r["notice"] == newest["notice"]]
        try:
            blob = fetch(session, newest["notice_url"], binary=True)
            got = parse_notice(blob, newest["notice_url"]) if blob else None
        except Exception as e:  # noqa: BLE001 - report any reading failure
            got, blob = {"names": [], "problems": [str(e)], "notice": None}, b""
        if not got or got["problems"] or got["notice"] != newest["notice"] or sorted(got["names"]) != sorted(expected):
            status["problems"].append(
                f"Self-check failed: re-reading Notice {newest['notice']} did not give the {len(expected)} names already in the list. "
                f"The Bank of Ghana may have changed its format, so nothing was added this time. Details: "
                + json.dumps({k: got.get(k) for k in ("notice", "names", "problems")} if got else "PDF not found"))
            return finish()

    # 4. read new PDFs
    new_rows, new_log = [], []
    known_by_number = {tuple(map(int, n.split("/")[-2:])) for n in known_notices if re.search(r"/\d{4}/\d+$", n)}
    for url in pdfs:
        if url in seen_urls:
            continue
        guess = number_from_filename(url)
        if guess and guess in known_by_number:
            new_log.append({"notice": f"BG/GOV/SEC/{guess[0]}/{guess[1]}", "notice_date": "", "pdf_url": url,
                            "apps_found": "already in the list (another copy of this notice)", "checked_on": today})
            continue
        try:
            blob = fetch(session, url, binary=True)
            if not blob:
                continue
            res = parse_notice(blob, url)
        except Exception as e:  # noqa: BLE001
            status["problems"].append(f"Could not read {url}: {e}")
            continue
        if res["problems"]:
            status["problems"].append(f"Notice at {url}: " + "; ".join(res["problems"]))
            continue
        if res["notice"] in known_notices:
            new_log.append({"notice": res["notice"], "notice_date": res["notice_date"], "pdf_url": url,
                            "apps_found": "already in the list (another copy of this notice)", "checked_on": today})
            continue
        known_notices.add(res["notice"])
        new_log.append({"notice": res["notice"], "notice_date": res["notice_date"], "pdf_url": url,
                        "apps_found": str(len(res["names"])), "checked_on": today})
        if res["names"]:
            new_rows += [{"name": n, "notice": res["notice"], "notice_date": res["notice_date"], "notice_url": url} for n in res["names"]]
            status["notices"].append({**res, "pdf_url": url})

    # 5. write files (oldest notice first, so the CSV stays in date order)
    new_rows.sort(key=lambda r: (r["notice_date"], r["notice"]))
    status["notices"].sort(key=lambda n: (n["notice_date"], n["notice"]))
    if new_log:
        write_csv(log_csv, LOG_FIELDS, log + new_log)
    if new_rows:
        write_csv(data_csv, CSV_FIELDS, rows + new_rows)
        subprocess.run([sys.executable, os.path.join(args.root, "tools", "embed_data.py")], check=True)
        status["status"] = "updated"
        status["new_apps"] = len(new_rows)
    return finish()


if __name__ == "__main__":
    main()
