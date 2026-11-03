"""Check startup against a fresh disposable DB; never uses the operational DB."""
import json
import os
import tempfile
from pathlib import Path


def main():
    # Set before importing any backend module.
    with tempfile.TemporaryDirectory(prefix='sagsin-release-') as folder:
        os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(folder) / 'clean.sqlite').as_posix()
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.database.database import engine
        try:
            with TestClient(app) as client:
                health = client.get('/api/health')
                assert health.status_code == 200 and health.json()['database_ready']
                for path in ('/', '/fl.html', '/results.html', '/js/service-clients.js',
                             '/js/3d/shared-motion.js', '/api/system'):
                    assert client.get(path).status_code == 200, path
                nodes = client.get('/api/nodes').json()['data']
                assert len(nodes) == 178, len(nodes)
                scenario = nodes[0]['scenario_id']
                state = client.get(f'/api/service/state?scenario_id={scenario}')
                assert state.status_code == 200 and state.json()['clients'] == []
                print(json.dumps(dict(clean_startup=True, nodes=len(nodes),
                                      database='disposable SQLite', health=health.json())))
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
