# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""CM360 / DV360 bulk-upload sidecar files (no API, no OAuth).

One row per inner HTML5 zip. Advertiser / account IDs are left blank for
Mark to fill in the ad-server UI. This module does not call Campaign
Manager or Display & Video 360 and does not store credentials.
"""
import io
import zipfile

import ad_macros
import creative_size

CM360_HEADERS = (
    'Advertiser ID',
    'Campaign ID',
    'Creative name',
    'Creative type',
    'Width',
    'Height',
    'HTML5 zip filename',
    'Click-through URL',
    'Backup image filename',
    'Segment',
    'Creative version',
    'Notes',
)

DV360_HEADERS = (
    'Advertiser ID',
    'Creative name',
    'Creative type',
    'Width',
    'Height',
    'Asset filename',
    'Landing page URL',
    'Segment',
    'Creative version',
    'Notes',
)

README_NAME = 'HOW_TO_UPLOAD.txt'
CM360_CSV_NAME = 'cm360_html5_bulk.csv'
DV360_CSV_NAME = 'dv360_html5_bulk.csv'

README_TEXT = """CM360 / DV360 bulk-upload files (no API)

These worksheets list every inner HTML5 zip in this package. They are
sidecar CSVs for the Campaign Manager 360 and Display & Video 360 UIs.
This app does not call the CM360 or DV360 APIs and does not store
OAuth client secrets or service-account keys.

Do not upload this file, html5_qa.txt, the outer zip, or these CSVs as
creatives. Upload each inner *.zip (index.html only).

1. Unzip the outer archive so the inner zips sit next to these CSVs.
2. Fill Advertiser ID (required by CM360/DV360) on every row. Campaign
   ID is copied from the survey Identity field when present; confirm it.
3. CM360: Creatives → New → Display → HTML5, or Bulk upload mapping
   "HTML5 zip filename" to the inner zip on the same row. Brand Lift:
   assign default_control to the Control audience and default_expose to
   Expose. Both files are the same survey labelled by seg — not a PSA.
4. DV360 display HTML5 is often still uploaded through CM360, then
   assigned to a line item. If you use the DV360 creative bulk editor,
   map "Asset filename" the same way. Match placement dimensions.
5. Click-through / landing page: CM360 clickTag is typically %%c (filled
   at serve). Set the landing page in the ad server if the CSV cell is
   blank. Do not traffic the measurement pixel as a click-through.
6. Re-download this sheet when you re-download zips (filenames include
   the date; ver= on the pixel is the zip snapshot).

Stopped here: no OAuth, no API client, no credential fields in the app.
A later cost/impressions join (BigQuery Data Transfer) is a separate
piece of work and is not these files.
""".replace('%%c', '%c')


def _size_wh(size_key):
  spec = creative_size.resolve(size_key)
  return spec['width'], spec['height']


def _creative_name(row):
  name = (row.get('survey_name') or 'survey').replace(' ', '-')
  size = row.get('size') or ''
  segment = row.get('segment') or 'creative'
  return '%s_%s_%s' % (name, size, segment)


def _landing_page(row, survey):
  survey = survey or {}
  exit_url = (survey.get('exit_url') or '').strip()
  if exit_url:
    return exit_url
  click = (row.get('click_tag') or '').strip()
  if click.startswith('http://') or click.startswith('https://'):
    return click
  return ''


def _notes(row):
  extra = (
      'Fill Advertiser ID. Upload the inner zip named in this row; '
      'do not upload the outer archive.')
  existing = (row.get('trafficking_notes') or '').strip()
  if existing:
    return existing + ' ' + extra
  return extra


def cm360_rows(tag_rows, survey=None):
  """One CM360 bulk-upload row per inner zip. Advertiser ID is blank."""
  out = []
  for row in tag_rows or []:
    width, height = _size_wh(row.get('size'))
    out.append([
        '',
        row.get('campaign_id') or '',
        _creative_name(row),
        'Display HTML5',
        str(width),
        str(height),
        row.get('inner_zip') or '',
        _landing_page(row, survey),
        '',
        row.get('segment') or '',
        row.get('creative_version') or '',
        _notes(row),
    ])
  return out


def dv360_rows(tag_rows, survey=None):
  """One DV360 bulk-editor row per inner zip. Advertiser ID is blank."""
  out = []
  for row in tag_rows or []:
    width, height = _size_wh(row.get('size'))
    out.append([
        '',
        _creative_name(row),
        'HTML5',
        str(width),
        str(height),
        row.get('inner_zip') or '',
        _landing_page(row, survey),
        row.get('segment') or '',
        row.get('creative_version') or '',
        _notes(row),
    ])
  return out


def sidecar_files(survey_id, survey, when=None, creative_version=None):
  """(filename, bytes) pairs to drop next to the inner zips."""
  tag_rows = ad_macros.tag_sheet_rows(
      survey_id, survey, when=when, creative_version=creative_version)
  cm_csv = ad_macros.csv_bytes(CM360_HEADERS, cm360_rows(tag_rows, survey))
  dv_csv = ad_macros.csv_bytes(DV360_HEADERS, dv360_rows(tag_rows, survey))
  return [
      (README_NAME, README_TEXT.encode('utf-8')),
      (CM360_CSV_NAME, cm_csv),
      (DV360_CSV_NAME, dv_csv),
  ]


def download_zip(survey_id, survey, when=None, creative_version=None):
  """Standalone zip of the sidecar CSVs + readme (no HTML5 creatives)."""
  buf = io.BytesIO()
  with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
    for name, content in sidecar_files(
        survey_id, survey, when=when, creative_version=creative_version):
      zf.writestr(name, content)
  buf.seek(0)
  slug = (survey.get('surveyname') or survey_id or 'survey').replace(' ', '-')
  return '%s_bulk_upload.zip' % slug, buf.getvalue()
