#!/usr/bin/env python3
"""Copy responses.responses onto a DAY-partitioned table clustered by ID.

New deploys already `bq mk` the table with `--time_partitioning_field CreatedAt`.
Existing unpartitioned tables cannot be converted in place. This script copies
rows into a new partitioned table, swaps names, and keeps a backup.

Dry-run is the default. Mark runs `--apply` in Cloud Shell.

  python3 tools/migrate_responses_partition.py --project brandometer2
  python3 tools/migrate_responses_partition.py --project brandometer2 --apply
  python3 tools/migrate_responses_partition.py --project brandometer2 --check

`--check` exits 0 when the table is DAY-partitioned on CreatedAt, 2 when it
exists but is not, 3 when the table is missing.
"""
from __future__ import annotations

import argparse
import datetime
import sys

DEFAULT_PROJECT = 'brandometer2'
DATASET = 'responses'
TABLE = 'responses'
PARTITION_FIELD = 'CreatedAt'
CLUSTER_FIELDS = ('ID',)
BACKUP_PREFIX = 'responses_unpartitioned_backup_'
STAGING_PREFIX = 'responses_partitioned_'

CHECK_OK = 0
CHECK_UNPARTITIONED = 2
CHECK_MISSING = 3
CHECK_ERROR = 1


def table_id(project: str, name: str = TABLE) -> str:
  return '%s.%s.%s' % (project, DATASET, name)


def partition_info(table) -> dict:
  """Normalize google.cloud.bigquery.Table or a dict from `bq show`."""
  if table is None:
    return {'exists': False}
  if isinstance(table, dict):
    partitioning = table.get('timePartitioning') or {}
    clustering = table.get('clustering') or {}
    fields = clustering.get('fields') or table.get('clusteringFields') or []
    return {
        'exists': True,
        'partition_field': partitioning.get('field') or '',
        'partition_type': (partitioning.get('type') or '').upper(),
        'clustering_fields': list(fields),
    }
  partitioning = getattr(table, 'time_partitioning', None)
  clustering = getattr(table, 'clustering_fields', None) or []
  field = getattr(partitioning, 'field', None) if partitioning else None
  ptype = getattr(partitioning, 'type_', None) if partitioning else None
  if ptype is None:
    ptype = getattr(partitioning, 'type', None) if partitioning else None
  return {
      'exists': True,
      'partition_field': field or '',
      'partition_type': str(ptype or '').upper(),
      'clustering_fields': list(clustering),
  }


def is_day_partitioned_on_created_at(info: dict) -> bool:
  if not info.get('exists'):
    return False
  field = (info.get('partition_field') or '').strip()
  ptype = (info.get('partition_type') or '').upper()
  return field == PARTITION_FIELD and ptype in ('DAY', 'TIMEPARTITIONINGTYPE.DAY')


def is_clustered_by_id(info: dict) -> bool:
  fields = [str(item) for item in (info.get('clustering_fields') or [])]
  return fields[:1] == list(CLUSTER_FIELDS)


def stamp_for(now: datetime.datetime | None = None) -> str:
  when = now or datetime.datetime.now(datetime.timezone.utc)
  return when.strftime('%Y%m%d')


def plan_names(stamp: str) -> dict:
  return {
      'source': TABLE,
      'staging': STAGING_PREFIX + stamp,
      'backup': BACKUP_PREFIX + stamp,
  }


def copy_sql(project: str, source: str, dest: str) -> str:
  return 'INSERT INTO `%s` SELECT * FROM `%s`' % (
      table_id(project, dest), table_id(project, source))


def count_sql(project: str, name: str) -> str:
  return 'SELECT COUNT(*) AS n FROM `%s`' % table_id(project, name)


def rename_sql(project: str, current: str, new_name: str) -> str:
  return 'ALTER TABLE `%s` RENAME TO `%s`' % (
      table_id(project, current), new_name)


def instruction_lines(project: str) -> list[str]:
  return [
      'WARNING: %s is not DAY-partitioned on CreatedAt.' % table_id(project),
      'Deploy will not drop or recreate it. Migrate with:',
      '  python3 tools/migrate_responses_partition.py --project %s' % project,
      '  python3 tools/migrate_responses_partition.py --project %s --apply'
      % project,
  ]


def _bq_client(project: str):
  from google.cloud import bigquery
  return bigquery.Client(project=project)


def _get_table(client, project: str, name: str):
  from google.cloud.exceptions import NotFound
  try:
    return client.get_table(table_id(project, name))
  except NotFound:
    return None


def inspect_table(client, project: str, name: str = TABLE) -> dict:
  table = _get_table(client, project, name)
  info = partition_info(table)
  info['table'] = table
  return info


def create_partitioned_table(client, project: str, source_table, dest_name: str):
  from google.cloud import bigquery
  dest = bigquery.Table(table_id(project, dest_name), schema=source_table.schema)
  dest.time_partitioning = bigquery.TimePartitioning(
      type_=bigquery.TimePartitioningType.DAY,
      field=PARTITION_FIELD,
  )
  dest.clustering_fields = list(CLUSTER_FIELDS)
  dest.description = (
      source_table.description or 'Survey response rows for Brandometer2')
  return client.create_table(dest)


