"""Copy the CSV lists into index.html as a built-in backup.

The website reads data/*.csv first. The built-in copy is only used when the
page is opened as a file or the CSVs cannot load. Run this after you change a
CSV:  python3 tools/embed_data.py
"""
import datetime, json, pathlib, re
root = pathlib.Path(__file__).resolve().parent.parent
data = {
    "built": datetime.date.today().isoformat(),
    "unlicensed": (root / "data/unlicensed-loan-apps.csv").read_text(encoding="utf-8"),
    "approved": (root / "data/approved-digital-lending-apps.csv").read_text(encoding="utf-8"),
}
html_path = root / "index.html"
html = html_path.read_text(encoding="utf-8")
block = "const EMBEDDED = " + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";"
new, n = re.subn(r"(// ---- EMBEDDED DATA[^\n]*\n).*?(\n// ---- END EMBEDDED DATA ----)", lambda m: m.group(1) + block + m.group(2), html, flags=re.S)
if n != 1:
    raise SystemExit("Could not find the EMBEDDED DATA markers in index.html")
html_path.write_text(new, encoding="utf-8")
print("Built-in copy updated:", data["unlicensed"].count("\n") - 1, "unlicensed rows,", data["approved"].count("\n") - 1, "approved rows")
