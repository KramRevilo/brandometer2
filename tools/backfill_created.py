#!/usr/bin/env python3
"""Fill missing Surveys.created_at / created_by from AuditLog create/copy rows.

Dry-run by default. Never overwrites a field that is already set.

  python3 tools/backfill_created.py --project brandometer2
  python3 tools/backfill_created.py --project brandometer2 --apply

Must run with Application Default Credentials that can read AuditLog and
read/write Surveys (Cloud Shell on the brandometer2 project).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'creative' / 'app'


def _prepare_env(project: str | None) -> None:
  if project:
    os.environ['GOOGLE_CLOUD_PROJECT'] = project
    os.environ.setdefault('PROJECT_ID', project)
  sys.path.insert(0, str(APP_DIR))


def _iso(value) -> str:
  if value is None or value == '':
    return ''
  if hasattr(value, 'rfc3339') and callable(value.rfc3339):
    text = value.rfc3339()
    return text.replace('+00:00', 'Z') if text.endswith('+00:00') else text
  iso = getattr(value, 'isoformat', None)
  if callable(iso):
    text = iso()
    if text.endswith('+00:00'):
      return text[:-6] + 'Z'
    return text
  text = str(value).strip()
  if text.endswith('+00:00'):
    return text[:-6] + 'Z'
  return text


def _missing(value) -> bool:
  return value is None or str(value).strip() == ''


def propose_patches(surveys, audits):
  """surveys: {id: dict}, audits: list of audit dicts.

  Copy events store the new survey id in detail and the source in survey_id.
  """
  events = []
  for row in audits or []:
    action = (row.get('action') or '').strip()
    actor = (row.get('actor') or '').strip()
    when = _iso(row.get('created_at'))
    if action == 'create':
      target = (row.get('survey_id') or '').strip()
    elif action == 'copy':
      target = (row.get('detail') or '').strip()
    else:
      continue
    if not target:
      continue
    events.append((when, target, actor, action))
  events.sort(key=lambda item: item[0] or '')

  patches = []
  for when, survey_id, actor, action in events:
    data = surveys.get(survey_id)
    if data is None:
      continue
    patch = {}
    if _missing(data.get('created_at')) and when:
      patch['created_at'] = when
    if _missing(data.get('created_by')) and actor:
      patch['created_by'] = actor
    if not patch:
      continue
    merged = dict(data)
    merged.update(patch)
    surveys[survey_id] = merged
    patches.append({
        'survey_id': survey_id,
        'action': action,
        'patch': patch,
    })
  return patches


def load_surveys(db):
  out = {}
  for doc in db.collection('Surveys').stream():
    data = doc.to_dict() or {}
    data['id'] = doc.id
    out[doc.id] = data
  return out


def load_audits(db):
  rows = []
  for doc in db.collection('AuditLog').stream():
    data = doc.to_dict() or {}
    data['id'] = doc.id
    rows.append(data)
  return rows


def apply_patches(db, patches):
  written = 0
  for item in patches:
    ref = db.collection('Surveys').document(item['survey_id'])
    snap = ref.get()
    if not getattr(snap, 'exists', False):
      continue
    current = snap.to_dict() or {}
    payload = {}
    for field, value in item['patch'].items():
      if _missing(current.get(field)):
        payload[field] = value
    if not payload:
      continue
    ref.update(payload)
    written += 1
  return written


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      '--project', default=os.environ.get('PROJECT_ID') or os.environ.get(
          'GOOGLE_CLOUD_PROJECT') or 'brandometer2',
      help='GCP project id (default brandometer2)')
  parser.add_argument(
      '--apply', action='store_true',
      help='Write patches. Default is a dry run that only prints.')
  args = parser.parse_args(argv)
  _prepare_env(args.project)
  from google.cloud import firestore
  db = firestore.Client(project=args.project)
  surveys = load_surveys(db)
  audits = load_audits(db)
  missing = [
      sid for sid, data in surveys.items()
      if _missing(data.get('created_at')) or _missing(data.get('created_by'))
  ]
  patches = propose_patches(surveys, audits)
  print('Project %s' % args.project)
  print('Surveys %d · missing created fields %d · AuditLog rows %d' % (
      len(surveys), len(missing), len(audits)))
  print('Patches %d' % len(patches))
  for item in patches:
    print('  %s (%s) -> %s' % (
        item['survey_id'], item['action'], item['patch']))
  unresolved = [
      sid for sid, data in surveys.items()
      if _missing(data.get('created_at')) or _missing(data.get('created_by'))
  ]
  if unresolved:
    print('Still Unknown after AuditLog (%d): %s' % (
        len(unresolved), ', '.join(sorted(unresolved)[:20])))
    if len(unresolved) > 20:
      print('  … and %d more' % (len(unresolved) - 20))
  if not args.apply:
    print('Dry run. Re-run with --apply to write.')
    return 0
  written = apply_patches(db, patches)
  print('Wrote %d survey documents.' % written)
  return 0


if __name__ == '__main__':
  sys.exit(main())
