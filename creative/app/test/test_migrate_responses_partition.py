# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for tools/migrate_responses_partition.py."""
import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from google.cloud.exceptions import NotFound

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def _load():
  path = os.path.join(_ROOT, 'tools', 'migrate_responses_partition.py')
  spec = importlib.util.spec_from_file_location(
      'migrate_responses_partition', path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class FakeTable:
  def __init__(self, field=None, ptype=None, clustering=None, description=''):
    self.schema = ('schema',)
    self.description = description
    if field:
      self.time_partitioning = mock.Mock(field=field, type_=ptype or 'DAY')
    else:
      self.time_partitioning = None
    self.clustering_fields = clustering or []


class MigrateResponsesPartitionTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.mod = _load()

  def _client(self, live, extras=None):
    extras = extras or {}

    def get_table(tid):
      if tid in extras:
        return extras[tid]
      if tid == 'brandometer2.responses.responses':
        return live
      raise NotFound('missing')

    client = mock.Mock()
    client.get_table.side_effect = get_table
    return client

  def test_partition_info_from_bq_show_dict(self):
    info = self.mod.partition_info({
        'timePartitioning': {'type': 'DAY', 'field': 'CreatedAt'},
        'clustering': {'fields': ['ID']},
    })
    self.assertTrue(self.mod.is_day_partitioned_on_created_at(info))
    self.assertTrue(self.mod.is_clustered_by_id(info))

  def test_unpartitioned_table_is_detected(self):
    info = self.mod.partition_info({'schema': []})
    self.assertTrue(info['exists'])
    self.assertFalse(self.mod.is_day_partitioned_on_created_at(info))
    self.assertEqual(self.mod.check_exit_code(info), self.mod.CHECK_UNPARTITIONED)

  def test_missing_table_check_code(self):
    self.assertEqual(
        self.mod.check_exit_code({'exists': False}), self.mod.CHECK_MISSING)

  def test_plan_sql_uses_created_at_and_keeps_backup(self):
    names = self.mod.plan_names('20261122')
    self.assertEqual(names['backup'], 'responses_unpartitioned_backup_20261122')
    self.assertEqual(names['staging'], 'responses_partitioned_20261122')
    copy = self.mod.copy_sql('brandometer2', names['source'], names['staging'])
    self.assertIn(
        'INSERT INTO `brandometer2.responses.responses_partitioned_20261122`',
        copy)
    self.assertIn('SELECT * FROM `brandometer2.responses.responses`', copy)
    backup = self.mod.rename_sql('brandometer2', 'responses', names['backup'])
    self.assertIn('RENAME TO `responses_unpartitioned_backup_20261122`', backup)

  def test_dry_run_does_not_write(self):
    client = self._client(FakeTable())
    result = self.mod.migrate(client, 'brandometer2', '20261122', apply=False)
    self.assertEqual(result['status'], 'ready')
    self.assertFalse(result['applied'])
    client.create_table.assert_not_called()
    client.query.assert_not_called()

  def test_apply_copies_then_swaps(self):
    client = self._client(FakeTable(description='old'))

    class CountResult(list):
      def __init__(self, n):
        super().__init__([(n,)])

    def query(sql):
      job = mock.Mock()
      job.result.return_value = (
          CountResult(41) if sql.startswith('SELECT COUNT') else [])
      return job

    client.query.side_effect = query
    with mock.patch.object(self.mod, 'create_partitioned_table') as create:
      result = self.mod.migrate(client, 'brandometer2', '20261122', apply=True)
    self.assertEqual(result['status'], 'migrated')
    self.assertTrue(result['applied'])
    self.assertEqual(result['copied'], 41)
    create.assert_called_once()
    sqls = [call.args[0] for call in client.query.call_args_list]
    self.assertTrue(any(item.startswith('INSERT INTO') for item in sqls))
    self.assertTrue(any(
        'RENAME TO `responses_unpartitioned_backup_20261122`' in item
        for item in sqls))
    self.assertTrue(any('RENAME TO `responses`' in item for item in sqls))

  def test_already_partitioned_is_noop(self):
    client = self._client(FakeTable(
        field='CreatedAt', ptype='DAY', clustering=['ID']))
    result = self.mod.migrate(client, 'brandometer2', '20261122', apply=True)
    self.assertEqual(result['status'], 'already_partitioned')
    client.create_table.assert_not_called()
    client.query.assert_not_called()

  def test_cli_check_unpartitioned(self):
    client = self._client(FakeTable())
    buf = io.StringIO()
    with mock.patch.object(self.mod, '_bq_client', return_value=client), \
         redirect_stdout(buf):
      code = self.mod.main(['--project', 'brandometer2', '--check'])
    self.assertEqual(code, self.mod.CHECK_UNPARTITIONED)
    self.assertIn('--apply', buf.getvalue())

  def test_cli_dry_run_prints_plan(self):
    client = self._client(FakeTable())
    buf = io.StringIO()
    with mock.patch.object(self.mod, '_bq_client', return_value=client), \
         redirect_stdout(buf):
      code = self.mod.main(
          ['--project', 'brandometer2', '--stamp', '20261122'])
    self.assertEqual(code, 0)
    text = buf.getvalue()
    self.assertIn('Dry run', text)
    self.assertIn('CLUSTER BY ID', text)
    client.create_table.assert_not_called()


class DeployPartitionDetectTest(unittest.TestCase):

  def test_deploy_warns_instead_of_recreating(self):
    script = open(os.path.join(_ROOT, 'deploy'), encoding='utf-8').read()
    self.assertIn('warn_if_unpartitioned()', script)
    self.assertIn('migrate_responses_partition.py', script)
    self.assertIn('--time_partitioning_field CreatedAt', script)
    self.assertIn('--clustering_fields ID', script)
    self.assertIn('will not drop or recreate', script)
