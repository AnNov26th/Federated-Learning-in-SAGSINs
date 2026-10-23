import gzip
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, event, text

from backend.database.database import Base
from backend.database import init_db  # Register all models.
from backend.models.network import Node
from backend.reset_training import reset_training


class ResetTrainingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        event.listen(self.engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
        Base.metadata.create_all(self.engine)
        self.directory = tempfile.TemporaryDirectory()
        self.backup = Path(self.directory.name) / 'backup'
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO scenarios(id,name) VALUES(1,'Preserve')"))
            c.execute(Node.__table__.insert().values(id='G', type='GROUND', lat=0, lng=0,
                                                     alt=0, bandwidth=100, latency=1, scenario_id=1))
            c.execute(text("INSERT INTO participants(node_id,dataset_size,local_epochs,selected) VALUES('G',100,2,1)"))
            c.execute(text("INSERT INTO experiments(id,scenario_id,algorithm,rounds,learning_rate,status) VALUES(1,1,'FedAvg',1,.01,'COMPLETED')"))
            c.execute(text("INSERT INTO fl_rounds(id,experiment_id,round,participants_count,accuracy,loss,round_duration_s) VALUES(1,1,1,1,0,1,1)"))

    def tearDown(self):
        self.engine.dispose()
        self.directory.cleanup()

    def test_dry_run_preserves_records_then_reset_backs_up_and_keeps_topology(self):
        preview = reset_training(self.engine, self.backup)
        self.assertEqual(preview['counts']['experiments'], 1)
        self.assertFalse(self.backup.exists())
        result = reset_training(self.engine, self.backup, apply=True)
        self.assertEqual(result['after']['experiments'], 0)
        self.assertEqual(result['after']['fl_rounds'], 0)
        self.assertEqual(result['after']['nodes'], 1)
        self.assertEqual(result['after']['scenarios'], 1)
        with gzip.open(result['backup'], 'rt', encoding='utf-8') as f:
            rows = [json.loads(line) for line in f]
        self.assertTrue(any(row.get('table') == 'experiments' for row in rows))
        with self.engine.connect() as c:
            self.assertEqual(tuple(c.execute(text('SELECT dataset_size,selected,local_epochs FROM participants')).one()), (0,0,2))

    def test_active_training_prevents_reset(self):
        with self.engine.begin() as c:
            c.execute(text("UPDATE experiments SET status='RUNNING'"))
        with self.assertRaisesRegex(RuntimeError, 'active training'):
            reset_training(self.engine, self.backup, apply=True)
        self.assertFalse(self.backup.exists())
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT COUNT(*) FROM fl_rounds')), 1)
