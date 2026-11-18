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

# Firestore (skip if (default) already exists)
gcloud firestore databases create --location=us-central1

# BigQuery dataset (the responses table is created on first receiver call)
bq --location=us-central1 mk --dataset --description "Main response data set for Sonar" "$PROJECT_ID:responses"

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

Export credentials and config (the homepage talks to Firestore + BigQuery; basic auth is always on):

```shell
export PROJECT_ID="your-gcp-project-id"
export TABLE_ID="$PROJECT_ID.responses.responses"
export AUTH_USERNAME="mark"
export AUTH_PASSWORD="choose-a-local-password"
# Optional. A dev default is used if unset; set a real value before any shared deploy.
# export SECRET_KEY="replace-me"
# Optional until the receiver function exists. Preview still works without it.
export RECEIVER_URL="$(gcloud functions describe receiver --gen2 --region=us-central1 --format='value(serviceConfig.uri)')"
```

If `gcloud functions describe` fails because the function is not deployed yet, omit `RECEIVER_URL` or set it later.

Start the app from `creative/app` so Flask finds the templates:

```shell
cd creative/app
python main.py
```

Open http://127.0.0.1:5000 and sign in with `AUTH_USERNAME` / `AUTH_PASSWORD`.

The app imports without GCP. Listing surveys, saving surveys, and downloading responses need Application Default Credentials against the project above (`gcloud auth application-default login`).

# Unit tests

GCP is not required. From the repo root:

```shell
source .venv/bin/activate
cd creative/app
PYTHONPATH=. pytest
```

# Receiver (Cloud Function)

Dependencies: `receiver/requirements.txt`. Deploy is handled by `./deploy` or the `gcloud functions deploy` command in [One-time GCP setup](#one-time-gcp-setup).
