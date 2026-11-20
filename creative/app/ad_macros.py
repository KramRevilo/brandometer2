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
"""Ad-server clickTag / cachebuster / ID macros baked into HTML5 creatives."""
import datetime
import io
import zipfile

import creative_size
from forms import BRAND_LIFT
from forms import BRAND_TRACK

DEFAULT_AD_SERVER = 'cm360'

PRESETS = {
    'cm360': {
        'id': 'cm360',
        'label': 'Campaign Manager 360',
        'click_tag': '%c',
        'cachebuster': '%n',
        'campaign': '',
        'placement': '%epid!',
        'site': '%esid!',
        'creative': '%ecid!',
        'user_id': '%u',
        'gdpr': '${GDPR}',
        'gdpr_consent': '${GDPR_CONSENT_XXXX}',
        'us_privacy': '${US_PRIVACY}',
        'overwrite_click_tag': False,
        'notes': (
            'Upload each inner HTML5 zip in CM360 (not the outer zip). '
            'Match placement dimensions to the size. Brand Lift: assign the '
            'default_control zip to Control and default_expose to Expose.'
        ),
    },
    'dv360': {
        'id': 'dv360',
        'label': 'Display & Video 360',
        'click_tag': '${CLICK_URL}',
        'cachebuster': '${CACHEBUSTER}',
        'campaign': '${CAMPAIGN_ID}',
        'placement': '${PLACEMENT_ID}',
        'site': '${SITE_ID}',
        'creative': '${CREATIVE_ID}',
        'user_id': '${USER_ID}',
        'gdpr': '${GDPR}',
        'gdpr_consent': '${GDPR_CONSENT_XXXX}',
        'us_privacy': '${US_PRIVACY}',
        'overwrite_click_tag': False,
        'notes': (
            'DV360 display HTML5 often still uploads through CM360. If this '
            'creative is assigned on a DV360 line item, macros expand at serve. '
            'Match the placement size. Brand Lift still needs Control vs Expose.'
        ),
    },
    'gam': {
        'id': 'gam',
        'label': 'Google Ad Manager',
        'click_tag': '%%CLICK_URL_UNESC%%',
        'cachebuster': '%%CACHEBUSTER%%',
        'campaign': '%%CAMPAIGN_ID%%',
        'placement': '%%PLACEMENT_ID%%',
        'site': '%%SITE%%',
        'creative': '%%CREATIVE_ID%%',
        'user_id': '%%USER_ID%%',
        'gdpr': '${GDPR}',
        'gdpr_consent': '${GDPR_CONSENT_XXXX}',
        'us_privacy': '%%US_PRIVACY%%',
        'overwrite_click_tag': False,
        'notes': (
            'GAM replaces %%macros%% at serve. Upload the inner zip as a '
            'custom HTML5 creative. Do not upload the outer zip.'
        ),
    },
    'generic': {
        'id': 'generic',
        'label': 'Generic / none',
        'click_tag': 'https://www.google.com',
        'cachebuster': '',
        'campaign': '',
        'placement': '',
        'site': '',
        'creative': '',
        'user_id': '',
        'gdpr': '',
        'gdpr_consent': '',
        'us_privacy': '',
        'overwrite_click_tag': True,
        'notes': (
            'No ad-server macros. clickTag stays a static URL. Prefer CM360 '
            'when trafficking through Campaign Manager.'
        ),
    },
}

CHOICES = [(key, PRESETS[key]['label']) for key in (
    'cm360', 'dv360', 'gam', 'generic')]

TAG_SHEET_HEADERS = (
    'survey_id',
    'survey_name',
    'display_name',
    'survey_type',
    'ad_server',
    'size',
    'segment',
    'inner_zip',
    'outer_zip',
    'campaign_id',
    'placement_id',
    'click_tag',
    'cachebuster',
    'campaign_macro',
    'placement_macro',
    'site_macro',
    'creative_macro',
    'user_id_macro',
    'gdpr_macro',
    'us_privacy_macro',
    'trafficking_notes',
)


def normalize_ad_server(value):
  key = (value or '').strip().lower()
  if key in PRESETS:
    return key
  return DEFAULT_AD_SERVER


def preset(survey=None):
  survey = survey or {}
  return PRESETS[normalize_ad_server(survey.get('ad_server'))]


