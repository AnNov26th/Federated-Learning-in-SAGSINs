"""Inventory upgrades must preserve user data and survive startup/reload safely."""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.database.init_db import init_db
from backend.database.migrations import DatabaseMigration, VERSION, apply_data_migrations
from backend.database.global_coverage import analytical_coverage, load_satellites, sample_coverage
from backend.models.network import Node, NetworkLink
from backend.models.scenario import Scenario
from backend.models.simulation import Experiment


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_fresh_startup_bootstraps_178_nodes_and_repeat_is_noop(self):
        init_db(bind=self.engine)
        with Session(self.engine) as db:
            scenario = db.scalar(select(Scenario))
            self.assertEqual((scenario.total_nodes, scenario.space, scenario.ground, scenario.air, scenario.sea), (178, 96, 50, 12, 20))
            self.assertEqual(len(db.scalars(select(Node)).all()), 178)
            self.assertIsNotNone(db.get(DatabaseMigration, VERSION))
        init_db(bind=self.engine)
        result = apply_data_migrations(self.engine)
        self.assertTrue(result['already_applied'])
        with Session(self.engine) as db:
            self.assertEqual(len(db.scalars(select(Node)).all()), 178)
            self.assertEqual(len(db.scalars(select(DatabaseMigration)).all()), 2)

    def test_existing_nodes_links_experiments_and_user_edits_survive(self):
        with Session(self.engine) as db, db.begin():
            s = Scenario(name='SAGSIN-Global-Multilayer-106', total_nodes=2)
            db.add(s); db.flush()
            db.add_all([Node(id='MY-GROUND', type='GROUND', lat=12, lng=34, alt=0, bandwidth=123, latency=7, scenario_id=s.id),
                        Node(id='SAT-001', type='SPACE', lat=1, lng=2, alt=550, bandwidth=19, latency=9, status='OFFLINE', scenario_id=s.id)])
            db.flush()
            db.add(NetworkLink(source='MY-GROUND', target='SAT-001', distance=55, bandwidth=6, latency=8, status='INACTIVE'))
            db.add(Experiment(scenario_id=s.id, algorithm='Predictive', rounds=10, learning_rate=.01, status='COMPLETED', config_json={'checkpoint': 'preserve'}))
        result = apply_data_migrations(self.engine)
        self.assertEqual(len(result['details']['satellites_added']), 72)
        self.assertEqual(result['details']['baseline_nodes_added'], 0)
        with Session(self.engine) as db:
            node = db.get(Node, 'SAT-001')
            self.assertEqual((node.lat, node.lng, node.bandwidth, node.status), (1, 2, 19, 'OFFLINE'))
            self.assertEqual(db.scalar(select(Experiment)).config_json, {'checkpoint': 'preserve'})
            self.assertEqual(db.scalar(select(NetworkLink)).status, 'INACTIVE')
            polar = db.get(Node, 'SAT-POLAR-001')
            polar.status = 'OFFLINE'; db.delete(db.get(Node, 'SAT-POLAR-002')); db.commit()
        # Startup never reactivates edited nodes or resurrects deliberate deletions.
        apply_data_migrations(self.engine)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Node, 'SAT-POLAR-001').status, 'OFFLINE')
            self.assertIsNone(db.get(Node, 'SAT-POLAR-002'))

    def test_collision_rolls_back_all_new_rows_and_version_marker(self):
        with Session(self.engine) as db, db.begin():
            s = Scenario(name='User scenario'); db.add(s); db.flush()
            db.add(Node(id='SAT-POLAR-040', type='GROUND', lat=0, lng=0, alt=0, bandwidth=1, latency=1, scenario_id=s.id))
        with self.assertRaisesRegex(RuntimeError, 'collision'):
            apply_data_migrations(self.engine)
        with Session(self.engine) as db:
            self.assertEqual(len(db.scalars(select(Node)).all()), 1)
            self.assertEqual(len(db.scalars(select(Scenario)).all()), 1)
            self.assertIsNone(db.get(DatabaseMigration, VERSION))

    def test_checksum_change_is_rejected_without_changing_data(self):
        apply_data_migrations(self.engine)
        with Session(self.engine) as db, db.begin():
            db.get(DatabaseMigration, VERSION).checksum = '0'*64
        with self.assertRaisesRegex(RuntimeError, 'migration inventory changed'):
            apply_data_migrations(self.engine)
        with Session(self.engine) as db:
            self.assertEqual(len(db.scalars(select(Node)).all()), 178)

    def test_unrelated_scenario_is_preserved(self):
        with Session(self.engine) as db, db.begin():
            db.add(Scenario(name='Custom', total_nodes=99, space=99))
        apply_data_migrations(self.engine)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(Scenario).where(Scenario.name == 'Custom')).total_nodes, 99)
            self.assertEqual(len(db.scalars(select(Scenario)).all()), 2)

    def test_old_nodes_table_gets_metadata_without_losing_rows(self):
        legacy = create_engine('sqlite://')
        try:
            with legacy.begin() as connection:
                connection.execute(text('CREATE TABLE nodes (id VARCHAR(50) PRIMARY KEY, type VARCHAR(20), lat FLOAT, lng FLOAT, alt FLOAT, bandwidth FLOAT, latency FLOAT, battery_percent FLOAT, status VARCHAR(20), last_heartbeat DATETIME)'))
                connection.execute(text("INSERT INTO nodes(id,type,lat,lng,alt,bandwidth,latency,status) VALUES ('CUSTOM','GROUND',1,2,0,100,5,'ACTIVE')"))
            init_db(bind=legacy)
            with Session(legacy) as db:
                self.assertEqual(db.get(Node, 'CUSTOM').lng, 2)
                self.assertEqual(db.get(Node, 'SAT-POLAR-013').orbit_raan_deg, 30)
        finally:
            legacy.dispose()

    def test_legacy_seed_entry_point_uses_safe_initializer(self):
        from backend.database.seed_db import seed_db
        with patch('backend.database.init_db.init_db') as initialize:
            seed_db()
        initialize.assert_called_once_with()

    def test_manifest_and_continuous_coverage_bound(self):
        rows = load_satellites()
        self.assertEqual(len(rows), 72)
        self.assertEqual(len({r['id'] for r in rows}), 72)
        bound = analytical_coverage()
        self.assertTrue(bound['continuous_geometric_coverage'])
        self.assertGreater(bound['minimum_best_elevation_bound_deg'], 10)
        samples = sample_coverage(grid_deg=15, step_s=1800, duration_s=86400)
        self.assertEqual(samples['uncovered_samples'], 0)


if __name__ == '__main__':
    unittest.main()
