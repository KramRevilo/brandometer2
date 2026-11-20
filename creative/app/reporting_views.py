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
"""SQL for the reporting dataset (authorized views for Looker Studio)."""
import os
import sys
from urllib.parse import urlencode

import respondent

REPORTING_DATASET = 'brandometer_reporting'
DEDUPED_VIEW = 'deduped_responses'
SUMMARY_VIEW = 'survey_summaries'


def looker_studio_url(project_id, table_id=DEDUPED_VIEW):
  """Linking API URL that opens a new report on the authorized view."""
  project_id = (project_id or '').strip()
  if not project_id:
    return ''
  query = urlencode({
      'c.mode': 'edit',
      'ds.ds0.connector': 'bigQuery',
      'ds.ds0.type': 'TABLE',
      'ds.ds0.projectId': project_id,
      'ds.ds0.datasetId': REPORTING_DATASET,
      'ds.ds0.tableId': table_id,
  })
  return 'https://lookerstudio.google.com/reporting/create?' + query


def deduped_view_sql(project_id):
  project_id = (project_id or '').strip()
  source = '`%s.responses.responses`' % project_id
  view = '`%s.%s.%s`' % (project_id, REPORTING_DATASET, DEDUPED_VIEW)
  return """CREATE OR REPLACE VIEW %s AS
WITH numbered AS (
  SELECT
    ID AS survey_id,
    Segmentation,
    CreatedAt,
    Response,
    BomID,
    RespondentID,
    RespondentIDSource,
    CampaignID,
    PlacementID,
    SiteID,
    AdCreativeID,
    CreativeSize,
    CreativeVersion,
    ARRAY_LENGTH(REGEXP_EXTRACT_ALL(IFNULL(Response, ''), r'[1-5]:[^|]+')) AS n_answers,
    ROW_NUMBER() OVER () AS row_id
  FROM %s
),
keyed AS (
  SELECT
    *,
    %s AS respondent_key
  FROM numbered
)
SELECT
  survey_id,
  respondent_key,
  Segmentation,
  CreatedAt,
  Response,
  BomID,
  RespondentID,
  RespondentIDSource,
  CampaignID,
  PlacementID,
  SiteID,
  AdCreativeID,
  CreativeSize,
  CreativeVersion
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY survey_id, respondent_key
      ORDER BY n_answers DESC, CreatedAt DESC
    ) AS rn
  FROM keyed
)
WHERE rn = 1
""" % (view, source, respondent.SESSION_KEY_SQL)


def summary_view_sql(project_id):
  project_id = (project_id or '').strip()
  deduped = '`%s.%s.%s`' % (project_id, REPORTING_DATASET, DEDUPED_VIEW)
  view = '`%s.%s.%s`' % (project_id, REPORTING_DATASET, SUMMARY_VIEW)
  return """CREATE OR REPLACE VIEW %s AS
SELECT
  survey_id,
  Segmentation,
  COUNT(*) AS respondents,
  MIN(CreatedAt) AS first_response,
  MAX(CreatedAt) AS last_response,
  MIN(CreativeVersion) AS first_creative_version,
  MAX(CreativeVersion) AS last_creative_version
FROM %s
GROUP BY survey_id, Segmentation
""" % (view, deduped)


def all_view_sql(project_id):
  return deduped_view_sql(project_id).rstrip() + ';\n\n' + summary_view_sql(
      project_id).rstrip() + ';\n'


def main(argv):
  if len(argv) < 2:
    sys.stderr.write(
        'Usage: reporting_views.py sql|deduped|summary|looker PROJECT_ID\n')
    return 2
  cmd = argv[1]
  project_id = argv[2] if len(argv) > 2 else os.environ.get('PROJECT_ID', '')
  if cmd == 'sql':
    sys.stdout.write(all_view_sql(project_id))
    return 0
  if cmd == 'deduped':
    sys.stdout.write(deduped_view_sql(project_id).rstrip() + ';\n')
    return 0
  if cmd == 'summary':
    sys.stdout.write(summary_view_sql(project_id).rstrip() + ';\n')
    return 0
  if cmd == 'looker':
    sys.stdout.write(looker_studio_url(project_id) + '\n')
    return 0
  sys.stderr.write('Unknown command %s\n' % cmd)
  return 2


if __name__ == '__main__':
  sys.exit(main(sys.argv))
