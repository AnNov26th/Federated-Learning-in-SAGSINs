import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch

from sagsin.config import ExperimentConfig
from sagsin.dataset import reuse_local


class DatasetReuseTests(unittest.TestCase):
    def fixture(self):
        config = ExperimentConfig()
        rows = {s: [dict(split=s, target_ms=1, tick=i)]
                for i, s in enumerate(('train', 'validation', 'test'))}
        encoded = ''.join(json.dumps(r, sort_keys=True, separators=(',', ':'))
                          for part in rows.values() for r in part)
        saved = dict(config_json=config.model_dump_json(),
                     fingerprint=hashlib.sha256(encoded.encode()).hexdigest())
        connection = MagicMock()
        connection.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = saved
        return config, rows, saved, connection

    def test_retraining_reads_same_rows_without_insert_or_regeneration(self):
        config, rows, saved, connection = self.fixture()
        changed = config.model_copy(update=dict(rounds=10, model_family='residual_mlp', selection='predictive'))
        with patch('sagsin.dataset.connect', return_value=connection), \
                patch('sagsin.dataset.load_local', side_effect=lambda _, run, split: rows[split]):
            actual, fingerprint = reuse_local({}, 'a' * 32, changed)
        self.assertEqual(actual, rows)
        self.assertEqual(fingerprint, saved['fingerprint'])
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        self.assertTrue(cursor.execute.call_args.args[0].startswith('SELECT'))
        cursor.executemany.assert_not_called()
        connection.commit.assert_not_called()

    def test_modified_rows_are_rejected(self):
        config, rows, _, connection = self.fixture()
        rows['train'][0]['target_ms'] = 99
        with patch('sagsin.dataset.connect', return_value=connection), \
                patch('sagsin.dataset.load_local', side_effect=lambda _, run, split: rows[split]):
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                reuse_local({}, 'a' * 32, config)

    def test_changed_data_seed_is_rejected_before_loading(self):
        config, _, _, connection = self.fixture()
        with patch('sagsin.dataset.connect', return_value=connection), patch('sagsin.dataset.load_local') as load:
            with self.assertRaisesRegex(ValueError, 'differs in seed'):
                reuse_local({}, 'a' * 32, config.model_copy(update={'seed': 71}))
        load.assert_not_called()
