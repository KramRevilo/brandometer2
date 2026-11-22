# Brandometer2 developer guide

Brandometer2 is a Flask + Google Cloud app (App Engine, Firestore, BigQuery, Cloud Functions) for building brand-lift / brand-track survey creatives. It started as a fork of Google Brandometer (Apache-2.0). The in-app product name is `APP_BRAND_NAME` (default **Brandometer2**). Use only the Brandometer2 name in docs and UI; do not reference the previous fork's name. Theme blocks in `custom_css` use `BV2_THEME_START` / `BV2_THEME_END` (and `BV2_SIZE_*` / `BV2_LAYOUT_*` overlays) with `--bv2-*` CSS variables (`--bv2-bg`, `--bv2-accent`, …). Custom CSS written for older names is not applied — this tree is for new survey deployments.

**Docs stay in the same commit.** Every change must update `README.md` in that commit. Update this file too when the change is operator- or developer-facing (deploy, IAM, local run, tests, secrets, architecture). See `AGENTS.md`.

# Prerequisites

* [Google Cloud SDK](https://cloud.google.com/sdk/) (`gcloud` and `bq`)
* Python 3.12
* pip
* A GCP project with billing enabled

# One-time GCP setup

If you already ran `./deploy`, skip to [Run locally](#run-locally). Otherwise, with your project ID (called `$PROJECT_ID` below):

```shell
gcloud auth login
gcloud auth application-default login
gcloud config set project "$PROJECT_ID"
gcloud auth application-default set-quota-project "$PROJECT_ID"
```

Either create everything with the deploy script (App Engine, Firestore, BigQuery dataset, receiver function, and a generated App Engine yaml):

```shell
./deploy "$PROJECT_ID" us-central1 us-central
```

App Engine only (receiver already deployed; rotate OAuth / yaml without touching the function):

```shell
./deploy "$PROJECT_ID" us-central1 us-central --app-only
```

Non-interactive OAuth (keeps existing Secret Manager values when an env var is omitted):

```shell
OAUTH_CLIENT_ID='....apps.googleusercontent.com' \
OAUTH_CLIENT_SECRET='...' \
BOOTSTRAP_ADMIN_EMAIL='you@google.com' \
  ./deploy "$PROJECT_ID" us-central1 us-central --app-only --skip-oauth-prompts
```

`us-central1` is the Functions / BigQuery / Firestore location; `us-central` is the App Engine region. List others with `gcloud functions regions list` and `gcloud app regions list`.

Or create the pieces yourself:

```shell
gcloud services enable \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  appengine.googleapis.com \
  cloudfunctions.googleapis.com \
  bigquery.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com

# Firestore Native (default) — do this *before* `gcloud app create`, which
# otherwise provisions (default) in Datastore mode.
gcloud firestore databases create \
  --location=us-central1 \
  --type=firestore-native \
  --database='(default)'

# BigQuery dataset + responses table (same schema as the receiver).
# New tables are partitioned by CreatedAt and clustered by ID. Skip this
# `bq mk --table` if the table already exists; do not migrate an existing table.
bq --location=us-central1 mk --dataset --description "Main response data set for Brandometer" "$PROJECT_ID:responses"
bq mk --table \
  --schema receiver/responses.schema.json \
  --time_partitioning_field CreatedAt \
  --time_partitioning_type DAY \
  --clustering_fields ID \
  --description "Survey response rows for Brandometer" \
  "$PROJECT_ID:responses.responses"

# Optional: deploy the HTTP receiver so survey creatives can post answers.
# Create a dedicated SA first (./deploy does this). Do not reuse the App Engine SA.
gcloud iam service-accounts create brandometer-receiver \
  --display-name="Brandometer response receiver"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:brandometer-receiver@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.viewer"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:brandometer-receiver@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"
# Dataset IAM: `bq add-iam-policy-binding` needs allowlisting. Use access[].
# PYTHONWARNINGS=ignore --quiet: bq can print RequestsDependencyWarning on stdout.
PYTHONWARNINGS=ignore bq --format=prettyjson --quiet show --dataset \
  "$PROJECT_ID:responses" > /tmp/responses-ds.json 2>/dev/null
# merge {role: WRITER, userByEmail: SA}, then:
PYTHONWARNINGS=ignore bq --quiet update --source /tmp/responses-ds.json \
  "$PROJECT_ID:responses"
# HMAC secrets: create once (./deploy does this). Then:
gcloud functions deploy receiver \
  --gen2 \
  --trigger-http \
  --allow-unauthenticated \
  --runtime python312 \
  --entry-point=receiver \
  --region=us-central1 \
  --source=receiver \
  --service-account="brandometer-receiver@$PROJECT_ID.iam.gserviceaccount.com" \
  --max-instances=20 \
  --timeout=60s \
  --memory=256MB \
  --set-env-vars TABLE_ID="$PROJECT_ID.responses.responses" \
  --set-secrets RECEIVER_HMAC_SECRET=brandometer-receiver-hmac:latest,IP_HMAC_SECRET=brandometer-ip-hmac:latest
```

**App Engine service account IAM.** `./deploy` grants the default App Engine SA (`$PROJECT_ID@appspot.gserviceaccount.com`) least privilege and **removes** `roles/editor` if it was bound. The same grants run on `--app-only`.

Runtime:

* `roles/datastore.user` (Firestore reads/writes)
* `roles/bigquery.jobUser` (run queries; **kept** at project level)
* dataset `WRITER` / `roles/bigquery.dataEditor` on `responses` via `bq show` + `bq update --source` (not a project-level `roles/bigquery.dataEditor`; that binding is **removed** once dataset IAM is verified)
* `roles/logging.logWriter`
* `roles/secretmanager.secretAccessor` (plus per-secret accessor bindings)

`gcloud app deploy` Cloud Build (the default GAE SA is the build identity after Editor is removed):

* `roles/cloudbuild.builds.builder` (project)
* `roles/artifactregistry.createOnPushWriter` (project; first push can create the `gcr.io` Artifact Registry repo)
* `roles/storage.objectAdmin` on `gs://staging.$PROJECT_ID.appspot.com` and `gs://$PROJECT_ID.appspot.com` if those buckets exist (skipped if not). This is the tight form of the [App Engine deploy troubleshooting](https://cloud.google.com/appengine/docs/standard/troubleshooter/deployment) “invalid bucket staging.….appspot.com; service account … does not have access” fix (that page suggests project-level `roles/storage.admin`; we scope objectAdmin to the App Engine buckets instead).

`--condition=None` on every IAM binding. If a previous run removed Editor before these build roles existed, rerun `./deploy "$PROJECT_ID" us-central1 us-central --app-only`.

The receiver SA gets `roles/datastore.viewer` (survey exists / not archived), dataset `WRITER` on `responses`, and `roles/logging.logWriter`. It does **not** create BigQuery tables at runtime. Dataset IAM writes `bq --format=prettyjson --quiet show --dataset` to a temp file (`PYTHONWARNINGS=ignore`, stderr discarded), strips anything before the first `{`, merges `{role: WRITER, userByEmail: SA}`, then `bq update --source`. After a verified dataset grant, project-level `roles/bigquery.dataEditor` is removed from that SA. App Engine keeps project `roles/bigquery.jobUser`.

**Secrets.** Shared Basic Auth is retired in production. `./deploy` stores:

* `brandometer-oauth-client-id` / `brandometer-oauth-client-secret` — Google OAuth Web client (prompted; Enter keeps an existing secret; after a write the script prints `stored N chars` and never echoes the value)
* `brandometer-secret-key` — Flask session signing (created once; not rotated on redeploy)
* `brandometer-receiver-hmac` — per-survey creative token HMAC (created once; rotating it invalidates live zips)
* `brandometer-ip-hmac` — daily IP-hash master (created once)

`app.yaml.template` is App Engine **standard** python312: `automatic_scaling.max_instances` (deploy env `MAX_INSTANCES`, default **5**) and only non-secret `env_variables` (`PROJECT_ID`, `RECEIVER_URL`, `TABLE_ID`, `GTAG_ID`, `BOOTSTRAP_ADMIN_EMAIL`). Standard `app.yaml` does **not** support `secret_environment_variables`. The App Engine app loads OAuth id/secret, `SECRET_KEY`, and `RECEIVER_HMAC_SECRET` from Secret Manager at startup (module-level cache, App Engine SA `secretAccessor`) and refuses to start if a required secret is missing. The receiver still gets HMAC secrets via `--set-secrets`. Local runs still use env vars. Do **not** use Identity-Aware Proxy for this app.

**Content-Security-Policy.** `app_security.install_security_headers` sets an **enforced** `Content-Security-Policy` on every Flask response (`default-src 'self'`). `frame-ancestors 'self'` lets the homepage modal iframe `/survey/preview/<id>?embed=1` (same origin only; not `'none'`). Google account avatars are `img-src https://*.googleusercontent.com`. Google Sign-In may navigate to `https://accounts.google.com` (`form-action` / `connect-src` also allow `oauth2.googleapis.com` and `www.googleapis.com`). Scripts and styles stay `'unsafe-inline'` because the editor, Chart.js bootstrap, and creative HTML (preview + iframe `srcdoc`) are inline; Alpine needs `'unsafe-eval'`. HTML5 zip downloads are attachments — once trafficked they are not under this header. If `GTAG_ID` is set, Tag Manager / analytics origins are added. `CSP_REPORT_ONLY=1` emits `Content-Security-Policy-Report-Only` instead (local debugging). Redeploy App Engine after this change (`--app-only`).

**Re-running `./deploy`.** Safe end to end, or App Engine only with `--app-only`. Firestore Native, the `responses` dataset, the `responses.responses` table, the `brandometer_reporting` dataset, and generated secrets (`brandometer-secret-key`, `brandometer-receiver-hmac`, `brandometer-ip-hmac`) are created only if missing — existing datasets/tables are not dropped or recreated. `ensure_respondent_columns` and `ensure_reporting_dataset` run on every deploy (including `--app-only`): `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for `RespondentID` / `RespondentIDSource` / trafficking IDs, then `CREATE OR REPLACE VIEW` for `deduped_responses` and `survey_summaries`. (`bq mk --dataset --force` never dropped a dataset; it only ignored ALREADY_EXISTS, but it still printed “successfully created”, which looked like a recreate. The script now skips with `already exists (not modified)`.) HMAC / `SECRET_KEY` values are never rotated on a later run. OAuth client id/secret: paste to rotate, or press Enter / pass `--skip-oauth-prompts` to keep existing; `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, and `BOOTSTRAP_ADMIN_EMAIL` skip the prompts when set. After creating `brandometer-receiver`, the script waits until `gcloud iam service-accounts describe` succeeds, then retries **transient** IAM errors only (SA “does not exist” / NOT_FOUND / INVALID_ARGUMENT, 409 concurrent policy). Usage errors (`Invalid choice`, `PERMISSION_DENIED`) fail immediately. Dataset IAM uses `bq --quiet show --dataset` to a file + `bq update --source` (not `gcloud bigquery`, which Cloud Shell gcloud does not have, and not `bq add-iam-policy-binding`, which requires allowlisting). Python warnings on stdout are ignored; JSON is parsed from the first `{`. A success line confirms each SA’s access entry. Verified dataset grants drop the project-level `roles/bigquery.dataEditor` fallback from a previous run. Dataset IAM for **both** the receiver SA and the App Engine SA runs on `--app-only`. `--condition=None` avoids the conditional-binding prompt. The same wait/retry applies to the App Engine default SA. If a previous run died on IAM lag, the old `gcloud bigquery` command, or `secret_environment_variables`, run `./deploy "$PROJECT_ID" us-central1 us-central --app-only`.

The App Engine service is only required for hosting, not for running Flask on your laptop.

# Run locally

From the repo root, on Mac or Linux:

```shell
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r creative/app/requirements.txt
```

Export credentials and config (the homepage talks to Firestore + BigQuery). Production uses Google Sign-In. Locally you can either configure OAuth or set `DISABLE_BASIC_AUTH=1` (refused when `GAE_ENV` is set):

```shell
export PROJECT_ID="your-gcp-project-id"
export TABLE_ID="$PROJECT_ID.responses.responses"
# Local-dev bypass (full admin). Never set this on App Engine / ./deploy.
export DISABLE_BASIC_AUTH=1
# Optional. A dev default is used if unset; set a real value before any shared deploy.
# export SECRET_KEY="replace-me"
# Optional until the receiver function exists. Preview still works without it.
export RECEIVER_URL="$(gcloud functions describe receiver --gen2 --region=us-central1 --format='value(serviceConfig.uri)')"
# Required to stamp signed tokens into downloaded zips. Preview stays unsigned.
# export RECEIVER_HMAC_SECRET="$(gcloud secrets versions access latest --secret=brandometer-receiver-hmac)"
# Optional Google Sign-In locally (http://127.0.0.1:8080/auth/callback must be on the OAuth client).
# AUTHLIB_INSECURE_TRANSPORT is set automatically off App Engine so http:// redirects work.
# export GOOGLE_OAUTH_CLIENT_ID="....apps.googleusercontent.com"
# export GOOGLE_OAUTH_CLIENT_SECRET="..."
# export BOOTSTRAP_ADMIN_EMAIL="you@google.com"
# Optional. Google tag (gtag.js) ID for creatives. Unset or empty skips the loader
# (there is no default Ads ID). Example: export GTAG_ID="AW-123456789"
# export GTAG_ID=""
# Optional. Homepage BQ stats cache TTL in seconds (default 90). 0 disables.
# export STATS_CACHE_SECONDS=90
# Optional. Shared Firestore L2 for homepage counts (default on). 0 keeps
# the in-process map only.
# export STATS_SHARED_CACHE=1
# Optional. CreatedAt partition window for homepage counts (default 400 days). 0 disables.
# export STATS_LOOKBACK_DAYS=400
```

If `gcloud functions describe` fails because the function is not deployed yet, omit `RECEIVER_URL` or set it later.

Start the app from `creative/app` so Flask finds the templates. Cloud Shell Web Preview only proxies port **8080**, so local and Shell both use that:

```shell
cd creative/app
flask --app main run --port 8080 --debug
```

`python main.py` also works: it reads `PORT` (default 8080).

Open http://127.0.0.1:8080. With `DISABLE_BASIC_AUTH=1` you are a local admin (`local-dev` in the navbar). With OAuth configured, use **Sign in with Google**.

The app imports without GCP. Listing surveys, saving surveys, and downloading responses need Application Default Credentials against the project above (`gcloud auth application-default login`).

# Google Cloud Shell

Cloud Shell **Web Preview** sits in front of Flask with its own login, and it is stuck on port **8080**. Google Sign-In needs the preview origin on the OAuth client, and that host **rotates per session**, so the practical Shell path is the local-dev bypass:

```shell
export DISABLE_BASIC_AUTH=1
cd creative/app
flask --app main run --port 8080 --debug
```

Then use Web Preview → port 8080. To try OAuth in Shell instead, open Web Preview first, copy the origin, add `https://<preview-host>/auth/callback` on the OAuth client (and the origin as a JavaScript origin), then unset `DISABLE_BASIC_AUTH`.

Do **not** set `DISABLE_BASIC_AUTH` in App Engine, `app.yaml`, or `./deploy`. Production is Google Sign-In only (not IAP, not shared Basic Auth). If `GAE_ENV` is set, the app **refuses to start** when `DISABLE_BASIC_AUTH` is set, when `SECRET_KEY` is the local default, or when OAuth client id/secret or `RECEIVER_HMAC_SECRET` is missing. Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` on App Engine (`secure: always` in `app.yaml.template`).

Homepage **Copy / Archive / Delete** are POST forms with Flask-WTF CSRF (confirm still runs on delete). Stats cells stay GET `/index/stats-partial` (no CSRF). htmx non-GET requests send `X-CSRFToken` from the page meta tag. Saving a survey that someone else already saved returns **409** with “Someone else saved this survey, reload” (Firestore `last_update_time` precondition). Version numbers are assigned transactionally via `Surveys/{id}/versions/_seq`.

Homepage: archived surveys are hidden unless you click **Show archived**. Copy opens the new survey in the editor. Row actions are one compact column (Preview, Stats, Edit for editors; ZIP/CSV/copy/archive/delete in a ⋯ menu). The stats button and `/survey/reporting/...` work for **Brand Lift and Brand Track**, including size/placement/site/creative/version/date/segment breakouts and a breakouts CSV. Preview does not write to BigQuery (empty `receiver_url`); generate test rows with curl against the receiver as in [Generate test responses](#generate-test-responses).

**Counts treat each COALESCE(RespondentID, BomID) as one respondent** (latest, most complete cumulative `Response`). Surveys set to submit after each question used to be counted once per question; those homepage and report numbers will drop. Submit-at-end rows with a blank BomID and no RespondentID stay as individual respondents.

Reporting (parameterized `WHERE ID = @survey_id`):

* Daily responses by stored `seg` (self-hosted Chart.js 4.4.6)
* Per-question answer distributions
* Brand Lift only: control vs exposed table, Wilson 95% CIs (not Wald), two-proportion z-test p-value plus Holm–Bonferroni p-adj (overall table = one family; each breakout dimension = its own family), n-too-small warning when an arm or question has fewer than 30 respondents. **What does this mean?** (Bootstrap collapse, copy in `ui_help.py`) sits on those warnings plus CI / p-value / Holm notes
* Sequential status on Brand Lift (item 80): O’Brien–Fleming / Lan–DeMets vs a saved sample plan, or an always-valid bound with no plan. Overall and per question use answer A. Breakouts stay fixed-horizon.
* Sample-size planner (item 78): `/survey/sample-size` and `/survey/sample-size/<id>`. Viewers GET; editors POST to save `sample_plan` on the survey.
* Empty states when there is no data, no control, or no exposed segment (same help pattern)
* CSV downloads stream in chunks after the same consolidation (not one in-memory string)

Segment roles come from the stored `seg` value (`control` / `expos` in the string). Brand Lift zips two copies of the **same** survey per size (`default_control` / `default_expose`); the app does not generate a PSA or house ad. Extra placements or DV360 line items are only for placement/site breakouts or a later cost join — not required to compute overall lift.

Status chips: **Active** up to 3 days since last response, **Stale** up to 7 days, **Timed out** after 7. (Previously Stale ran through 14 days.) Thresholds are `STATUS_ACTIVE_DAYS` / `STATUS_STALE_DAYS` in `creative/app/survey_service.py`.

The homepage paginates at `HOMEPAGE_PAGE_SIZE` (**50**, a named constant in `survey_service.py`, not an env var) and projects list fields only (no `custom_css`; includes `client`, `agency`, `created_at`, `created_by`, `creativesize`, `creativesizes`). **GET `/index` does not call BigQuery.** Count / last-received-days / status cells render as `Loading…` and load from `/index/stats-partial` via htmx `hx-trigger="load, every 30s [!document.hidden]"` with `hx-timeout` 20s (`STATS_PARTIAL_TIMEOUT_MS`). The previous `every 30s` trigger never ran before first paint, so the list waited on BQ. A BigQuery (or Storage API) failure used to 500 the partial and leave **Loading…** forever — htmx does not OOB-swap on error. The route now catches exceptions, logs `index.stats_partial_error`, and returns 200 OOB cells with **—** / unavailable tooltip. `htmx:responseError` / `timeout` / `sendError` on `#stats-poller` do the same in the browser. `_query_to_dataframe` still prefers BigQuery Storage `to_dataframe()`; on failure it logs `stats.bqstorage_failed` and retries with `create_bqstorage_client=False` (jobs REST). The stats query is limited to the survey IDs on the current page (`ID IN UNNEST(@survey_ids)`) plus a `CreatedAt` partition window (`STATS_LOOKBACK_DAYS`, default 400). Results are cached **per survey ID** for 90 seconds (`STATS_CACHE_SECONDS`): in-process L1 on each instance, then Firestore collection `StatsCache` L2 with a logical `expires_at` (no Firestore TTL policy, no extra GCP product). `STATS_SHARED_CACHE=0` keeps L1 only. Values can be up to that TTL stale. Surveys with no rows in that window used to produce empty DataFrames that pandas concatenated together (`FutureWarning` on empty-or-all-NA concat). `survey_service._concat_frames` drops empty frames first (homepage counts, brand-lift join, CSV join). Debug logs: `index.firestore_list_ms`, `index.filter_ms`, `index.render_ms`, `index.request_ms`, `index.stats_partial_ms`, `index.stats_partial_error`, `stats.bq_ms` (`cache=l1|l2|miss|skip`), `stats.bqstorage_failed`. **Phase 7d / 68.** Redeploy App Engine (`--app-only`). Firestore creates `StatsCache` on first write.

If live Count/Last/Status stay on Loading… or show **—**, confirm with:

```shell
gcloud app logs read --service=default --project=brandometer2 --limit=50 | grep -E 'index.stats_partial_error|stats.bqstorage_failed|stats.bq_ms'
```

A `stats.bqstorage_failed` line means Storage API `to_dataframe` failed and REST fallback ran (no IAM change required if counts then appear). `index.stats_partial_error` is an uncaught query/IAM failure. Typical IAM: App Engine SA already has project `roles/bigquery.jobUser` plus dataset WRITER on `responses`. If the query itself is Forbidden, grant dataset access (or `roles/bigquery.readSessionUser` if you want Storage API to succeed without the REST fallback):

```shell
gcloud projects add-iam-policy-binding brandometer2 \
  --member="serviceAccount:brandometer2@appspot.gserviceaccount.com" \
  --role="roles/bigquery.readSessionUser"
```

Homepage filters (`q`, `client`, `agency`, `created_by`, `year`, `size`) plus `sort` / `dir` are query params, applied in Python after the list `select()`, and are kept on pagination and the archive toggle. Default sort is `created_at` descending (newest first); surveys with no `created_at` always sort last. Name, client, agency, created_by, id, and sizes are sortable; count / last-received-days / status are not. A survey matches the size filter if that size is in its configured list (legacy docs with no size field match **300×250**). The **Sizes** column is one line (`300×250 +1`; full list in `title`). Count is one line (`C 40 · E 42` for Brand Lift control/expose, a bare number for a generic `survey` segment; full labels in `title` / `aria-label`) so htmx `/index/stats-partial` OOB swaps stay single-line. The last-received header is two lines (`Last Rcvd` / `Data (days)`); the cell is days since the latest response, date in `title`. `#mainTable` is `table-sm` with nowrap/truncate (name, client, agency, created-by email, YYYY-MM-DD created date, questions). Client and Agency are their own columns. Created by is the stored email. Year / creator **Unknown** is for old documents with no `created_at` / `created_by`. Optional **Client** and **Agency** on the editor (datalist of existing values) copy with the survey. `created_at` and `created_by` are set on create and copy. Optional **Campaign ID** / **Placement ID** are placeholders for a future cost join; they are not used in reporting yet.

**Responsive list.** `#survey-cards` (`d-md-none`) is the list below 768px; `#mainTable` is `d-none d-md-block`. Agency uses `d-none d-xl-table-cell`; Created by, Sizes, Count, and Last Rcvd use `d-none d-lg-table-cell`. Survey ID and questions stay `d-none` on this compact list (they still live in the editor). Cards reuse unique stats ids (`count-card-<id>`, `last-card-<id>`, `status-card-<id>`) so htmx OOB swaps can fill both the table and the cards. Actions menus use `actions-<id>` in the table and `actions-card-<id>` on cards.

**Backfill missing created fields.** `tools/backfill_created.py` reads Firestore `AuditLog` `create` / `copy` rows and writes **only** missing `created_at` / `created_by` on `Surveys` (never overwrites). Copy events use `detail` as the new survey id. Dry-run is the default:

```shell
# Cloud Shell, project brandometer2, from the repo root
gcloud config set project brandometer2
python3 tools/backfill_created.py --project brandometer2
python3 tools/backfill_created.py --project brandometer2 --apply
```

Needs ADC that can read `AuditLog` and read/write `Surveys`. AuditLog was added with Google Sign-In on **2026-11-19**; `created_at` on new surveys started the same day. Anything created before that, or never copied/created through the app after audit existed, stays **Unknown** on the list.

**Demo data.** `tools/seed_demo_data.py` is the Cloud Shell tool for load-testing the homepage against **production** Firestore + `brandometer2.responses.responses`. Agents and this VM must not run `--apply`. Dry-run (summary + sample surveys + estimated BQ row count) is the default:

```shell
# Cloud Shell, project brandometer2, from the repo root
gcloud config set project brandometer2
python3 tools/seed_demo_data.py --project brandometer2
python3 tools/seed_demo_data.py --project brandometer2 --apply
python3 tools/seed_demo_data.py --project brandometer2 --purge
python3 tools/seed_demo_data.py --project brandometer2 --purge --apply
```

`--count` default 220 (minimum 200 so the list has 4+ pages at `HOMEPAGE_PAGE_SIZE=50`). `--seed` default 1. `--apply` overwrites the tagged batch (deterministic survey ids `demo_<seed>_<nnnn>`) then load-jobs NDJSON into BigQuery after deleting previous demo rows. `--purge` without `--apply` prints the DELETE SQL and counts tagged Firestore docs; `--purge --apply` deletes them.

**What it creates.** Five fictional agencies (Northline Media, Cedar & Pine Collective, Riverbend Insights, Halcyon Street, Oak & Anchor) with `.example` creator emails and fictional grocery / auto / games / computer / restaurant / apparel clients. Mix of Brand Lift and Brand Track, single and multi size, some `sample_plan` maps, some archived. Response volumes and last-received dates are consistent with homepage **Active** / **Stale** / **Timed out** / **No data** (`STATUS_ACTIVE_DAYS=3`, `STATUS_STALE_DAYS=7`). Control/exposed is roughly 50/50. Respondent ids match app dedupe (`COALESCE(RespondentID, BomID)`, latest/most complete `Response`).

**Tags (purge is exact).** Firestore Surveys: `demo_seed: true`, `demo_batch: demo-<seed>`, document id `demo_*`. AuditLog: `demo_seed: true` and id `demo_audit_<survey_id>` (or `survey_id` starting `demo_`). `DemoSeed/current` bookmark. StatsCache docs whose ids are those surveys. BigQuery: `ID` starts with `demo_` **and** `RandomTimeStamp` starts with `demo_seed:` (plus a 800-day `CreatedAt` window so partitioned tables can prune). Non-demo surveys and rows are never touched.

**IAM (Mark's Cloud Shell user, project `brandometer2`).** Application Default Credentials in Shell usually suffice after `gcloud config set project brandometer2`. Grant:

* `roles/datastore.user` (Firestore `Surveys`, `AuditLog`, `StatsCache`, `DemoSeed`)
* `roles/bigquery.jobUser` (load + DELETE jobs)
* `roles/bigquery.dataEditor` on dataset `responses` (or table `responses.responses`)

**Warning: this writes to the live project.** Load jobs are visible immediately and are deletable; streaming-insert buffer delay (~90 minutes) does not apply unless someone used `insert_rows_json` for demo rows.

**View Survey.** The eye button (and Preview size items in **⋯**) open a Bootstrap modal (`#previewModal`) via `static/home.js`. The iframe loads `/survey/preview/<id>?embed=1` (and `&size=` when needed). `embed=1` hides the Back link and the page size switcher; the modal header owns the size buttons and an **Open page** link to the standalone preview. Modifier-click / middle-click still uses the `href`. The standalone page is unchanged: single-size URLs omit `?size=`; multi-size URLs use the first configured key by default; unknown `?size=` falls back to that first key. Preview still does not post (`receiver_url` empty). No control/exposed toggle on this pass.

The admin UI is self-hosted Bootstrap 5.3.3, Bootstrap Icons 1.11.3, htmx 1.9.12, Alpine.js 3.14.3, and Chart.js 4.4.6 under `creative/app/static/vendor/` (see `VERSIONS`). Style pickers write a theme block of `--bv2-*` CSS variables into `custom_css` (`BV2_THEME_START` / `BV2_THEME_END` sentinels); existing free-form CSS is kept in Advanced (CSS) and still used when zipping creatives. Custom CSS that still names the old variables is not applied. **Presets** are a grouped dropdown (Classic / Loud solids / Complementary / Patterns); Classic green is the default. Patterns are CSS gradients only, with a solid panel behind question and answer text. The live preview iframe resizes to the previewed **creative size** and has a size switcher when more than one size is selected. Set an optional **Display name** to show a friendly label on the homepage (survey name still drives zip filenames).

**Theme CSS.** Pickers and presets write `--bv2-*` variables (`--bv2-bg`, `--bv2-accent`, …) between `BV2_THEME_START` / `BV2_THEME_END`. Size and wrap overlays use `BV2_SIZE_*` and `BV2_LAYOUT_*`. Custom CSS that still uses the previous variable names is not applied on new zips or preview. Redeploy App Engine (`--app-only`) and re-download zips.

**Bulk CSV create.** Editors/admins: navbar **Bulk CSV** → `/survey/bulk`. Download `survey_bulk_template.csv`, preview (validates name, Q1 + answers A/B, sizes, type, F–H only on tall sizes), then create valid rows (max 50). Invalid rows are skipped. `survey_service.create_from_payload` writes the same Firestore fields as the editor form (default CSS, next=end). Viewers 403. Redeploy App Engine (`--app-only`).

**Thank You screen.** `renderThankyou` always runs after the last answer. Tracking pixels and the receiver POST are fire-and-forget (`try/catch`, empty tracker URLs skipped, `resolveRespondentId` failures do not gate the UI). Preview and live zips share `creative.html`; preview only clears `receiver_url`. A 2023 `var window.cookie = ""` syntax error sat in the first `<script>` next to clickTag. Phase 7c item **59** (`52796e5`) added `BV2_*` macros to that same block and read them from `fillMacrosInUrl`, so the empty `trackers: [""]` pixel threw `ReferenceError` *before* thank-you — preview and already-downloaded zips. Redeploy App Engine (`--app-only`) and **re-download zips**.

**Creative sizes.** 300×250 (default for old docs), 160×600, 300×600, 336×280, 970×250. Not 728×90 / 320×50 / 320×100. Stored as `creativesizes` (list) plus `creativesize` (single string when there is one size, otherwise the list) so old docs still load. 970×250 lays answers out in a wrapping grid. Download is an **outer ZIP** of one HTML5 inner ZIP per size (and per Brand Lift segment: `default_control` / `default_expose`) plus `html5_qa.txt` and CM360/DV360 bulk-upload sidecars. Inner ZIPs contain only `index.html` (never a nested zip), `ad.size` for that size, filename ≤ 50 characters, well under 5 MB. clickTag/exit is unchanged.

**HTML5 spec QA.** `html5_qa.py` checks IAB display (200 KB initial / 2.2 MB polite, ~10 host-initiated files), CM360 HTML5 (10 MB / 100 files), clickTag, `ad.size` vs the labelled size, no nested zip, and no unexpected external `https://` (macros, `google.com` clickTag, and `*.googleusercontent.com` are allowed). The configured `RECEIVER_URL` is classified as **`[info] receiver`** (required survey response call; some publishers need that domain allowlisted), not a warning. Other hosts stay `[warning] external`. Findings never block a download. The editor lists them per selected size with a **What does this mean?** Bootstrap collapse (no extra script; CSP unchanged). Zip download flashes a count of warnings/errors only and writes `html5_qa.txt` in the outer archive (do not upload that file as a creative). Plain-English copy is `creative/app/ui_help.py` (`ENTRIES`), shared with the report page (min-n, Holm p-adj, CIs, p-values, missing control/expose, no data). Redeploy App Engine (`--app-only`).

**Answers.** 2–5 answers on 300×250 / 336×280 / 970×250; up to 8 (a–h) when **every** selected size is 160×600 or 300×600. Empty rows are skipped. Answer text wraps (always-injected layout CSS overrides old `.AText { height: 27px }` in stored `custom_css`). Reporting and the receiver treat `1:F` the same as `1:A` (Response is a string).

**Ad badge.** Every creative and the preview has a bottom-left disclosure badge. Default icon is the bevelled **B** (first letter of `APP_BRAND_NAME`, overridable with `APP_BRAND_BADGE_LETTER`). Per-survey **Disclosure badge** on create/edit picks **B**, **B2**, **Ad**, or **Dentsu** (plain-text wordmark in the same bevelled pill; not Dentsu’s official logo). Stored as `badge_icon` / `badge_text`. Blank or missing fields behave as the default tooltip `Survey Type {brand} Ad - powered by Google` (`APP_BRAND_BADGE_TOOLTIP` to override the default string). Popup text is max 120 characters and HTML-escaped. Hover / focus / tap still show the tooltip; it does not fire clickTag. Copy and zip version snapshots keep the fields. Add more faces in `brand.BADGE_ICONS` (reserved `svg` for an uploaded logo).

**Brand.** `export APP_BRAND_NAME=Brandometer2` (that is the default). Navbar, page titles, login, and the badge letter/tooltip use it. Tag sheets and response CSVs do not embed the product name (survey name only). There is no branded email.

**Favicon.** Rounded-square Bootstrap primary (`#0d6efd`) with white **Bv2** (`creative/app/static/favicon.svg`). Raster sizes (16/32/48 ICO, 180 apple-touch) are generated with `python3 tools/generate_favicons.py` and committed. App Engine serves `/favicon.ico` from `creative/app/favicon.ico`; `base.html` and `login.html` also link the SVG, ICO, and apple-touch icon. Browsers cache favicons aggressively — hard-refresh after a change.

**Version history.** Each zip download writes an immutable snapshot to the Firestore subcollection `Surveys/{id}/versions/{n}` (questions, CSS, size, type, timestamp, version number). The edit page lists them with **Download this version**. Editing the live survey does not change past snapshots. No GCS. No new index.

Redeploy **App Engine** (`./deploy` or `gcloud app deploy creative/app`) to pick up size, variable answers, versioning, and reporting. No new Firestore index is required; archive filtering and version listing are done in the app. Optional: `export GTAG_ID=AW-…` before `./deploy` if creatives should load gtag.js.

**Receiver redeploy is required for Phase 7b** (signed tokens, HMAC IP hashes, rate limit). After that, sized HTML from App Engine still posts `creative_size={width}x{height}` as before.

```shell
gcloud functions deploy receiver \
  --gen2 \
  --trigger-http \
  --allow-unauthenticated \
  --runtime python312 \
  --entry-point=receiver \
  --region=us-central1 \
  --source=receiver \
  --service-account="brandometer-receiver@$PROJECT_ID.iam.gserviceaccount.com" \
  --max-instances=20 \
  --timeout=60s \
  --memory=256MB \
  --set-env-vars TABLE_ID="$PROJECT_ID.responses.responses" \
  --set-secrets RECEIVER_HMAC_SECRET=brandometer-receiver-hmac:latest,IP_HMAC_SECRET=brandometer-ip-hmac:latest
```

If `/index` fails with `Not found: Table …responses.responses` (a dataset without the table), create the table in the **same location as the dataset**. `./deploy` uses the location you pass as the second argument (for Mark's `brandometer2` project that was `us-central1`). From the repo root:

```shell
bq mk --table \
  --schema receiver/responses.schema.json \
  --description "Survey response rows for Brandometer" \
  brandometer2:responses.responses
```

Or the equivalent inline schema (no repo file needed):

```shell
bq mk --table \
  --schema 'CreatedAt:DATETIME:REQUIRED,Type:STRING:REQUIRED,ID:STRING:REQUIRED,Segmentation:STRING:REQUIRED,Response:STRING:REQUIRED,Visual:STRING:REQUIRED,CreativeSize:STRING:REQUIRED,RandomTimeStamp:STRING:REQUIRED,BomID:STRING:REQUIRED,RespondentID:STRING,RespondentIDSource:STRING' \
  brandometer2:responses.responses
```

Do not pass `--location` on `bq mk --table`; the table inherits `us-central1` from the existing `responses` dataset. Skip the command if `bq show brandometer2:responses.responses` already succeeds. The homepage also treats a missing table as zero responses, so `/index` still loads.

# Firestore Datastore mode

If the app fails with `The Cloud Firestore API is not available for Firestore in Datastore Mode database projects/…/databases/(default)`, App Engine (or an older `./deploy`) created `(default)` in **Datastore mode**. Brandometer needs **Firestore Native**.

Check:

```shell
gcloud firestore databases describe --database='(default)' --format='value(type)'
```

`DATASTORE_MODE` is the problem; `FIRESTORE_NATIVE` is correct.

If that database is **empty** (a fresh project is), delete it and recreate Native. This cannot be undone and will fail if any entities exist:

```shell
gcloud firestore databases delete --database='(default)'
gcloud firestore databases create \
  --location=us-central1 \
  --type=firestore-native \
  --database='(default)'
```

Then restart the local app (or rerun `./deploy`). `./deploy` now creates Native Firestore **before** App Engine and exits with these same commands if it finds Datastore mode.

# Unit tests

GCP is not required. From the repo root:

```shell
source .venv/bin/activate
pip install -r creative/app/requirements.txt -r requirements-dev.txt
cd creative/app
PYTHONPATH=. pytest
```

`requirements-dev.txt` includes **pip-audit**. From the repo root:

```shell
pip-audit -r creative/app/requirements.txt
pip-audit -r receiver/requirements.txt
```

**Accepted exception: PYSEC-2026-113 on `pyarrow==17.0.0`.** `google-cloud-bigquery-storage` `to_dataframe()` needs pyarrow; do not drop the pin to clear that finding. Revisit when a patched pyarrow that still works with BigQuery Storage is available.

# README screenshots

`docs/images/` is generated by `tools/capture_screenshots.py`. It boots Flask in-process with MockFirestore, synthetic BigQuery rows, and Playwright Chromium. No GCP, no real client data, no real secrets (dummy OAuth / HMAC env only). Generic example emails (`admin@example.com`).

```shell
pip install -r creative/app/requirements.txt -r tools/requirements-screenshots.txt
python3 -m playwright install chromium
python3 tools/capture_screenshots.py
```

Desktop UI shots use a 1400px viewport (capped at 1400px wide); creatives are clipped to `#master_container` at natural size. Homepage recapture: `home.png`, `home-filters.png`, `avatar-dropdown.png`, `home-actions-menu.png`, `home-preview-modal.png` at 1400px, plus `home-narrow.png` (800px table). Do not commit production screenshots or real email addresses.

# Receiver (Cloud Function)

Dependencies: `receiver/requirements.txt`. Deploy is handled by `./deploy` or the `gcloud functions deploy` command in [One-time GCP setup](#one-time-gcp-setup). Redeploy the receiver for Phase 7b (signed tokens, daily HMAC IP hashes, in-memory rate limit) and again for Phase 7c item 58 (durable `rid` / `RespondentID`). **`--app-only` is not enough** for 58: you need a full `./deploy` so the receiver is rebuilt and `ALTER TABLE … ADD COLUMN IF NOT EXISTS RespondentID` runs. Re-download live zips after the App Engine deploy so creatives send `rid` / `rsrc`.

The receiver writes `Type` (default `survey`), `ID`, `Segmentation` (`seg`), `Response`, `BomID` (`bomid`), nullable `RespondentID` / `RespondentIDSource` (`rid` / `rsrc`, falling back to BomID), and the other REQUIRED schema fields. Live creatives post here via a 0×0 iframe pixel; **preview does not** (`receiver_url` is empty, so no token is needed). Success is **HTTP 204** with an empty body (safe for that iframe). Invalid params are **400**, missing/invalid HMAC token **403**, unknown/archived surveys **404**, too many hits **429**, BigQuery/Firestore / missing HMAC secrets **500** with a small JSON body (`reason=…`). The table must already exist — missing `TABLE_ID` / table is 500, not a create. Survey existence is cached in memory for 30 seconds.

**Signed links are required. There is no grace period.** Each zip/creative embeds `token=` HMAC-SHA256(`RECEIVER_HMAC_SECRET`, survey id) as hex. The receiver and App Engine share `brandometer-receiver-hmac`. Rotating that secret invalidates every live zip until you re-download.

**Rate limit.** 30 requests / minute / (hashed IP + survey id), **per Cloud Function instance**. `./deploy` sets `--max-instances=20`, so the theoretical ceiling for one IP+survey is 600/minute across instances. The map is in-memory (lost on instance recycle) and capped at 20 000 keys per instance. This is abuse control, not a global quota.

**IP hashing.** `RandomTimeStamp` is **not** unsalted SHA-256 of the IP. It is HMAC-SHA256 of the IP, keyed by a daily key `HMAC(IP_HMAC_SECRET, YYYY-MM-DD UTC)`. Same IP on the same UTC day produces the same hash (dedupe still works). Hashes cannot be reversed to an IP and cannot be linked across days. The IP itself is not stored.

**Durable respondent ID (Phase 7c / 58).** One person per survey in counts, reports, and CSV. The creative resolves `rid` in this order: (1) SHA-256(`receiver_token` + newline + expanded ad-server user id) when `%u`, `${USER_ID}`, or `%%USER_ID%%` is expanded — raw ids never leave the browser; (2) `localStorage` / `sessionStorage` key `bv2.rid.<surveyId>` (partitioned by the creative origin); (3) a fresh UUID for this impression. `bomid` is set to the same value so per-question submits still group. `rsrc` is `macro`, `storage`, or `impression`. Old rows: `RespondentID` NULL, dedupe by BomID. Existing REQUIRED columns are unchanged; `./deploy` adds the two NULLABLE columns with `ALTER TABLE … IF NOT EXISTS`.

Creatives show: “Your IP address is not stored. A daily hash limits repeat posts. A survey-only ID (this browser, or a hashed ad-server id) counts each person once and is not shared across surveys.”

# Generate test responses

Preview never posts (`receiver_url` is empty). To see homepage counts, reporting, and CSV, `curl` the live receiver. Schema fields are REQUIRED — send dummy `visual` / `creative_size` even if unused.

```shell
export PROJECT_ID="your-gcp-project-id"
export RECEIVER_URL="$(gcloud functions describe receiver --gen2 --region=us-central1 --format='value(serviceConfig.uri)')"
export RECEIVER_HMAC_SECRET="$(gcloud secrets versions access latest --secret=brandometer-receiver-hmac)"
# Firestore document id from the homepage Survey ID column
export SURVEY_ID="paste-survey-id"
# Unversioned token (old zips / curl without ver=). Live zips after the
# CreativeVersion change use HMAC(secret, survey_id + newline + version).
TOKEN="$(python3 -c 'import hmac,hashlib,os; print(hmac.new(os.environ["RECEIVER_HMAC_SECRET"].encode(), os.environ["SURVEY_ID"].encode(), hashlib.sha256).hexdigest())')"
# Versioned live zip (example ver=1):
# TOKEN="$(python3 -c 'import hmac,hashlib,os; print(hmac.new(os.environ["RECEIVER_HMAC_SECRET"].encode(), (os.environ["SURVEY_ID"]+"\n1").encode(), hashlib.sha256).hexdigest())')"
# and add: --data-urlencode "ver=1"

post() {
  # $1=seg  $2=response  $3=bomid
  curl -sS -G "$RECEIVER_URL" \
    --data-urlencode "type=survey" \
    --data-urlencode "id=$SURVEY_ID" \
    --data-urlencode "seg=$1" \
    --data-urlencode "response=$2" \
    --data-urlencode "visual=none" \
    --data-urlencode "creative_size=${4:-300x250}" \
    --data-urlencode "bomid=$3" \
    --data-urlencode "token=$TOKEN"
  echo
}

# Brand Track (empty seg), one row per person
post "" "1:A|2:B" "track-1"
post "" "1:B|2:A" "track-2"

# Brand Lift: per-question submit, same BomID, growing Response
post "default_control" "1:A" "lift-c1"
post "default_control" "1:A|2:B" "lift-c1"
post "default_control" "1:B" "lift-c2"
post "default_expose" "1:A" "lift-e1"
post "default_expose" "1:A|2:A" "lift-e1"
post "default_expose" "1:A" "lift-e2"
```

A successful insert returns HTTP 204 (empty body). `curl -sS` still exits 0; add `-w '%{http_code}\n'` if you want to see the status. Invalid `id` / `response` / size characters return 400. Missing or wrong `token` returns **403**. Streaming inserts can take a few seconds to show up in `SELECT`. Homepage counts are cached up to 90 seconds (`STATS_CACHE_SECONDS`; set `0` while testing) in process memory and in Firestore `StatsCache`. Reporting and CSV query BigQuery on each request.

Per-question submits for `lift-c1` / `lift-e1` collapse to **one respondent each** (the longer Response). Raw `COUNT(*)` in BigQuery stays higher.

# Cloud Shell test (Phase 3)

```shell
gcloud config set project "$PROJECT_ID"
cd "$(git rev-parse --show-toplevel)"
git pull
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r creative/app/requirements.txt

export PROJECT_ID="$(gcloud config get-value project)"
export TABLE_ID="$PROJECT_ID.responses.responses"
export DISABLE_BASIC_AUTH=1
export STATS_CACHE_SECONDS=0
export RECEIVER_URL="$(gcloud functions describe receiver --gen2 --region=us-central1 --format='value(serviceConfig.uri)')"

cd creative/app
flask --app main run --port 8080 --debug
```

Web Preview → port 8080.

1. Create or open a Brand Track survey and a Brand Lift survey. Copy the Survey ID.
2. Confirm preview still does not post (Network tab / BigQuery unchanged).
3. Run the curl recipe above against those IDs.
4. Homepage: counts should be respondents (BomID), not raw rows. Track and Lift both have a stats button.
5. Open stats: daily chart, distributions; Lift also has control vs exposed, Wilson CIs, p-values, sequential status, and a small-n warning until each arm has 30 respondents. Empty surveys show “No responses yet”. Navbar **Sample size** calculates n and impressions; save on a Lift survey as an editor.
6. Download CSV: one row per BomID; streaming (not a single buffered string).
7. Optional: `bq query --nouse_legacy_sql "SELECT BomID, Response FROM \`$TABLE_ID\` WHERE ID='$SURVEY_ID' ORDER BY CreatedAt"` to compare raw vs consolidated.

Redeploy App Engine before this is live in production. Receiver redeploy is required for Phase 7a validation and status codes.

# Cloud Shell test (Phase 4)

Same start as Phase 3 (`DISABLE_BASIC_AUTH=1`, Web Preview port 8080). Then:

1. **Size.** Create survey → Creative size **160×600**. Live preview iframe should grow to 160×600. Save, download zip: filename contains `_160x600`. Unzip `index.html` and check `<meta name="ad.size" content="width=160,height=600">` and `#master_container` width/height 160/600. Open preview: same meta. Optional curl with `creative_size=160x600` then `bq query` that `CreativeSize` column.
2. **Answers.** On question 1, **Add answer** until E is visible; **Remove last answer** hides it and clears the field. Save a 2-answer question and a 5-answer question. Preview should show only filled options. Reporting/CSV should list A–E when present and skip blanks.
3. **Versions.** Homepage → download zip. Edit the survey: **Version history** shows version 1. Change a question and size, save, download zip again. History has version 2. **Download this version** on v1 should still zip the old questions/size. Edit must not rewrite v1 (download v1 after further edits and confirm old copy).
4. **Presets.** Style → Classic green / Dark / High contrast / Ocean updates the pickers and preview. Advanced CSS is kept.

Existing 300×250 four-answer surveys should look the same until you change them.

# Assessments (not built)

**Free-form responses (backlog ID 12).** Not small enough to ship here. The 300×250/160×600 creative has no usable text field today; Response is tokenised `1:A|2:B`. A write-in needs creative JS (keyboard in a display ad), a storage choice (stuff text into the token vs a new BQ column — schema is REQUIRED and already full), and reporting that cannot run lift on free text. Recommend a later optional “Other” answer that reveals a short input and stores `1:OTHER:text` in `Response`, skipped for lift, shown in CSV. Do not add a sixth BQ column unless you are willing to migrate the table.

**Video creative.** Do not build yet. DV360/CM video line items serve **VAST** (2/3/4), not an HTML5 zip. Typical brand-lift-on-video setup is a linear video plus an IAB **companion banner** (300×250) that is our existing survey. Recommended path: keep the HTML5 survey as the companion; generate a VAST XML that references a hosted video file and a public URL for the companion (that URL is the extra piece — App Engine or GCS). In-stream SIMID/VPAID overlays are a much larger project and VPAID is on the way out. Effort: companion-VAST generator is a later phase of its own (hosting + XML + CM/DV360 video placement docs); not a small add-on to this zip.

**Asset templates (backlog ID 4 / old #8).** Implemented as the grouped **theme preset** dropdown (26 themes, Classic green first). They write picker values, accent, panel, and CSS-only patterns into `custom_css`. Full “asset packs” (logos, CM placement kits) would still be a separate piece of work.

**Cost / impressions dashboard.** Not built. Two ingestion options:

1. **CM360 / DV360 → BigQuery Data Transfer.** Campaign Manager 360 Data Transfer v2 and the Display & Video 360 BigQuery Data Transfer dump impressions, clicks, and cost (with campaign and placement IDs) on a schedule. Join `Surveys.campaign_id` or `Surveys.placement_id` to those tables, then show cost, impressions, CPM, and cost per completed survey. This is the production path if CM/DV360 is already the source of truth: transfer IAM, schema mapping, currency, and aligning report dates with response `CreatedAt` are the real work. Do not scrape the DV360 UI.

2. **Sheet / CSV upload.** Columns such as date, campaign_id or placement_id, impressions, cost. Parse in Flask and store in BigQuery or a Firestore subcollection, same join. Faster to prototype, manual, no daily refresh, easy to get IDs wrong.

Join key if you add a cost dashboard later: **Placement ID** is the precise join; **campaign ID** is enough only when a survey maps 1:1 to a campaign. Extra placements or DV360 line items are **not** required for Brand Lift control vs expose (that is the baked `seg` on two copies of the survey). Use extra placements when you want placement- or site-level breakouts or a cost join. Both optional Identity fields show on the report/tag sheet, go on the pixel when macros do not expand, and are stored on the row when the ad server expands them. A cost/impressions dashboard is still not built.

Effort: the dashboard (join quality, unmatched IDs, currency, a cost table next to Brand Lift) is a later phase of its own. A sheet upload is the smaller stopgap. The Data Transfer path is larger but is what you want if this will be used weekly. Redeploy is not required for the placeholder ID fields until you want them in production editor.

# Cloud Shell test (Phase 5)

Same start as Phase 3 (`DISABLE_BASIC_AUTH=1`, then from `creative/app`: `flask --app main run --port 8080 --debug`). Web Preview → port 8080.

1. **Identity.** Create survey: Client, Agency, Campaign ID, Placement ID in Identity. Type a client used on another survey and confirm the datalist suggests it. Save. Homepage has **Client** and **Agency** columns (not a subtitle under the name).
2. **Copy.** Copy that survey. Editor should still have the same client/agency/IDs. `created_at` / `created_by` on the copy are now (the copier’s email). Old docs without those fields stay **Unknown**.
3. **Filters.** Homepage: filter by client, agency, created by, year, size, and a name search. Combine with **Show archived**. Next/Previous should keep the query params (and `sort`/`dir`). Clear returns to the unfiltered list (archive toggle unchanged). Default order is newest created first. The Sizes column shows chips (legacy rows show 300×250). Shrink the preview below 768px: cards, not the table. Around 992px Agency should be gone; Client stays.
4. **Old surveys.** A document with no `created_at` appears under Year → Unknown and Created → Unknown, and still lists if you do not filter by year. Optionally run `tools/backfill_created.py` (dry-run, then `--apply`) on project `brandometer2`.

# Cloud Shell test (Phase 6)

Same start (`DISABLE_BASIC_AUTH=1`, `cd creative/app`, `flask --app main run --port 8080 --debug`). Web Preview → port 8080.

1. Navbar says **Brandometer2** (or `APP_BRAND_NAME`). Create survey: check **300×250** and **970×250**. Editor preview switcher appears; 970×250 is wide with answers in a grid. Check only **160×600** and **Add answer** through H. Checking 300×250 as well should drop F–H on save (validation).
2. Homepage: that two-size survey has Sizes chips. Click the eye: a modal iframe (`?embed=1`) with a size switcher. **Open page** still loads `/survey/preview/<id>`. Pick **970×250** from **⋯** → Preview size. A one-size survey still has a plain eye button and no modal size switcher. Filter Size = 970×250 hides surveys that do not include it; combine with page 2 / Show archived.
3. Theme preset dropdown: Classic green first; groups Classic / Loud solids / Complementary / Patterns. Hazard stripes should show a striped background with readable answer panels.
4. Download zip with two sizes: outer zip contains two inner zips plus `html5_qa.txt`; each inner has only `index.html`, `ad.size` matching that size, a **B** badge bottom-left. Hover/tap the badge for the tooltip. Inner filenames ≤ 50 chars. Editor **HTML5 spec QA** should say no warnings (or list them, with **What does this mean?**). The survey receiver URL is `[info]`, not a warning. Download flashes if the report has warnings (info-only does not flash).
5. **Disclosure badge.** Create survey: Icon picker shows B / B2 / Ad / Dentsu. Default B looks like the current bevelled letter. Pick **Dentsu** and 160×600 — the wordmark is a small pill, not overlapping answers. Change popup text; preview updates immediately. **Use default** restores the `Survey Type Brandometer2 Ad - powered by Google` string. Leave text blank and save — creative still uses that default. Copy the survey; badge choices come along.
6. Homepage speed: the survey table should appear immediately with **Loading…** in count / last-received-days / status; those cells fill in after `/index/stats-partial` (check Network: `/index` returns before the stats request). A failed/timed-out stats request shows **—**, not eternal Loading…. Flask debug log lines `index.request_ms` (bq=deferred), `stats.bq_ms`, and on failure `index.stats_partial_error`.
7. Trafficking: in CM360, **Upload HTML5** (batch) the inner zips. Brand Lift is two copies of the same survey per size (`default_control` / `default_expose`) — assign those to Control vs Expose **audiences**, not a PSA. One placement per size with two ads is enough for overall lift. Extra placements/line items are only for breakouts or a cost join. Do not upload the outer zip as a creative. Match placement dimensions to 300×250 / 160×600 / 300×600 / 336×280 / 970×250. Preview still does not post to BigQuery.

# CM360 batch upload (Phase 6)

1. Download the survey zip from the homepage.
2. Unzip the **outer** archive on your machine. You should see one `.zip` per size (Brand Lift: two per size, `default_control` and `default_expose`), `html5_qa.txt` (a report — do not upload it), and bulk-upload sidecars (`cm360_html5_bulk.csv`, `dv360_html5_bulk.csv`, `HOW_TO_UPLOAD.txt`).
3. In Campaign Manager 360 → Creatives → **New** → **Display** → upload each **inner** zip as HTML5. The `ad.size` meta inside `index.html` must match the placement. Optional: fill **Advertiser ID** on the CM360 CSV and use CM360 bulk upload, mapping `HTML5 zip filename` to the inner zip on that row.
4. Do not put a zip inside a zip when uploading; each inner file is already a legal HTML5 creative (`index.html` only). Do not upload the sidecar CSVs as creatives.
5. Brand Lift: assign `…_default_control.zip` to the Control audience ad and `…_default_expose.zip` to the Expose audience ad. Both files are the same survey labelled by `seg`. The app does not ship a PSA/house ad.

**Phase 7d / 67 bulk-upload files.** Editors can also download only the sidecars from the homepage or report (`/survey/download_bulk_upload/<id>`). Advertiser ID is blank on purpose. This app does **not** call the CM360 or DV360 APIs and does not store OAuth or service-account credentials. Stopped before anything Mark would have to mint in Cloud Console. Redeploy App Engine (`--app-only`).

Redeploy **App Engine** for Phase 6. Receiver redeploy is not required for sizes/answers (`Response` already stores `1:H`). Optional env: `APP_BRAND_NAME`, `APP_BRAND_BADGE_LETTER`, `APP_BRAND_BADGE_TOOLTIP`.

# Cloud Shell test (Phase 7a)

Same start as Phase 3 (`DISABLE_BASIC_AUTH=1` locally only). Then:

1. Homepage: Copy / Archive / Delete are buttons inside POST forms. Delete still confirms. A GET to `/survey/delete` is 405. Edit a survey, save, then in another tab save the same survey again — you should see **Someone else saved this survey, reload** (HTTP 409).
2. Network: `/index/stats-partial` is GET. Any future htmx POST would send `X-CSRFToken`.
3. Preview / zip: question and answer text is assigned with `textContent`. A `custom_css` value containing `</style><script>` must not appear in the creative HTML.
4. Receiver (after 7a redeploy): `curl` a missing survey id → 404; omit `response` → 400; valid row → 204. The function must not create a BigQuery table. After 7b the same curls need `token=` or they return 403.
5. Production: `./deploy` no longer prompts for a shared password. See [Phase 7b deploy](#phase-7b-deploy-mark). Do not set `DISABLE_BASIC_AUTH` in App Engine.

`pyarrow` is still required (`google-cloud-bigquery-storage` `to_dataframe()`). Do not drop it. Accepted pip-audit exception: **PYSEC-2026-113** on `pyarrow==17.0.0`. App and test pins: `protobuf==5.29.6`, `pytest==9.0.3`.

# Phase 7b (Google Sign-In, signed pixels, daily IP HMAC)

There is **no tenancy**: every allowed user sees every survey. Roles are `admin` (Admin page + everything), `editor` (create/change surveys, ZIP downloads; no Admin), and `viewer` (list, preview, reports, CSV results only). Firestore collections: `AccessUsers` (email → role), `AccessConfig/settings` (`domains` plus `domain_roles` default role per domain), `AuditLog` (create/edit/delete/copy/archive + admin changes, including role updates), `StatsCache` (homepage count L2, logical `expires_at`). Surveys and versions store `created_by` / `created_at` / `updated_by` / `updated_at`. Verified `@google.com` Google identities (`email_verified` and `hd` empty or `google.com`) can always sign in as **editor** unless listed with another role. Missing/unknown stored roles read as **editor** (existing allowlist users are not downgraded). The first admin is `BOOTSTRAP_ADMIN_EMAIL`. Navbar avatar dropdown shows the signed-in email, role, and **Sign out**.

Identity-Aware Proxy is **not** used.

# Phase 7b deploy (Mark)

Do this once per GCP project (or when the OAuth client / bootstrap admin changes). `./deploy` creates HMAC and session secrets if they are missing and does **not** rotate them on later runs.

1. In [Google Cloud Console](https://console.cloud.google.com/) open the target project.
2. **APIs & Services → OAuth consent screen**
   1. User type: **Internal** if this is a Google Workspace project; otherwise **External** (add yourself as a test user while the app is in Testing).
   2. App name: `Brandometer2`. Support email: your address.
   3. Scopes: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (Authlib requests `openid email profile`).
   4. Authorized domains: `appspot.com`. Optionally `cloudshell.dev` if you will try Sign-In from Cloud Shell Web Preview.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   1. Application type: **Web application**. Name: `Brandometer2 web`.
   2. **Authorized JavaScript origins** (replace `PROJECT_ID`; us-central App Engine also uses `uc.r.appspot.com`):
      - `https://PROJECT_ID.appspot.com`
      - `https://PROJECT_ID.uc.r.appspot.com`
      - `http://127.0.0.1:8080`
      - `http://localhost:8080`
   3. **Authorized redirect URIs** (exact; this is what Sign-In needs):
      - `https://PROJECT_ID.appspot.com/auth/callback`
      - `https://PROJECT_ID.uc.r.appspot.com/auth/callback`
      - `http://127.0.0.1:8080/auth/callback`
      - `http://localhost:8080/auth/callback`
   4. Cloud Shell Web Preview on port **8080** uses a **per-session** host. After you open Web Preview, add that origin and callback, for example:
      - `https://8080-<session>.cs-<region>.cloudshell.dev`
      - `https://8080-<session>.cs-<region>.cloudshell.dev/auth/callback`
      - `https://8080-dot-<vm>-dot-devshell.appspot.com`
      - `https://8080-dot-<vm>-dot-devshell.appspot.com/auth/callback`
      Practical Shell path: skip OAuth there and `export DISABLE_BASIC_AUTH=1` (refused on App Engine).
   5. Create the client. Copy **Client ID** and **Client secret**.
4. From the repo root, with billing-enabled `gcloud` pointed at the project:

```shell
./deploy "$PROJECT_ID" us-central1 us-central
```

To redeploy **only App Engine** after a failed `gcloud app deploy` (or to rotate the OAuth client secret):

```shell
./deploy "$PROJECT_ID" us-central1 us-central --app-only
```

5. When prompted (`[press Enter to keep existing]` if the secret already exists):
   1. **OAuth client ID** — paste the Web client ID, or Enter to keep.
   2. **OAuth client secret** — paste the secret (not echoed). After a write you should see `stored N chars (brandometer-oauth-client-secret)`.
   3. **Bootstrap admin email** — your Google account, e.g. `mark@google.com`. This identity becomes the first **admin** and is upserted into `AccessUsers` on first sign-in.
6. `./deploy` writes Secret Manager (`brandometer-oauth-client-id`, `brandometer-oauth-client-secret`, `brandometer-secret-key`, `brandometer-receiver-hmac`, `brandometer-ip-hmac`), deploys the receiver with HMAC secrets and `--max-instances=20` (skipped with `--app-only`), and deploys App Engine with `BOOTSTRAP_ADMIN_EMAIL`. The generated yaml is checked for App Engine standard keys before `gcloud app deploy`.
7. Open `https://PROJECT_ID.appspot.com`, **Sign in with Google** as the bootstrap email, confirm the navbar shows your address and **Sign out**, then open **Admin**. Add other users (`email` + `admin`/`editor`/`viewer`) and extra allowed domains (each with a default role; editor unless you change it). `@google.com` accounts can sign in as editors without being listed.
8. Download a survey zip, unzip an inner `index.html`, and confirm `response_server` contains `&token=`. Preview in the app still has an empty `response_server` (unsigned, does not post).
9. `curl` the receiver without `token` → **403**. With the HMAC token from [Generate test responses](#generate-test-responses) against an active survey → **204**.

Redeploy **App Engine and the receiver** for Phase 7b. Do not set `DISABLE_BASIC_AUTH` in production.

# Cloud Shell test (Phase 7b)

Same start as Phase 3 (`DISABLE_BASIC_AUTH=1`, Web Preview port 8080). Then:

1. Navbar shows `local-dev`, **Admin**, and **Sign out**. Admin page lists users/domains/audit (empty until you add some). Create/edit/copy/archive a survey; Admin → Audit log should show those actions.
2. Download zip: inner `index.html` `response_server` includes `&token=` when `RECEIVER_HMAC_SECRET` is set. Preview HTML must **not** include a token and must not post.
3. After receiver redeploy: curl without token → 403; curl with token for a missing id → 404; omit `response` → 400; valid signed row → 204. `RandomTimeStamp` in BigQuery is a 64-char hex string that is **not** `sha256(ip)`.
4. Thank-you screen in preview shows the privacy sentence after submit.

# Phase 7c / 61 (reporting breakouts)

The report page **Breakouts** section (and `/survey/download_breakouts/<id>`) recomputes the same Wilson 95% CIs and two-proportion z-test per slice of:

* **Size** (`CreativeSize`)
* **Placement** (`PlacementID`)
* **Site** (`SiteID` — expanded ad-server site macro)
* **Creative ID** (`AdCreativeID` — the expanded ad-server creative macro)
* **Creative version** (`CreativeVersion` — zip snapshot number stamped as `ver=`)
* **Date** (`CreatedAt` UTC day)
* **Segment** (`Segmentation`)

A dimension is omitted when every row is blank. Mixed NULL / numbered versions show **Unknown / pre-version** for old rows. Slices with only one lift arm show counts/CIs for that arm and em-dash for lift. Small-n uses the same `MIN_N = 30` threshold as the overall table (slice respondents or people who answered that question).

CSV columns: `dimension,slice,question_index,question,answer_id,answer,n_answered,k,p,ci_lo,ci_hi,n_control,…,lift,pvalue,pvalue_adjusted,warning_n_small,sequential_status`. Proportions are 0–1. `overall,all` is the un-sliced table. `pvalue` is unadjusted; `pvalue_adjusted` is Holm–Bonferroni within that CSV dimension (`overall` or one breakout). Breakout unadjusted p &lt; 0.05 is exploratory. `sequential_status` is filled on overall rows only.

**Stats methods (Phase 7d / 66).** Wilson 95% CIs stay; Wald is not used near 0/1. The two-proportion z-test is two-sided with pooled SE. Holm is applied after every answer-level p-value is computed. Redeploy App Engine (`--app-only`).

**Sample-size planner (Phase 7e / 78).** Standalone page (`/survey/sample-size`) so viewers can use it without the editor; per-survey URL saves onto that Firestore document. Inputs: baseline positive rate (default 20%), MDE relative 10% or absolute pp, confidence 95%, power 80%, comparisons (α/m, Holm first step), response rate 1%, control share 50%. Output: n per arm (ceil, then `MIN_N=30` floor), total n, impressions = n / rate. Table repeats a few lift values. Formula: two-sided two-proportion sample size with pooled-null / unpooled-alternative variances and allocation k = n_e / n_c — the same z-test as `reporting.two_proportion_z`. Calculation is server-side (GET form; no extra script). Editors POST to `survey_service.save_sample_plan`. Redeploy App Engine (`--app-only`).

**Sequential reporting (Phase 7e / 80).** Why O’Brien–Fleming (Lan–DeMets) when a plan exists: the planner already names a final n, the continuous OF bound `z_{α/2}/√t` equals the usual critical value at t = 1, and information `t = I/I_plan` with `I = 1/(1/n_c+1/n_e)` handles unequal arms. Why an always-valid Robbins mixture bound (`√(2 log(1/α) + log(n_c+n_e))`) with no plan: there is no designed end, so a time-uniform bound is the honest peeking rule (more conservative than OF). Futility is declared only at t = 1 without an efficacy cross. Statuses: Collecting, Conclusive: positive lift, Conclusive: negative lift, Conclusive: no meaningful lift / futility, Not enough data (n&lt;30). Overall / per question = answer A. Breakouts remain fixed-horizon. Simulated null type I stays ≤ α within tolerance. Redeploy App Engine (`--app-only`). Item **79** (holdout control) is not built.

`fetch_survey_response_rows` SELECTs `CreativeSize` and `CreativeVersion` as well as the trafficking IDs. Response CSV includes **Size** and **Creative version**.

# Phase 7c / 61b (zip snapshot version on the pixel)

Each ZIP download records the Firestore snapshot **first**, then bakes that number into the creative as `ver=` and HMAC-SHA256(`RECEIVER_HMAC_SECRET`, `survey_id + newline + version`). Re-downloading a stored version uses that snapshot’s number. Preview stays unsigned and does not send `ver=`.

The receiver accepts `ver` as an integer 1…1 000 000. Missing `ver` (old zips) still validates HMAC(survey id) only and stores `CreativeVersion` NULL. A `ver` with the unversioned token is **403**. Invalid `ver` is **400**.

**Full `./deploy`** (not `--app-only`): receiver writes `CreativeVersion`; `ensure_respondent_columns` ALTERs `CreativeVersion INT64` on `--app-only` too so App Engine SELECT does not 500. Re-download every live zip after App Engine is up.

Tag sheet column `creative_version` is the **next** snapshot number (what the following ZIP download will stamp). Re-download the sheet when you re-download zips.

Authorized view `deduped_responses` includes `CreativeVersion`. `survey_summaries` adds `first_creative_version` / `last_creative_version`.

Cloud Shell: unzip a new inner `index.html` and confirm `response_server` contains `&ver=` and a token that is **not** HMAC(survey id) alone. Curl without `ver=` still 204 (NULL version). Curl `ver=1` with the unversioned token → 403.

Cloud Shell: open a Brand Lift report with mixed sizes (or curl two sizes into BQ) and confirm Breakouts lists each size with lift/CIs; download CSV and confirm `Size,` rows.

# Phase 7c / 60 (authorized views + Looker Studio)

`./deploy` (including **`--app-only`**) creates dataset `$PROJECT_ID:brandometer_reporting` in the same location as the rest of the project, then:

1. `CREATE OR REPLACE VIEW …deduped_responses` — one row per survey + respondent (`COALESCE(RespondentID, BomID)`, latest/most complete `Response`). Columns include campaign/placement/site/creative ids, `CreativeSize`, and `CreativeVersion`. Does **not** expose `RandomTimeStamp` / IP hashes.
2. `CREATE OR REPLACE VIEW …survey_summaries` — `survey_id`, `Segmentation`, respondent count, first/last `CreatedAt`, min/max `CreativeVersion`.
3. Authorizes the **reporting dataset** (`targetTypes: VIEWS`) on `responses` via `bq show` + `bq_dataset_iam.py authorize-dataset` + `bq update --source`. Analysts with `READER` on `brandometer_reporting` can query the views without access to the raw table.

The report page **Open in Looker Studio** uses the [Looker Studio Linking API](https://developers.google.com/looker-studio/integrate/linking-api) against `deduped_responses`. Each click starts a **new** untitled report. Save and share that report in Looker Studio if you want a stable dashboard URL.

**Grant a user or Google group** (do this once per analyst; `./deploy` does not guess emails):

```shell
# 1. Project-level jobs (required to run queries / Looker Studio).
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:ana@dentsu.com" \
  --role="roles/bigquery.jobUser" \
  --condition=None

# Group instead of a user:
#   --member="group:dentsu-bq@example.com"

# 2. READER on the reporting dataset only (not responses).
PYTHONWARNINGS=ignore bq --format=prettyjson --quiet show --dataset \
  "$PROJECT_ID:brandometer_reporting" > /tmp/brandometer-reporting.json
python3 creative/app/bq_dataset_iam.py merge-reader \
  /tmp/brandometer-reporting.json user:ana@dentsu.com
# or: ... merge-reader /tmp/brandometer-reporting.json group:dentsu-bq@example.com
bq --quiet update --source /tmp/brandometer-reporting.json \
  "$PROJECT_ID:brandometer_reporting"
python3 creative/app/bq_dataset_iam.py verify-reader \
  /tmp/brandometer-reporting.json user:ana@dentsu.com
```

**Connect Looker Studio manually:** Create → Data source → BigQuery → project `$PROJECT_ID` → dataset `brandometer_reporting` → table `deduped_responses` (or `survey_summaries`). Filter `survey_id` to one study. Do not add the `responses.responses` table to a Dentsu-shared report.

Do **not** grant `READER` / `dataViewer` on `responses`. If an analyst can `SELECT` from `responses.responses` directly, the authorized-view boundary is bypassed.

Receiver code is unchanged. **`--app-only` is enough** after App Engine is already up.

# Phase 7c / 59 (ad-server macros + tag sheet)

Identity → **Ad server** (CM360 default, DV360, GAM, generic) writes clickTag / cachebuster / placement / site / creative / user / GDPR / US-privacy placeholders into the zip. Expanded campaign/placement/site/creative IDs are posted as `camp` / `plc` / `site` / `crid` (NULLABLE BQ columns). GDPR/US privacy strings are **not** sent to the receiver.

Editors download a tag sheet: `/survey/download_tags/<id>` (CSV) or `?format=xlsx`. Viewers get 403.

**Full `./deploy` again** (not `--app-only`): receiver writes the new columns; `ensure_respondent_columns` ALTERs `CampaignID`, `PlacementID`, `SiteID`, `AdCreativeID`. Re-download zips after App Engine is up.

# Phase 7c / 58 (durable respondent ID)

Full `./deploy` (not `--app-only`): adds NULLABLE `RespondentID` / `RespondentIDSource` on existing tables, deploys the receiver that writes `rid`/`rsrc`, then App Engine. Re-download every live zip after App Engine is up — old creatives keep sending impression-level BomID only.

Homepage, reports, and CSV already collapse by `COALESCE(RespondentID, BomID)` once the columns exist (`ensure_respondent_columns` also runs on `--app-only` so SELECT does not fail; the receiver still needs the full deploy to *write* the new fields).

Default privacy choice (reversible): raw ad-server user ids are hashed in the browser (`SHA-256(token + newline + uid)`) and never sent on the pixel or stored. Macros tried: CM360 `%u`, DV360/GAM `${USER_ID}`, `%%USER_ID%%`. Unexpanded placeholders are ignored. To stop using macros, change `ad_user_id_candidates` in `creative.html` and re-download zips.

Cloud Shell: download a zip, confirm `response_server` contains `&rid={rid}&rsrc={rsrc}` and `resolveRespondentId`. Preview still does not post. After full deploy, curl with `bomid=b1` and no `rid` → 204 and `RespondentID=b1`, `RespondentIDSource=bomid`. Curl with `rid=<64 hex>&rsrc=storage` stores that rid.
