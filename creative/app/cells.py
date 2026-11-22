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
"""Survey cells: explicit control / expose / holdout / other roles.

Brand Lift zips one inner HTML5 per cell. Lift stats pool every control cell
against every expose cell. Extra expose cells are each compared to pooled
control with Holm across those cell-level tests. Holdout and other are stored
and excluded from lift (no holdout analysis).
"""
import json
import re

BRAND_LIFT = 'brand_lift'
BRAND_TRACK = 'brand_track'

ROLES = ('control', 'expose', 'holdout', 'other')
LIFT_ROLES = frozenset(('control', 'expose'))
CELL_ID_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
CELLS_JSON_KEY = 'cells_json'


def default_cells(survey_type):
  """Today's Brand Lift zips; Brand Track has no cells until the editor adds some."""
  if (survey_type or BRAND_TRACK) == BRAND_LIFT:
    return [
        {'id': 'default_control', 'label': 'Control', 'role': 'control'},
        {'id': 'default_expose', 'label': 'Exposed', 'role': 'expose'},
    ]
  return []


def normalize_cell(raw):
  if not isinstance(raw, dict):
    return None
  cell_id = str(raw.get('id') or '').strip()
  label = str(raw.get('label') or '').strip() or cell_id
  role = str(raw.get('role') or 'other').strip().lower()
  if role not in ROLES:
    role = 'other'
  if not cell_id:
    return None
  return {'id': cell_id, 'label': label, 'role': role}


def normalize(cells):
  out = []
  seen = set()
  for raw in cells or []:
    cell = normalize_cell(raw)
    if not cell or cell['id'] in seen:
      continue
    seen.add(cell['id'])
    out.append(cell)
  return out


def parse_json(raw):
  if raw in (None, ''):
    return []
  if isinstance(raw, list):
    return normalize(raw)
  text = str(raw).strip()
  if not text:
    return []
  try:
    parsed = json.loads(text)
  except (TypeError, ValueError, json.JSONDecodeError):
    raise ValueError('Cells JSON is not valid.')
  if not isinstance(parsed, list):
    raise ValueError('Cells JSON must be a list.')
  return normalize(parsed)


def dumps(cells):
  return json.dumps(normalize(cells), separators=(',', ':'))


def validate(cells, survey_type=None):
  """Return a list of error strings (empty means ok)."""
  errors = []
  cells = list(cells or [])
  ids = []
  for cell in cells:
    cell_id = cell.get('id') or ''
    if not CELL_ID_RE.match(cell_id):
      errors.append(
          'Cell id %r must match the pixel seg alphabet (letters, digits, '
          'underscore, dot, hyphen; 1–64 characters).' % cell_id)
    if cell_id in ids:
      errors.append('Cell id %r is duplicated.' % cell_id)
    ids.append(cell_id)
    if cell.get('role') not in ROLES:
      errors.append(
          'Cell %r has unknown role %r.' % (cell_id, cell.get('role')))
  if (survey_type or BRAND_TRACK) == BRAND_LIFT:
    if not any(c.get('role') == 'control' for c in cells):
      errors.append('Brand Lift needs at least one control cell.')
    if not any(c.get('role') == 'expose' for c in cells):
      errors.append('Brand Lift needs at least one expose cell.')
  return errors


def persist(payload):
  """Parse cells_json / cells onto a survey dict. Apply type defaults."""
  data = dict(payload or {})
  survey_type = data.get('surveytype') or BRAND_TRACK
  raw_json = data.pop(CELLS_JSON_KEY, None)
  if raw_json not in (None, ''):
    cells = parse_json(raw_json)
  else:
    cells = normalize(data.get('cells'))
  if not cells:
    cells = default_cells(survey_type)
  errors = validate(cells, survey_type)
  if errors:
    raise ValueError(errors[0])
  data['cells'] = cells
  return data


def zip_seg_ids(survey):
  """One inner-zip seg per cell; Brand Track with no cells is a single blank seg."""
  survey = survey or {}
  cells = normalize(survey.get('cells'))
  if cells:
    return [cell['id'] for cell in cells]
  return [cell['id'] for cell in default_cells(survey.get('surveytype'))] or ['']


def preview_cells(survey):
  cells = normalize((survey or {}).get('cells'))
  if cells:
    return cells
  return default_cells((survey or {}).get('surveytype'))


def resolve_preview_seg(survey, requested):
  """Requested cell id if it exists; otherwise the first cell or preview."""
  cells = preview_cells(survey)
  wanted = str(requested or '').strip()
  ids = [c['id'] for c in cells]
  if wanted and wanted in ids:
    return wanted
  if ids:
    return ids[0]
  return 'preview'


def role_for_seg(seg, cells=None):
  """Explicit cell role, else substring fallback used by surveys without cells.

  Holdout is returned as 'holdout' so lift pooling can exclude it. Unknown
  roles and unmatched segs become 'other'.
  """
  text = str(seg or '').strip()
  cells = normalize(cells)
  if cells:
    for cell in cells:
      if cell['id'] == text:
        return cell['role']
  lowered = text.lower()
  if 'control' in lowered:
    return 'control'
  if 'expos' in lowered:
    return 'expose'
  return 'other'


def lift_role(seg, cells=None):
  """control / expose, or other (holdout and extra cells are excluded from lift)."""
  role = role_for_seg(seg, cells)
  if role in LIFT_ROLES:
    return role
  return 'other'


def primary_cells(cells):
  """First control cell and first expose cell (defaults when cells are empty)."""
  cells = normalize(cells)
  control = next((c for c in cells if c['role'] == 'control'), None)
  expose = next((c for c in cells if c['role'] == 'expose'), None)
  extra_expose = [c for c in cells if c['role'] == 'expose'][1:]
  return control, expose, extra_expose