def render_vars(survey=None):
  """Values injected into creative.html. Unexpanded macros stay as placeholders."""
  survey = survey or {}
  spec = preset(survey)
  click_tag = spec['click_tag']
  if spec['overwrite_click_tag']:
    click_tag = survey.get('exit_url') or spec['click_tag']
  user_candidates = []
  if spec.get('user_id'):
    user_candidates.append(spec['user_id'])
  for extra in ('%u', '${USER_ID}', '%%USER_ID%%'):
    if extra not in user_candidates:
      user_candidates.append(extra)
  return {
      'ad_server': spec['id'],
      'ad_server_label': spec['label'],
      'click_tag': click_tag,
      'cachebuster_macro': spec['cachebuster'],
      'campaign_macro': spec['campaign'],
      'placement_macro': spec['placement'],
      'site_macro': spec['site'],
      'creative_macro': spec['creative'],
      'gdpr_macro': spec['gdpr'],
      'gdpr_consent_macro': spec['gdpr_consent'],
      'us_privacy_macro': spec['us_privacy'],
      'overwrite_click_tag': spec['overwrite_click_tag'],
      'survey_campaign_id': (survey.get('campaign_id') or '').strip(),
      'survey_placement_id': (survey.get('placement_id') or '').strip(),
      'ad_user_id_candidates': user_candidates,
  }


def _segments(survey):
  if (survey.get('surveytype') or BRAND_TRACK) == BRAND_LIFT:
    return ['default_control', 'default_expose']
  return ['']


def tag_sheet_rows(survey_id, survey, when=None):
  """One row per inner zip (size × Brand Lift segment)."""
  survey = survey or {}
  spec = preset(survey)
  when = when or datetime.datetime.now()
  date_stamp = when.strftime('%Y%m%d')
  surveyname = (survey.get('surveyname') or 'survey').replace(' ', '-')
  sizes = creative_size.selected_keys(survey)
  outer = creative_size.outer_zip_basename(date_stamp, surveyname, sizes)
  survey_type = survey.get('surveytype') or BRAND_TRACK
  rows = []
  for size_key in sizes:
    for seg in _segments(survey):
      suffix = seg if seg else 'creative'
      inner = creative_size.inner_zip_basename(
          date_stamp, surveyname, size_key, suffix)
      rows.append({
          'survey_id': survey_id,
          'survey_name': survey.get('surveyname') or '',
          'display_name': survey.get('displayname') or '',
          'survey_type': survey_type,
          'ad_server': spec['id'],
          'size': size_key,
          'segment': seg or 'creative',
          'inner_zip': inner,
          'outer_zip': outer,
          'campaign_id': (survey.get('campaign_id') or '').strip(),
          'placement_id': (survey.get('placement_id') or '').strip(),
          'click_tag': spec['click_tag'],
          'cachebuster': spec['cachebuster'],
          'campaign_macro': spec['campaign'],
          'placement_macro': spec['placement'],
          'site_macro': spec['site'],
          'creative_macro': spec['creative'],
          'user_id_macro': spec['user_id'],
          'gdpr_macro': spec['gdpr'],
          'us_privacy_macro': spec['us_privacy'],
          'trafficking_notes': spec['notes'],
      })
  return rows


def tag_sheet_matrix(survey_id, survey, when=None):
  rows = tag_sheet_rows(survey_id, survey, when=when)
  body = []
  for row in rows:
    body.append([row.get(key, '') for key in TAG_SHEET_HEADERS])
  return list(TAG_SHEET_HEADERS), body


def csv_bytes(headers, rows):
  import csv
  buf = io.StringIO()
  writer = csv.writer(buf)
  writer.writerow(headers)
  writer.writerows(rows)
  return buf.getvalue().encode('utf-8-sig')


def xlsx_bytes(headers, rows, sheet_name='tag_sheet'):
  """Minimal Office Open XML workbook. No openpyxl dependency."""
  def xml_escape(value):
    text = '' if value is None else str(value)
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))

  def cell(ref, value):
    return (
        '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (
            ref, xml_escape(value)))

  def col_letter(index):
    n = index + 1
    letters = ''
    while n:
      n, rem = divmod(n - 1, 26)
      letters = chr(65 + rem) + letters
    return letters

  sheet_rows = []
  for r, values in enumerate([headers] + list(rows), start=1):
    cells = []
    for c, value in enumerate(values):
      cells.append(cell('%s%s' % (col_letter(c), r), value))
    sheet_rows.append('<row r="%s">%s</row>' % (r, ''.join(cells)))
  sheet = (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
      '<sheetData>%s</sheetData></worksheet>' % ''.join(sheet_rows))
  workbook = (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
      '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>'
      '</workbook>' % xml_escape(sheet_name[:31] or 'Sheet1'))
  workbook_rels = (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
      '</Relationships>')
  rels = (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
      '</Relationships>')
  ctypes = (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
      '</Types>')
  buf = io.BytesIO()
  with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('[Content_Types].xml', ctypes)
    zf.writestr('_rels/.rels', rels)
    zf.writestr('xl/workbook.xml', workbook)
    zf.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
    zf.writestr('xl/worksheets/sheet1.xml', sheet)
  return buf.getvalue()
