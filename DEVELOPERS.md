# Brandometer developer guide

Brandometer is a Flask + Google Cloud app (App Engine, Firestore, BigQuery, Cloud Functions) for building brand-lift / brand-track survey creatives. It started as a fork of Google Brandometer (Apache-2.0). The product name is `APP_BRAND_NAME` (default **Brandometer**). Internal CSS markers stay `SONAR_THEME_*` / `--sonar-*` / `SONAR_SIZE_*` so existing `custom_css` still parses.

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
bq --location=us-central1 mk --dataset --description "Main response data set for Brandometer" "$PROJECT_ID:responses"
bq mk --table \
  --schema receiver/responses.schema.json \
  --time_partitioning_field CreatedAt \
  --time_partitioning_type DAY \
  --clustering_fields ID \
  --description "Survey response rows for Brandometer" \
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

Open http://127.0.0.1:8080 and sign in with `AUTH_USERNAME` / `AUTH_PASSWORD`.

The app imports without GCP. Listing surveys, saving surveys, and downloading responses need Application Default Credentials against the project above (`gcloud auth application-default login`).

# Google Cloud Shell

Cloud Shell **Web Preview** sits in front of Flask with its own login, and it is stuck on port **8080**. Flask-BasicAuth then returns `401` on `GET /`, and the preview page reloads in a loop. For Cloud Shell only, disable basic auth and bind 8080:

```shell
export DISABLE_BASIC_AUTH=1
cd creative/app
flask --app main run --port 8080 --debug
```

Then use Web Preview → port 8080. You do not need `AUTH_USERNAME` / `AUTH_PASSWORD` in this mode.

Do **not** set `DISABLE_BASIC_AUTH` in App Engine, `app.yaml`, or `./deploy`. Production stays behind basic auth.

