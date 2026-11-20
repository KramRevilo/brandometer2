# Brandometer2

N.B. This is not an officially supported Google product.

Brandometer2 builds **brand-lift** and **brand-track** display surveys and hosts them on Google Cloud. Marketers create a survey in the app, download HTML5 zips, traffic them in Campaign Manager 360 / DV360, and read results in the app (or in BigQuery).

It is a fork of [Google Brandometer](https://github.com/google/brandometer) (Apache-2.0). The in-app product name is `APP_BRAND_NAME` (default **Brandometer**). Developer detail lives in [DEVELOPERS.md](DEVELOPERS.md).

## What’s new vs upstream

Upstream Brandometer was a Python 3.7 App Engine app with Basic Auth, a 300×250 creative, and spreadsheet reporting. Brandometer2 adds:

* A Bootstrap 5 survey editor (multi-size creatives, 2–8 answers, theme presets, wrapping text, disclosure badge, zip version history)
* Homepage archive/copy, status chips, and client/agency/year/size filters
* In-app reporting (Brand Lift with Wilson CIs and a z-test; Brand Track distributions) and streamed CSV, with one row per BomID
* Google Sign-In, an Admin page, and **admin / editor / viewer** roles (not IAP, not shared passwords)
* HMAC-signed pixel links, daily-rotating IP hashes, CSRF on mutating actions, and a 409 when two people save the same survey
* Secret Manager, least-privilege service accounts, App Engine **python312**, a gen2 Cloud Function receiver, and self-hosted front-end libraries
* A **Bv2** favicon and a Google-account avatar in the navbar

## Features

### Survey editor

Create or edit a survey in the browser (Bootstrap 5.3.3, Alpine.js, live iframe preview).

* **Sizes:** 300×250 (default for old surveys), 160×600, 300×600, 336×280, 970×250. You can select more than one. 970×250 lays answers in a wrapping grid. Not 728×90 / 320×50 / 320×100.
* **Answers:** 2–5 on 300×250 / 336×280 / 970×250; up to 8 (a–h) when **every** selected size is 160×600 or 300×600. Empty rows are skipped. Answer text wraps.
* **Themes:** grouped presets (Classic, Loud solids, Complementary, Patterns). Classic green is the default. Pickers write CSS variables; free-form CSS stays under Advanced.
* **Disclosure badge:** bottom-left **B** / **B2** / **Ad** / **Dentsu** pill on the creative (not an official Dentsu logo). Optional tooltip (max 120 characters).
* **Identity:** optional display name, client, agency, campaign ID, and placement ID. Display name is the homepage label; the survey name still drives zip filenames. Campaign/placement IDs are stored for a future cost join and are **not** used in reporting yet.
* **Versions:** each creative ZIP download stores an immutable snapshot. The edit page can re-download an old version. Editing the live survey does not change past snapshots.

Download from the homepage is an **outer ZIP** of one HTML5 inner zip per size (Brand Lift also splits Control and Expose). Unzip the outer file and upload each **inner** zip to CM360. Do not upload the outer zip as a creative. Inner zips contain only `index.html`.

![Survey creation](survey_creation_screenshot.png)

### Homepage

* List with search plus **client / agency / year / size** filters (kept on pagination and Show archived). Page size 50.
* **Archive / unarchive** and **copy** (copy opens the new survey in the editor).
* Status chips: **Active** (≤ 3 days since last response), **Stale** (≤ 7 days), **Timed out** (after 7).
* View Survey (size switcher when there is more than one size), stats, ZIP download (editors/admins), and CSV download.
* Count / last-response / status cells load after the table (`/index/stats-partial`); the list itself does not wait on BigQuery.

### Reporting and CSV

The stats button works for **Brand Lift and Brand Track**.

* Counts, reports, and CSV treat each **BomID as one respondent** (latest, most complete `Response`). Surveys that submit after each question show fewer people than raw BigQuery row counts.
* Brand Lift: control vs exposed, Wilson 95% CIs, two-proportion z-test, warning when an arm has fewer than 30 respondents. Segments come from the stored `seg` value (`control` / `expos` in the string).
* Brand Track: answer distributions and responses per day.
* Two CSVs: responses, and responses with question text. Both stream; they are not built as one in-memory string.

Preview **does not** post to BigQuery. To generate test rows, curl the receiver (see DEVELOPERS.md).

![Download responses](download_responses_screenshot.png)

### Trafficking (CM360 / DV360)

Still the way live studies run:

1. Match each CM/DV360 placement to a selected survey size.
2. Brand Lift: Control and Expose audience segments, control creative on Control, expose survey on Expose, plus default / pre-survey / master ads as in a normal BOM cut.
3. Brand Track: one creative (no control/expose split).
4. Default ads should be brand-neutral (no brand names or logos).
5. Assign CM creatives to DV360 line items; each BOM cut is its own placement / line item.

## Security and access

Production is **Google Sign-In** (OIDC). Identity-Aware Proxy is not used. Shared Basic Auth is retired.

* **Admin** — Admin page plus everything editors can do.
* **Editor** — create, edit, copy, archive, delete, download creative ZIPs. No Admin page.
* **Viewer** — list, filters, preview, reports, and CSV. Cannot change surveys, download ZIPs, or open Admin. Mutating routes and ZIP downloads return a friendly **403**, not only hidden buttons.
* **Admin page:** allowlist users (role per email), allowed domains (default role per domain), audit log. Role changes are audited.
* Verified **@google.com** accounts can always sign in as **editor** unless you list them with another role.
* **Bootstrap admin** (`BOOTSTRAP_ADMIN_EMAIL`) is always admin on first sign-in.
* There is **no tenancy**: every allowed user sees every survey.
* Navbar: Google profile photo when the account has one, otherwise an initial; the dropdown shows email, role, and Sign out.

Also in production:

* CSRF on POST actions (copy / archive / delete / save). Stats polling is GET.
* Saving a survey someone else already saved returns **409** (“Someone else saved this survey, reload”).
* Live creatives post through HMAC-signed pixel links (`token=`). Preview is unsigned and does not post. Rotating the receiver HMAC secret invalidates every live zip until you re-download.
* Receiver rate limit: 30 requests / minute / (hashed IP + survey id), **per function instance**.
* Client IP is **not** stored. `RandomTimeStamp` is a daily HMAC of the IP (same IP, same UTC day → same hash; hashes do not link across days).
* Secrets live in Secret Manager. App Engine loads them at startup (standard `app.yaml` cannot inject secrets as env vars).
* App Engine and the receiver use least-privilege service accounts (`roles/editor` is removed from the App Engine SA).
* Front-end libraries are self-hosted under `creative/app/static/vendor/` (Bootstrap 5.3.3, Bootstrap Icons 1.11.3, htmx 1.9.12, Alpine.js 3.14.3, Chart.js 4.4.6).

## Architecture

| Piece | What it is |
| --- | --- |
| App | App Engine **standard python312**, Flask 3, instance class F4, `automatic_scaling.max_instances` (deploy env `MAX_INSTANCES`, default **5**) |
| Surveys | Firestore Native `(default)` — survey docs, versions, allowlist, audit log |
| Responses | BigQuery dataset `responses`, table `responses` (`$PROJECT_ID.responses.responses`) |
| Pixel | Gen2 Cloud Function `receiver` (python312, HTTP, unauthenticated, dedicated SA, `--max-instances=20`) |
| UI assets | `/static` on App Engine; `/favicon.ico` is a static file |

**Secrets** (created by `./deploy`; HMAC / `SECRET_KEY` are not rotated on later runs):

* `brandometer-oauth-client-id` / `brandometer-oauth-client-secret` — Google OAuth Web client
* `brandometer-secret-key` — Flask session signing
* `brandometer-receiver-hmac` — per-survey creative token
* `brandometer-ip-hmac` — daily IP-hash master

App Engine env vars are non-secret only: `PROJECT_ID`, `RECEIVER_URL`, `TABLE_ID`, `GTAG_ID`, `BOOTSTRAP_ADMIN_EMAIL`.

## Setup and deploy

Prerequisites: [Google Cloud SDK](https://cloud.google.com/sdk/) (`gcloud` and `bq`), Python 3.12, pip, a GCP project with billing enabled.

### OAuth client

1. In the Cloud Console, open the project.
2. **APIs & Services → OAuth consent screen.** Use **Internal** for a Google Workspace project; otherwise **External** and add yourself as a test user while the app is in Testing. App name `Brandometer`. Scopes: `openid`, userinfo email, userinfo profile. Authorized domain: `appspot.com`.
3. **Credentials → Create credentials → OAuth client ID → Web application.**

Authorized JavaScript origins (replace `PROJECT_ID`; us-central App Engine also uses `uc.r.appspot.com`):

* `https://PROJECT_ID.appspot.com`
* `https://PROJECT_ID.uc.r.appspot.com`
* `http://127.0.0.1:8080`
* `http://localhost:8080`

Authorized redirect URIs (exact):

* `https://PROJECT_ID.appspot.com/auth/callback`
* `https://PROJECT_ID.uc.r.appspot.com/auth/callback`
* `http://127.0.0.1:8080/auth/callback`
* `http://localhost:8080/auth/callback`

Copy the client ID and secret. You will paste them into `./deploy` (or set env vars). Do not commit them.

### Deploy

```shell
gcloud auth login
gcloud config set project "$PROJECT_ID"
./deploy "$PROJECT_ID" us-central1 us-central
```

Arguments are **project**, **Functions / BigQuery / Firestore location** (`gcloud functions regions list`), **App Engine region** (`gcloud app regions list`). Example: `us-central1` then `us-central`.

The script prompts for OAuth client id, OAuth client secret, and bootstrap admin email. **Enter keeps an existing secret.** After a write it prints `stored N chars` and never echoes the value.

App Engine only (receiver already up, or you are rotating the OAuth client secret):

```shell
./deploy "$PROJECT_ID" us-central1 us-central --app-only
```

Non-interactive (omit an env var to keep the existing secret):

```shell
OAUTH_CLIENT_ID='....apps.googleusercontent.com' \
OAUTH_CLIENT_SECRET='...' \
BOOTSTRAP_ADMIN_EMAIL='you@example.com' \
  ./deploy "$PROJECT_ID" us-central1 us-central --app-only --skip-oauth-prompts
```

`MAX_INSTANCES` (default 5) caps App Engine instances.

**HMAC secrets and `SECRET_KEY` are created once and never rotated by `./deploy`.** Rotating `brandometer-receiver-hmac` would invalidate every live creative zip. Rotating `SECRET_KEY` would sign everyone out.

**To rotate the OAuth client secret:** create a new secret on the OAuth client (or a new Web client), then rerun `./deploy … --app-only` and paste the new id/secret when prompted (or set `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET`). Enter / `--skip-oauth-prompts` keeps the old values.

If a new project is still provisioning, wait a few minutes and rerun. `--app-only` is enough for App Engine code, yaml, favicon, and most IAM/dataset fixes; redeploy the receiver as well when its Python or HMAC wiring changes (see DEVELOPERS.md).

## Local development

From the repo root:

```shell
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r creative/app/requirements.txt
export PROJECT_ID="your-gcp-project-id"
export TABLE_ID="$PROJECT_ID.responses.responses"
export DISABLE_BASIC_AUTH=1
cd creative/app
flask --app main run --port 8080 --debug
```

Open http://127.0.0.1:8080. `python main.py` also works (`PORT` defaults to 8080). Cloud Shell Web Preview only proxies **8080**.

`DISABLE_BASIC_AUTH=1` is a local-dev bypass (full admin, `local-dev` in the navbar). The app **refuses to start** with that flag when `GAE_ENV` is set. Never put it in `app.yaml` or `./deploy`.

Listing and saving surveys need Application Default Credentials (`gcloud auth application-default login`). Preview works without the receiver. Signed zip tokens need `RECEIVER_HMAC_SECRET`. Optional Google Sign-In locally: put `http://127.0.0.1:8080/auth/callback` on the OAuth client.

### Tests

GCP is not required:

```shell
pip install -r creative/app/requirements.txt -r requirements-dev.txt
cd creative/app
PYTHONPATH=. python -m pytest
```

## Querying results in BigQuery

Table: `` `$PROJECT_ID.responses.responses` `` (dataset `responses`, table `responses`). Required columns:

| Column | Type | Meaning |
| --- | --- | --- |
| `CreatedAt` | DATETIME | Insert time |
| `Type` | STRING | Usually `survey` |
| `ID` | STRING | Firestore survey id |
| `Segmentation` | STRING | Stored `seg` (Brand Lift control/expose; often empty for Track) |
| `Response` | STRING | Tokenised answers, e.g. `1:A\|2:B` |
| `Visual` | STRING | Unused placeholder (schema is REQUIRED) |
| `CreativeSize` | STRING | e.g. `300x250` |
| `RandomTimeStamp` | STRING | Daily HMAC of the client IP (not the IP, not unsalted SHA-256) |
| `BomID` | STRING | Respondent id from the creative |

The app consolidates by BomID. A raw count of rows can be higher than homepage / report / CSV counts.

```sql
SELECT
  ID,
  BomID,
  Segmentation,
  Response,
  CreativeSize,
  CreatedAt
FROM `PROJECT_ID.responses.responses`
WHERE ID = 'SURVEY_ID'
ORDER BY CreatedAt;
```

Replace `PROJECT_ID` and `SURVEY_ID`. For production tables that are partitioned on `CreatedAt`, add a date filter.

## Roadmap (not built)

Phase **7c / 7d** and related backlog — do not treat these as shipped:

* Durable respondent ID (beyond BomID / daily IP hash)
* Ad-server macros and a trafficking tag sheet
* BigQuery authorized views and Looker
* Reporting breakouts (beyond current Lift / Track views)
* HTML5 spec QA automation
* Bulk CSV survey import
* Stats-method corrections beyond current Wilson / z-test
* CM360 / DV360 export (cost/impressions dashboard; campaign/placement ID fields are placeholders only)
* Shared stats cache (today each App Engine instance caches for 90 seconds)

Also not built: free-form write-in answers, in-stream video/VAST creatives, and a cost/impressions join. See **Assessments (not built)** in [DEVELOPERS.md](DEVELOPERS.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).

This repository started as a copy of [google/brandometer](https://github.com/google/brandometer). Google is not a party to this fork and does not support it. Keep the Apache notices on files that still carry them.
