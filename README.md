# Ananse Check

**Is this loan app licensed?** A free checker that compares a loan app's name against the Bank of Ghana's public notices.

This is a public awareness project, part of the Ananse Cash campaign. It is not a loan app. It gives no loans, and it collects no personal data.

## What it does

You type an app name and get one of three answers:

| Answer | Meaning |
| --- | --- |
| Not licensed | The Bank of Ghana has named this app in a notice on unlicensed digital credit providers |
| On the approved list | The app is on the Bank of Ghana's list of approved digital lending apps |
| Not on any list | Neither. Not being named does not make an app safe |

Close spellings are matched too, so "Sika Tapp" still finds "Sika Tap".

## Data

| File | Source |
| --- | --- |
| `data/unlicensed-loan-apps.csv` | Bank of Ghana notices BG/GOV/SEC/2026/25 (3 Aug 2026), /29 (8 Sep 2026), /36 (6 Oct 2026) and /40 (2 Nov 2026). Each row links to its notice PDF. |
| `data/approved-digital-lending-apps.csv` | [Bank of Ghana: Approved Digital Lending Applications](https://www.bog.gov.gh/supervision-regulation/all-institutions/digital-lending-applications/), checked 6 Nov 2026 |

Names are copied exactly as the Bank of Ghana prints them. When it prints the same app more than once, or with different spellings ("Hasty Credit" and "HastyCredit"), each notice keeps its own row.

### Adding a new notice

1. Open the notice PDF on [bog.gov.gh](https://www.bog.gov.gh/?s=unlicensed+digital+credit).
2. Add one row per app to `data/unlicensed-loan-apps.csv`: `name,notice,notice_date,notice_url`. Copy the name exactly, and don't put commas in it.
3. Commit the change. The page updates within a minute or two.

Only add apps that a regulator has named in writing. Never add an app because someone said it is bad.

### Automatic updates

`.github/workflows/update-bog-list.yml` runs `tools/update_from_bog.py` every morning at 06:23 Ghana time. It:

1. reads the Bank of Ghana search results for "unlicensed digital credit" and opens each notice PDF;
2. **self-checks** by re-reading the newest notice already in the list. If it doesn't get exactly the same names, it adds nothing and opens an issue, because the Bank may have changed its format;
3. reads any new notice: its number, its date and the numbered table of app names. A list is only added if the numbers run 1 to N with no gaps, every name is found in the PDF text, and two separate reading methods agree;
4. adds the new rows, logs every PDF in `data/processed-notices.csv`, refreshes the built-in copy, and updates `data/last-checked.json` (shown on the website).

| Mode | What happens with new names |
| --- | --- |
| `auto` (default) | Added straight to the website |
| `review` | A pull request for you to approve (set the repository variable `UPDATE_MODE` to `review`) |

If a check fails, nothing is added and an issue called "Ananse Check updater needs a look" opens. It only ever adds names the Bank published; it never removes any.

**One-time setup:** Settings > Actions > General > Workflow permissions: choose "Read and write permissions" and tick "Allow GitHub Actions to create and approve pull requests". Then go to the Actions tab, open "Update Bank of Ghana list" and click "Run workflow" to test it.

**To run it by hand:** `pip install -r tools/requirements.txt`, then `python3 tools/update_from_bog.py`.

### The built-in copy

`index.html` also carries a copy of both lists. The page only uses it when it can't read the CSV files, for example when it's opened straight from a phone or laptop. A note under the search box then says it is using the built-in copy.

The website always reads the CSV files first, so editing them on GitHub is enough. To refresh the built-in copy too, run this on a computer and commit `index.html`:

    python3 tools/embed_data.py

## Run it

- **Online:** GitHub Pages serves `index.html` from the main branch. It reads the latest CSV files.
- **Opened as a file:** it works, but it uses the built-in copy.
- **Local web server:** run `python3 -m http.server` in this folder and open http://localhost:8000.

## Change the words or add a language

All the text is in `index.html`. Twi, Ewe and Dagbani versions should be written and checked by native speakers.

## Licence

- Code: MIT.
- Campaign text: CC BY 4.0.
- The lists come from Bank of Ghana public notices; see each notice for its source.

This is a guide, not legal advice.

## Report harassment

- Cyber Security Authority: call or text **292**, or email report@csa.gov.gh
- Bank of Ghana, Fintech and Innovation Department: digitalcredit@bog.gov.gh