Homepage: archived surveys are hidden unless you click **Show archived**. Copy opens the new survey in the editor. The stats button and `/survey/reporting/...` work for **Brand Lift and Brand Track**. Preview does not write to BigQuery (empty `receiver_url`); generate test rows with curl against the receiver as in [Generate test responses](#generate-test-responses).

**Counts treat each BomID as one respondent** (latest, most complete cumulative `Response`). Surveys set to submit after each question used to be counted once per question; those homepage and report numbers will drop. Submit-at-end rows with a blank BomID stay as individual respondents.

Reporting (parameterized `WHERE ID = @survey_id`):

* Daily responses by stored `seg` (Chart.js CDN)
* Per-question answer distributions
* Brand Lift only: control vs exposed table, Wilson 95% CIs, two-proportion z-test p-value, n-too-small warning when an arm has fewer than 30 respondents
* Empty states when there is no data, no control, or no exposed segment
* CSV downloads stream in chunks after the same consolidation (not one in-memory string)

Segment roles come from the stored `seg` value (`control` / `expos` in the string). Creatives still zip as `default_control` / `default_expose` for Brand Lift.

Status chips: **Active** up to 3 days since last response, **Stale** up to 7 days, **Timed out** after 7. (Previously Stale ran through 14 days.) Thresholds are `STATUS_ACTIVE_DAYS` / `STATUS_STALE_DAYS` in `creative/app/survey_service.py`.

The homepage paginates at 50 surveys and projects list fields only (no `custom_css`; includes `client`, `agency`, `created_at`, `creativesize`, `creativesizes`). **GET `/index` does not call BigQuery.** Count / last-response / status cells render as `Loading…` and load from `/index/stats-partial` via htmx `hx-trigger="load, every 30s [!document.hidden]"` (the previous `every 30s` trigger never ran before first paint, so the list waited on BQ). The stats query is limited to the survey IDs on the current page (`ID IN UNNEST(@survey_ids)`) plus a `CreatedAt` partition window (`STATS_LOOKBACK_DAYS`, default 400). Results are cached in-process **per survey ID** for 90 seconds (`STATS_CACHE_SECONDS`). Each App Engine instance has its own cache; values can be up to that TTL stale. Debug logs: `index.firestore_list_ms`, `index.filter_ms`, `index.render_ms`, `index.request_ms`, `index.stats_partial_ms`, `stats.bq_ms` (`cache=hit|miss|skip`).

Homepage filters (`q`, `client`, `agency`, `year`, `size`) are query params, applied in Python after the list `select()`, and are kept on pagination and the archive toggle. A survey matches the size filter if that size is in its configured list (legacy docs with no size field match **300×250**). The **Sizes** column shows those keys as chips. Year **Unknown** is for old documents with no `created_at`. Optional **Client** and **Agency** on the editor (datalist of existing values) copy with the survey. `created_at` is set on create and copy. Optional **Campaign ID** / **Placement ID** are placeholders for a future cost join; they are not used in reporting yet.

**View Survey.** Single-size rows keep a plain eye button (no `?size=`). Multi-size rows use a split button: the main control opens the first configured size; the caret lists every size as `/survey/preview/<id>?size=WxH`. The preview page itself has a size switcher when there is more than one size, defaulting to the first configured key. Unknown `?size=` falls back to that first key.

The admin UI is Bootstrap 5 (CDN) plus Alpine.js on the create/edit page. Style pickers write a `SONAR_THEME` block of CSS variables into `custom_css`; existing free-form CSS is kept in Advanced (CSS) and still used when zipping creatives. **Presets** are a grouped dropdown (Classic / Loud solids / Complementary / Patterns); Classic green is the default. Patterns are CSS gradients only, with a solid panel behind question and answer text. The live preview iframe resizes to the previewed **creative size** and has a size switcher when more than one size is selected. Set an optional **Display name** to show a friendly label on the homepage (survey name still drives zip filenames).

**Creative sizes.** 300×250 (default for old docs), 160×600, 300×600, 336×280, 970×250. Not 728×90 / 320×50 / 320×100. Stored as `creativesizes` (list) plus `creativesize` (single string when there is one size, otherwise the list) so old docs still load. 970×250 lays answers out in a wrapping grid. Download is an **outer ZIP** of one HTML5 inner ZIP per size (and per Brand Lift segment: `default_control` / `default_expose`). Inner ZIPs contain only `index.html` (never a nested zip), `ad.size` for that size, filename ≤ 50 characters, well under 5 MB. clickTag/exit is unchanged.

**Answers.** 2–5 answers on 300×250 / 336×280 / 970×250; up to 8 (a–h) when **every** selected size is 160×600 or 300×600. Empty rows are skipped. Answer text wraps (always-injected layout CSS overrides old `.AText { height: 27px }` in stored `custom_css`). Reporting and the receiver treat `1:F` the same as `1:A` (Response is a string).

**Ad badge.** Every creative and the preview has a bottom-left disclosure badge. Default icon is the bevelled **B** (first letter of `APP_BRAND_NAME`, overridable with `APP_BRAND_BADGE_LETTER`). Per-survey **Disclosure badge** on create/edit picks **B**, **B2**, **Ad**, or **Dentsu** (plain-text wordmark in the same bevelled pill; not Dentsu’s official logo). Stored as `badge_icon` / `badge_text`. Blank or missing fields behave as the default tooltip `Survey Type {brand} Ad - powered by Google` (`APP_BRAND_BADGE_TOOLTIP` to override the default string). Popup text is max 120 characters and HTML-escaped. Hover / focus / tap still show the tooltip; it does not fire clickTag. Copy and zip version snapshots keep the fields. Add more faces in `brand.BADGE_ICONS` (reserved `svg` for an uploaded logo).

**Brand.** `export APP_BRAND_NAME=Brandometer` (that is the default). Navbar, page titles, and the badge letter/tooltip use it.

**Version history.** Each zip download writes an immutable snapshot to the Firestore subcollection `Surveys/{id}/versions/{n}` (questions, CSS, size, type, timestamp, version number). The edit page lists them with **Download this version**. Editing the live survey does not change past snapshots. No GCS. No new index.

Redeploy **App Engine** (`./deploy` or `gcloud app deploy creative/app`) to pick up size, variable answers, versioning, and reporting. No new Firestore index is required; archive filtering and version listing are done in the app. Optional: `export GTAG_ID=AW-…` before `./deploy` if creatives should load gtag.js.

**Receiver redeploy is not required for Phase 4.** Creatives already post `creative_size={width}x{height}` from `ui_config`; once App Engine serves sized HTML, new rows get `300x250` or `160x600`. The optional `Type=survey` default from Phase 3 still only needs a receiver redeploy if you want that default.

```shell
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
  --schema 'CreatedAt:DATETIME:REQUIRED,Type:STRING:REQUIRED,ID:STRING:REQUIRED,Segmentation:STRING:REQUIRED,Response:STRING:REQUIRED,Visual:STRING:REQUIRED,CreativeSize:STRING:REQUIRED,RandomTimeStamp:STRING:REQUIRED,BomID:STRING:REQUIRED' \
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
cd creative/app
PYTHONPATH=. pytest
```

# Receiver (Cloud Function)

Dependencies: `receiver/requirements.txt`. Deploy is handled by `./deploy` or the `gcloud functions deploy` command in [One-time GCP setup](#one-time-gcp-setup).

The receiver writes `Type` (default `survey`), `ID`, `Segmentation` (`seg`), `Response`, `BomID` (`bomid`), and the other REQUIRED schema fields. Live creatives post here; **preview does not**.

# Generate test responses

Preview never posts (`receiver_url` is empty). To see homepage counts, reporting, and CSV, `curl` the live receiver. Schema fields are REQUIRED — send dummy `visual` / `creative_size` even if unused.

```shell
export PROJECT_ID="your-gcp-project-id"
export RECEIVER_URL="$(gcloud functions describe receiver --gen2 --region=us-central1 --format='value(serviceConfig.uri)')"
# Firestore document id from the homepage Survey ID column
SURVEY_ID="paste-survey-id"

post() {
  # $1=seg  $2=response  $3=bomid
  curl -sS -G "$RECEIVER_URL" \
    --data-urlencode "type=survey" \
    --data-urlencode "id=$SURVEY_ID" \
    --data-urlencode "seg=$1" \
    --data-urlencode "response=$2" \
    --data-urlencode "visual=none" \
    --data-urlencode "creative_size=${4:-300x250}" \
    --data-urlencode "bomid=$3"
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

A successful insert returns `{"errors": []}`. Streaming inserts can take a few seconds to show up in `SELECT`. Homepage counts are cached up to 90 seconds (`STATS_CACHE_SECONDS`; set `0` while testing). Reporting and CSV query BigQuery on each request.

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
5. Open stats: daily chart, distributions; Lift also has control vs exposed, Wilson CIs, p-values, and a small-n warning until each arm has 30 respondents. Empty surveys show “No responses yet”.
6. Download CSV: one row per BomID; streaming (not a single buffered string).
7. Optional: `bq query --nouse_legacy_sql "SELECT BomID, Response FROM \`$TABLE_ID\` WHERE ID='$SURVEY_ID' ORDER BY CreatedAt"` to compare raw vs consolidated.

Redeploy App Engine before this is live in production. Receiver redeploy is only for the `Type` default.

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

Join: each BOM cut is usually one CM placement (and one DV360 line item). **Placement ID** is the precise key; **campaign ID** is enough only when a survey maps 1:1 to a campaign. Both optional fields are on Identity now so surveys can be tagged before a dashboard exists. They are not read by reporting or the receiver.

Effort: the dashboard (join quality, unmatched IDs, currency, a cost table next to Brand Lift) is a later phase of its own. A sheet upload is the smaller stopgap. The Data Transfer path is larger but is what you want if this will be used weekly. Redeploy is not required for the placeholder ID fields until you want them in production editor.

# Cloud Shell test (Phase 5)

Same start as Phase 3 (`DISABLE_BASIC_AUTH=1`, then from `creative/app`: `flask --app main run --port 8080 --debug`). Web Preview → port 8080.

1. **Identity.** Create survey: Client, Agency, Campaign ID, Placement ID in Identity. Type a client used on another survey and confirm the datalist suggests it. Save. Homepage row shows `Client · Agency` under the name.
2. **Copy.** Copy that survey. Editor should still have the same client/agency/IDs. `created_at` on the copy is now (old docs without a timestamp stay year **Unknown**).
3. **Filters.** Homepage: filter by client, agency, year, size, and a name search. Combine with **Show archived**. Next/Previous should keep the query params. Clear returns to the unfiltered list (archive toggle unchanged). The Sizes column shows chips (legacy rows show 300×250).
4. **Old surveys.** A document with no `created_at` appears under Year → Unknown and still lists if you do not filter by year.

# Cloud Shell test (Phase 6)

Same start (`DISABLE_BASIC_AUTH=1`, `cd creative/app`, `flask --app main run --port 8080 --debug`). Web Preview → port 8080.

1. Navbar says **Brandometer** (or `APP_BRAND_NAME`). Create survey: check **300×250** and **970×250**. Editor preview switcher appears; 970×250 is wide with answers in a grid. Check only **160×600** and **Add answer** through H. Checking 300×250 as well should drop F–H on save (validation).
2. Homepage: that two-size survey has Sizes chips and a View split button. Pick **970×250** from the caret (`?size=970x250`). The preview page size switcher highlights 970×250. A one-size survey still has a plain View button and no preview switcher. Filter Size = 970×250 hides surveys that do not include it; combine with page 2 / Show archived.
3. Theme preset dropdown: Classic green first; groups Classic / Loud solids / Complementary / Patterns. Hazard stripes should show a striped background with readable answer panels.
4. Download zip with two sizes: outer zip contains two inner zips; each inner has only `index.html`, `ad.size` matching that size, a **B** badge bottom-left. Hover/tap the badge for the tooltip. Inner filenames ≤ 50 chars.
5. **Disclosure badge.** Create survey: Icon picker shows B / B2 / Ad / Dentsu. Default B looks like the current bevelled letter. Pick **Dentsu** and 160×600 — the wordmark is a small pill, not overlapping answers. Change popup text; preview updates immediately. **Use default** restores the `Survey Type Brandometer Ad - powered by Google` string. Leave text blank and save — creative still uses that default. Copy the survey; badge choices come along.
6. Homepage speed: the survey table should appear immediately with **Loading…** in count/last/status; those cells fill in after `/index/stats-partial` (check Network: `/index` returns before the stats request). Flask debug log lines `index.request_ms` (bq=deferred) and `stats.bq_ms`.
7. Trafficking: in CM360, **Upload HTML5** (batch) the inner zips, one placement per size. Assign Brand Lift control/expose creatives to the matching audience ads. Do not upload the outer zip as a creative. Match placement dimensions to 300×250 / 160×600 / 300×600 / 336×280 / 970×250. Preview still does not post to BigQuery.

# CM360 batch upload (Phase 6)

1. Download the survey zip from the homepage.
2. Unzip the **outer** archive on your machine. You should see one `.zip` per size (Brand Lift: two per size, `default_control` and `default_expose`).
3. In Campaign Manager 360 → Creatives → **New** → **Display** → upload each **inner** zip as HTML5. The `ad.size` meta inside `index.html` must match the placement.
4. Do not put a zip inside a zip when uploading; each inner file is already a legal HTML5 creative (`index.html` only).
5. Brand Lift: assign `…_default_control.zip` to the Control ad and `…_default_expose.zip` to the Expose ad, same as before.

Redeploy **App Engine** for Phase 6. Receiver redeploy is not required (`Response` already stores `1:H`). Optional env: `APP_BRAND_NAME`, `APP_BRAND_BADGE_LETTER`, `APP_BRAND_BADGE_TOOLTIP`.