def _run_query(client, sql: str):
  job = client.query(sql)
  return job.result()


def _count(client, project: str, name: str) -> int:
  rows = list(_run_query(client, count_sql(project, name)))
  if not rows:
    return 0
  value = rows[0][0] if not hasattr(rows[0], 'n') else rows[0].n
  return int(value)


def migrate(client, project: str, stamp: str, apply: bool) -> dict:
  names = plan_names(stamp)
  info = inspect_table(client, project, TABLE)
  result = {
      'names': names,
      'source': info,
      'applied': False,
      'copied': 0,
  }
  if not info['exists']:
    result['status'] = 'missing'
    return result
  if is_day_partitioned_on_created_at(info):
    result['status'] = 'already_partitioned'
    return result
  staging_info = inspect_table(client, project, names['staging'])
  backup_info = inspect_table(client, project, names['backup'])
  if staging_info['exists'] or backup_info['exists']:
    result['status'] = 'name_collision'
    return result
  result['status'] = 'ready'
  result['copy_sql'] = copy_sql(project, names['source'], names['staging'])
  result['backup_sql'] = rename_sql(project, names['source'], names['backup'])
  result['promote_sql'] = rename_sql(
      project, names['staging'], names['source'])
  if not apply:
    return result
  create_partitioned_table(client, project, info['table'], names['staging'])
  _run_query(client, result['copy_sql'])
  source_n = _count(client, project, names['source'])
  dest_n = _count(client, project, names['staging'])
  result['copied'] = dest_n
  if source_n != dest_n:
    raise RuntimeError(
        'row count mismatch after copy: source=%s staging=%s'
        % (source_n, dest_n))
  _run_query(client, result['backup_sql'])
  _run_query(client, result['promote_sql'])
  result['applied'] = True
  result['status'] = 'migrated'
  return result


def check_exit_code(info: dict) -> int:
  if not info.get('exists'):
    return CHECK_MISSING
  if is_day_partitioned_on_created_at(info):
    return CHECK_OK
  return CHECK_UNPARTITIONED


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--project', default=DEFAULT_PROJECT)
  parser.add_argument('--apply', action='store_true')
  parser.add_argument(
      '--check', action='store_true',
      help='Exit 0 if DAY-partitioned on CreatedAt, 2 if not, 3 if missing.')
  parser.add_argument(
      '--stamp', default='',
      help='Override backup/staging suffix (default UTC YYYYMMDD).')
  args = parser.parse_args(argv)
  client = _bq_client(args.project)
  if args.check:
    info = inspect_table(client, args.project)
    code = check_exit_code(info)
    if code == CHECK_OK:
      extra = ''
      if not is_clustered_by_id(info):
        extra = ' (clustering is %s, expected ID)' % (
            info.get('clustering_fields') or [])
      print('Partitioned: %s DAY on %s%s' % (
          table_id(args.project), PARTITION_FIELD, extra))
    elif code == CHECK_MISSING:
      print('Missing: %s' % table_id(args.project))
    else:
      print('\n'.join(instruction_lines(args.project)))
    return code

  stamp = args.stamp or stamp_for()
  result = migrate(client, args.project, stamp, apply=False)
  print('Table %s' % table_id(args.project))
  if result['status'] == 'missing':
    print('Table is missing. ./deploy will create it partitioned.')
    return 0
  if result['status'] == 'already_partitioned':
    print('Already DAY-partitioned on CreatedAt. Nothing to do.')
    return 0
  if result['status'] == 'name_collision':
    print('error: staging or backup table already exists for stamp %s'
          % stamp, file=sys.stderr)
    print('  staging %s' % table_id(args.project, result['names']['staging']),
          file=sys.stderr)
    print('  backup  %s' % table_id(args.project, result['names']['backup']),
          file=sys.stderr)
    return CHECK_ERROR
  print('Plan (stamp %s):' % stamp)
  print('  1. CREATE %s PARTITION BY DATE(CreatedAt) CLUSTER BY ID'
        % table_id(args.project, result['names']['staging']))
  print('  2. %s' % result['copy_sql'])
  print('  3. %s' % result['backup_sql'])
  print('  4. %s' % result['promote_sql'])
  print('Backup remains as %s' % table_id(
      args.project, result['names']['backup']))
  if not args.apply:
    print('Dry run. Re-run with --apply to copy and swap.')
    return 0
  print('APPLY copy + rename swap')
  done = migrate(client, args.project, stamp, apply=True)
  print('Copied %s rows. Live table is now DAY-partitioned on CreatedAt.'
        % done['copied'])
  print('Backup: %s' % table_id(args.project, done['names']['backup']))
  return 0


if __name__ == '__main__':
  sys.exit(main())
