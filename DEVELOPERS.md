# Sonar developer guide

Sonar is a Flask + Google Cloud app (App Engine, Firestore, BigQuery, Cloud Functions) for building brand-lift / brand-track survey creatives. It started as a fork of Google Brandometer (Apache-2.0).

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
  artifactregistry.googleapis.com

# Firestore Native (default) — do this *before* `gcloud app create`, which
# otherwise provisions (default) in Datastore mode.
gcloud firestore databases create \
  --location=us-central1 \
  --type=firestore-native \
  --database='(default)'

# BigQuery dataset + responses table (same schema as the receiver).
# New tables are partitioned by CreatedAt and clustered by ID. Skip this
# `bq mk --table` if the table already exists; do not migrate an existing table.
bq --location=us-central1 mk --dataset --description "Main response data set for Sonar" "$PROJECT_ID:responses"
bq mk --table \
  --schema receiver/responses.schema.json \
  --time_partitioning_field CreatedAt \
  --time_partitioning_type DAY \
  --clustering_fields ID \
  --description "Survey response rows for Sonar" \
  "$PROJECT_ID:responses.responses"

# Optional: deploy the HTTP receiver so survey creatives can post answers
gcloud functions deploy receiver \
  --gen2 \
  --trigger-http \
  --allow-unauthenticated \
  --runtime python312 \
  --entry-point=receiver \
  --region=us-central1 \
  --source=receiver \
  --set-env-vars TABLE_ID="$PROJECT_ID.responses.responses"
```

The App Engine service is only required for hosting, not for running Flask on your laptop.

# Run locally

From the repo root, on Mac or Linux:

```shell
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r creative/app/requirements.txt
```

Export credentials and config (the homepage talks to Firestore + BigQuery; basic auth is on unless you set `DISABLE_BASIC_AUTH=1`):

```shell
export PROJECT_ID="your-gcp-project-id"
export TABLE_ID="$PROJECT_ID.responses.responses"
export AUTH_USERNAME="mark"
export AUTH_PASSWORD="choose-a-local-password"
# Optional. A dev default is used if unset; set a real value before any shared deploy.
# export SECRET_KEY="replace-me"
# Optional until the receiver function exists. Preview still works without it.
export RECEIVER_URL="$(gcloud functions describe receiver --gen2 --region=us-central1 --format='value(serviceConfig.uri)')"
# Optional. Google tag (gtag.js) ID for creatives. Unset or empty skips the loader
# (there is no default Ads ID). Example: export GTAG_ID="AW-123456789"
# export GTAG_ID=""
# Optional. Homepage BQ stats cache TTL in seconds (default 90). 0 disables.
# export STATS_CACHE_SECONDS=90
```

If `gcloud functions describe` fails because the function is not deployed yet, omit `RECEIVER_URL` or set it later.

Start the app from `creative/app` so Flask finds the templates:

```shell
cd creative/app
python main.py
```

Open http://127.0.0.1:5000 and sign in with `AUTH_USERNAME` / `AUTH_PASSWORD`.

The app imports without GCP. Listing surveys, saving surveys, and downloading responses need Application Default Credentials against the project above (`gcloud auth application-default login`).

# Google Cloud Shell

Cloud Shell **Web Preview** on port 5000 sits in front of Flask with its own login. Flask-BasicAuth then returns `401` on `GET /`, and the preview page reloads in a loop. For Cloud Shell only, disable basic auth and start as usual:

```shell
export DISABLE_BASIC_AUTH=1
cd creative/app
python main.py
```

Then use Web Preview → port 5000. You do not need `AUTH_USERNAME` / `AUTH_PASSWORD` in this mode.

Do **not** set `DISABLE_BASIC_AUTH` in App Engine, `app.yaml`, or `./deploy`. Production stays behind basic auth.

Homepage: archived surveys are hidden unless you click **Show archived**. Copy opens the new survey in the editor. The stats button and `/survey/reporting/...` are Brand Lift only. Preview does not write to BigQuery.

Status chips: **Active** up to 3 days since last response, **Stale** up to 7 days, **Timed out** after 7. (Previously Stale ran through 14 days.) Thresholds are `STATUS_ACTIVE_DAYS` / `STATUS_STALE_DAYS` in `creative/app/survey_service.py`.

The homepage paginates at 50 surveys, projects list fields only (no `custom_css`), and caches the BigQuery count query in-process for 90 seconds (`STATS_CACHE_SECONDS`). Each App Engine instance has its own cache; values can be up to that TTL stale. Count / last-response / status cells poll every 30s via htmx against that cache (polling pauses while the tab is hidden).

The admin UI is Bootstrap 5 (CDN) plus Alpine.js on the create/edit page. Style pickers write a `SONAR_THEME` block of CSS variables into `custom_css`; existing free-form CSS is kept in Advanced (CSS) and still used when zipping creatives. The live 300×250 preview is an iframe so it cannot strip page styles. Set an optional **Display name** to show a friendly label on the homepage (survey name still drives zip filenames).

Redeploy App Engine (`./deploy` or `gcloud app deploy`) to pick up these changes. No new Firestore index is required; archive filtering is done in the app (a missing `archived` field counts as active). Optional: `export GTAG_ID=AW-…` before `./deploy` if creatives should load gtag.js.

If `/index` fails with `Not found: Table …responses.responses` (a dataset without the table), create the table in the **same location as the dataset**. `./deploy` uses the location you pass as the second argument (for Mark's `brandometer2` project that was `us-central1`). From the repo root:

```shell
bq mk --table \
  --schema receiver/responses.schema.json \
  --description "Survey response rows for Sonar" \
  brandometer2:responses.responses
```

Or the equivalent inline schema (no repo file needed):

```shell
bq mk --table \
  --schema 'CreatedAt:DATETIME:REQUIRED,Type:STRING:REQUIRED,ID:STRING:REQUIRED,Segmentation:STRING:REQUIRED,Response:STRING:REQUIRED,Visual:STRING:REQUIRED,CreativeSize:STRING:REQUIRED,RandomTimeStamp:STRING:REQUIRED,BomID:STRING:REQUIRED' \
  brandometer2:responses.responses
```

Do not pass `--location` on `bq mk --table`; the table inherits `us-central1` from the existing `responses` dataset. Skip the command if `bq show brandometer2:responses.responses` already succeeds. The homepage also treats a missing table as zero responses, so `/index` still loads.

# Firestore Datastore mode

If the app fails with `The Cloud Firestore API is not available for Firestore in Datastore Mode database projects/…/databases/(default)`, App Engine (or an older `./deploy`) created `(default)` in **Datastore mode**. Sonar needs **Firestore Native**.

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
cd creative/app
PYTHONPATH=. pytest
```

# Receiver (Cloud Function)

Dependencies: `receiver/requirements.txt`. Deploy is handled by `./deploy` or the `gcloud functions deploy` command in [One-time GCP setup](#one-time-gcp-setup).
