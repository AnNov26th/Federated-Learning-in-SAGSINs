import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.database import init_db  # Register all models without starting migrations.
from backend.models.network import Node, NetworkLink
from backend.models.scenario import Scenario
from backend.services.topology_service import connect_feasible_snapshot, feasible_pair


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        scenario = Scenario(name='Network'); other = Scenario(name='Other')
        self.db.add_all([scenario, other]); self.db.flush()
        self.scenario = scenario.id
        for id, type, lng, alt, scenario_id in [('G','GROUND',0,0,scenario.id), ('U','AIR',10,.3,scenario.id),
                ('S','SPACE',5,1200,scenario.id), ('F','GROUND',0,0,other.id)]:
            self.db.add(Node(id=id,type=type,lat=0,lng=lng,alt=alt,bandwidth=100,latency=5,status='ACTIVE',scenario_id=scenario_id))
        self.db.flush()

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def test_impossible_saved_radio_link_is_disabled_and_satellite_relays_connect(self):
        old = NetworkLink(source='G',target='U',distance=1112,bandwidth=50,latency=4,status='ACTIVE')
        self.db.add(old); self.db.flush()
        result=connect_feasible_snapshot(self.db,self.scenario)
        self.assertEqual(result['deactivated_link_ids'],[old.id])
        self.assertEqual(old.status,'INACTIVE')
        self.assertEqual(result['component_count'],1)
        self.assertEqual(result['created_count'],2)
        for link in self.db.query(NetworkLink).filter_by(status='ACTIVE'):
            self.assertTrue(feasible_pair(self.db.get(Node,link.source), self.db.get(Node,link.target), True))
            self.assertNotIn('F',(link.source,link.target))

    def test_second_run_is_idempotent_and_does_not_reactivate_disabled_links(self):
        self.db.add(NetworkLink(source='G',target='S',distance=1,bandwidth=1,latency=1,status='INACTIVE'))
        self.db.flush()
        connect_feasible_snapshot(self.db,self.scenario)
        second=connect_feasible_snapshot(self.db,self.scenario)
        self.assertEqual(second['created_count'],0)
        self.assertEqual(second['deactivated_link_ids'],[])
        self.assertEqual(self.db.query(NetworkLink).filter_by(source='G',target='S').one().status,'INACTIVE')
        self.assertEqual(second['component_count'],2)

    def test_no_impossible_bridge_or_invented_ground_fibre(self):
        self.db.get(Node,'S').status='OFFLINE'
        self.db.get(Node,'U').status='OFFLINE'
        self.db.add(Node(id='G2',type='GROUND',lat=0,lng=120,alt=0,bandwidth=100,latency=5,status='ACTIVE',scenario_id=self.scenario))
        self.db.flush()
        result=connect_feasible_snapshot(self.db,self.scenario)
        self.assertEqual(result['created_count'],0)
        self.assertEqual(result['component_count'],2)

    def test_existing_terrestrial_backbone_is_kept(self):
        self.db.add(Node(id='G2',type='GROUND',lat=0,lng=120,alt=0,bandwidth=100,latency=5,status='ACTIVE',scenario_id=self.scenario))
        link=NetworkLink(source='G',target='G2',distance=13343,bandwidth=80,latency=45,status='ACTIVE')
        self.db.add(link); self.db.flush()
        connect_feasible_snapshot(self.db,self.scenario)
        self.assertEqual(link.status,'ACTIVE')
        self.assertEqual(link.bandwidth,80)


if __name__ == '__main__':
    unittest.main()
