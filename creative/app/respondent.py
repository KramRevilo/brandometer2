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
"""Survey-scoped respondent keys for one-person-one-response dedupe.

New rows store RespondentID (durable) plus BomID (same value in current
creatives). Existing rows have BomID only. The session key is
COALESCE(non-blank RespondentID, non-blank BomID, synthetic row:id).
"""
import pandas as pd

# BigQuery: numbered subquery must expose RespondentID, BomID, and row_id.
SESSION_KEY_SQL = (
    "IF(RespondentID IS NOT NULL AND TRIM(RespondentID) != '', "
    "TRIM(RespondentID), "
    "IF(BomID IS NOT NULL AND TRIM(BomID) != '', TRIM(BomID), "
    "CONCAT('row:', CAST(row_id AS STRING))))"
)

SOURCES = ('macro', 'storage', 'impression', 'bomid')


def session_keys(frame):
  """Stable per-respondent labels. Blank IDs become row:<index>."""
  if frame is None or frame.empty:
    return pd.Series(dtype=str)
  n = len(frame)
  blank = pd.Series([''] * n, index=frame.index, dtype=str)
  if 'RespondentID' in frame.columns:
    rid = frame['RespondentID'].fillna('').astype(str).str.strip()
  else:
    rid = blank
  if 'BomID' in frame.columns:
    bom = frame['BomID'].fillna('').astype(str).str.strip()
  else:
    bom = blank
  keys = rid.where(rid != '', bom)
  missing = keys == ''
  if missing.any():
    keys = keys.copy()
    keys.loc[missing] = [
        'row:%s' % idx for idx in frame.index[missing]
    ]
  return keys
