# TriB

Arabic/English accounting and ERP for Egypt and the Middle East, by Heliolink. Multi-company SaaS: every customer
(Scientific Gate is the first) gets its own company with its own users, chart of accounts and settings.

Built with Django 5.2, PostgreSQL (Neon) or SQLite, and Chart.js. The interface follows the QuickBooks layout:
icon rail, top bar with search, greeting, business feed, create actions and "Business at a glance" blocks.

## What Release 1 does

- **Arabic and English.** One click switches the whole interface, including right-to-left layout. Every name
  (accounts, banks, branches) is stored in both languages. Voucher printouts are bilingual with the amount in
  words in both languages (تفقيط).
- **Companies, branches and users.** Each user can belong to several companies. Branch restrictions per user.
- **Authority matrix.** Roles hold permissions per module and action (view, create, edit, approve, post, void,
  export), plus approval limits per document type. Five starter roles: Administrator, Finance manager, Accountant,
  Cashier, Auditor.
- **Electronic approvals.** Rules by document type and amount, up to three levels. The creator can't approve
  their own document, nobody can approve two levels, and approval limits are enforced. Each decision is
  e-signed (HMAC-SHA256 over the document's contents), so any later change to the document shows as "Signature
  does not match".
- **Vouchers.** Receipt (سند قبض), payment (سند صرف) and journal (قيد يومية) vouchers, paid by cash, bank transfer
  or cheque. They go draft → submitted → approved → posted, with gap-free numbering per year (RV/PV/JV-2026-00001).
- **Banks and cash.** Egyptian and Gulf banks are listed (including FAB/FABMISR) and companies can add any bank.
  Bank accounts can be in any currency, and each one automatically gets its own account in the chart.
- **Post-dated cheques.** Received: in the safe → under collection → cleared, or bounced (the amount goes back to
  the customer). Issued: issued → cleared or cancelled. Every step posts the correct journal entry.
- **Ledger.** Starter Egyptian trading chart of accounts (bilingual), cost centres, lock date, foreign-currency
  amounts kept next to base-currency amounts. Entries are never edited, only reversed. On PostgreSQL a database
  trigger refuses to commit any entry whose debits and credits differ.
- **Reports.** Trial balance (with CSV export that opens correctly in Excel), account statement, profit and loss,
  balance sheet.
- **Audit log.** Every change, approval and sign-in is recorded with user and IP address.
- **Add-ons switch.** Egypt tax & ETA, Trading & imports, GCC pack, Payroll and Planning can be switched on or off
  per company in Settings (the modules themselves arrive in later releases).

Coming next: sales and supplier invoices, VAT and withholding tax, ETA e-invoicing (Release 1b), then inventory,
imports and landed cost (Release 2), planning and cash forecast (Release 3), GCC pack (Release 4).

## Run it on your PC

You need Python 3.12.

```powershell
python -m venv "$env:LOCALAPPDATA\trib-venv"
& "$env:LOCALAPPDATA\trib-venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
copy .env.example .env
& "$env:LOCALAPPDATA\trib-venv\Scripts\python.exe" manage.py build_locale
& "$env:LOCALAPPDATA\trib-venv\Scripts\python.exe" manage.py migrate
& "$env:LOCALAPPDATA\trib-venv\Scripts\python.exe" manage.py seed_reference
& "$env:LOCALAPPDATA\trib-venv\Scripts\python.exe" manage.py runserver 8077
```

Open http://127.0.0.1:8077. With an empty database you are sent to **Set up your company**, which creates the
company, its chart of accounts, roles, cash box and approval rules, and makes you the owner.

The virtual environment lives outside OneDrive so it doesn't sync thousands of files. Without a `DATABASE_URL`
the app uses `db.sqlite3` in this folder.

**Demo data.** Add `TRIB_DEMO_PASSWORD=<10+ characters>` to your `.env`, then run `manage.py seed_demo`. It
creates "Scientific Gate (demo)" with three users (demo-owner@trib.local, demo-finance@trib.local,
demo-cashier@trib.local), four bank accounts, a year of vouchers, items waiting for approval and post-dated
cheques. It only runs when `DEBUG=1`.

**Tests:** `& "$env:LOCALAPPDATA\trib-venv\Scripts\python.exe" -m pytest`

## Deploy: GitHub + Neon + Render

### 1. Put the code on GitHub

**Without Git (upload in the browser)**

1. On github.com, create a new **private** repository called `trib`. Don't add a README.
2. On the empty repository page, click **uploading an existing file**.
3. Unzip `trib-github.zip`, open the `trib` folder inside it, select everything (including `.github`,
   `.gitignore` and `.python-version`) and drag it onto the upload page. Then click **Commit changes**.
4. Check that `config`, `core`, `templates`, `render.yaml` and `manage.py` sit at the top level of the repository.

**With Git** (`winget install --id Git.Git -e`, then reopen the terminal):

```powershell
git init -b main
git add .
git commit -m "TriB release 1"
git remote add origin https://github.com/<your-username>/trib.git
git push -u origin main
```

### 2. Create the database on Neon

1. At https://console.neon.tech create a project called `trib` in **AWS Europe Central (Frankfurt)**, next to
   the Render server.
2. Click **Connect** and copy the connection string (pooled). It looks like
   `postgresql://user:password@ep-xxxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require`.
   Keep it private.

### 3. Deploy on Render

1. At https://dashboard.render.com click **New → Blueprint**, choose the `trib` repository and **Connect**.
2. When asked for `DATABASE_URL`, paste the Neon connection string. `SECRET_KEY` is generated for you.
3. Click **Apply**. The build installs packages, builds the Arabic catalogue, collects static files, creates the
   tables and loads currencies and banks.
4. Open the site (e.g. `https://trib.onrender.com`). You'll see **Set up your company**: create Scientific Gate
   and your owner account. This page closes itself once a company exists.
5. In **Users & roles**, add Scientific Gate's finance manager and cashier.

Every `git push` to `main` redeploys. GitHub runs the tests against PostgreSQL on every push
(`.github/workflows/tests.yml`).

**Second and later customers:** sign in to `/admin/` as a platform superuser (create one locally with
`manage.py createsuperuser` against the Neon database) to see all companies. A self-service sign-up for new
customers is planned with subscription billing.

### Free plans

- Render's free web service sleeps after 15 minutes without visitors, and the first request after that takes
  about a minute. Use the Starter plan (about $7 a month) for Scientific Gate's live use.
- Neon's free plan pauses an idle database and wakes it in a second or two. For live accounting data, use a paid
  Neon plan so you get point-in-time restore.

## Project layout

```
config/      settings, URLs, Arabic number formats
core/        companies, currencies, exchange rates, numbering, audit log, amounts in words, setup, settings
users/       sign-in, users, roles, the authority matrix and approval limits
ledger/      chart of accounts, cost centres, journal entries, posting rules (services.py)
banking/     banks, bank accounts and cash boxes, post-dated cheques
approvals/   approval rules, routing, e-signatures
vouchers/    receipt, payment and journal vouchers, printing
reports/     trial balance, statement, profit and loss, balance sheet
dashboard/   the QuickBooks-style home page
templates/   shared layout (rail, top bar, Create menu)
static/      trib.css, trib.js, dashboard.js, logo
tests/       ledger, banking, vouchers and approvals, amounts in words, every page in both languages
```

All money is stored as exact decimals (`NUMERIC(19,2)`), never floating point. Arabic text lives in
`core/translations_ar.py`; `tests/test_i18n.py` fails if any interface string is missing its Arabic version.
