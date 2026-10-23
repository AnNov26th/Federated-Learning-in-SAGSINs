"""Save a bounded feasible graph for one database-position snapshot."""
from collections import Counter
from itertools import combinations

from backend.models.network import NetworkLink, Node
from backend.services.routing_service import channel_distance, finite, surface_distance, visible


def feasible_pair(first, second, allow_ground_backbone=False):
    if first.id == second.id or first.scenario_id != second.scenario_id:
        return False
    if any(n.status.upper() != 'ACTIVE' or n.type not in {'SPACE', 'AIR', 'SEA', 'GROUND'}
           or not finite(n.bandwidth, True) or not finite(n.latency) for n in (first, second)):
        return False
    if first.type == second.type == 'GROUND':
        # Keep existing simulated terrestrial backhaul; do not invent fibre links.
        return allow_ground_backbone and surface_distance(first, second) <= 20000
    limit = 5000 if 'SPACE' in (first.type, second.type) else 1500 if 'AIR' in (first.type, second.type) else 500
    return visible(first, second) and channel_distance(first, second) <= limit


def connect_feasible_snapshot(db, scenario_id, neighbors=4):
    """No commit: caller owns transaction. Keep inactive links and history intact.

    Save nearest-neighbor edges plus a minimum spanning forest over eligible
    pairs. Never bridge components with edges that fail the geometric rules.
    Ground/sea surface links use the project's 500 km abstract channel rule;
    this is not antenna/link-budget or navigable-trajectory validation.
    """
    nodes = {n.id: n for n in db.query(Node).filter(Node.scenario_id == scenario_id).order_by(Node.id)}
    links = [link for link in db.query(NetworkLink).order_by(NetworkLink.id)
             if link.source in nodes and link.target in nodes]
    existing = {frozenset((link.source, link.target)): link for link in links}
    disabled = []
    for link in links:
        if link.status.upper() == 'ACTIVE' and not feasible_pair(nodes[link.source], nodes[link.target], True):
            link.status = 'INACTIVE'; disabled.append(link.id)
    active = {key: n for key, n in nodes.items() if n.status.upper() == 'ACTIVE'
              and n.type in {'SPACE', 'AIR', 'SEA', 'GROUND'} and finite(n.bandwidth, True) and finite(n.latency)}
    eligible, adjacent = [], {key: [] for key in active}
    for first, second in combinations(active.values(), 2):
        key = frozenset((first.id, second.id))
        saved = existing.get(key)
        # An explicitly inactive saved link must never be reactivated implicitly.
        if saved and saved.status.upper() != 'ACTIVE':
            continue
        if not feasible_pair(first, second, saved is not None):
            continue
        edge = (channel_distance(first, second), first.id, second.id)
        eligible.append(edge)
        adjacent[first.id].append(edge); adjacent[second.id].append(edge)
    chosen = {edge for candidates in adjacent.values() for edge in sorted(candidates)[:neighbors]}
    parent = {key: key for key in active}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]; key = parent[key]
        return key

    # Preserve existing active links first, then connect via feasible edges only.
    for link in links:
        if link.status.upper() == 'ACTIVE':
            parent[root(link.source)] = root(link.target)
    for edge in sorted(eligible):
        _, first, second = edge
        if root(first) != root(second):
            chosen.add(edge); parent[root(first)] = root(second)
    added, layers = [], Counter()
    for distance, first_id, second_id in sorted(chosen):
        if frozenset((first_id, second_id)) in existing:
            continue
        first, second = nodes[first_id], nodes[second_id]
        link = NetworkLink(source=first_id, target=second_id, distance=distance,
                           bandwidth=min(first.bandwidth, second.bandwidth),
                           latency=max(first.latency, second.latency, distance/299.792458), status='ACTIVE')
        db.add(link); added.append(link)
        layers['-'.join(sorted((first.type, second.type)))] += 1
    db.flush()
    components = {}
    for key in active:
        components.setdefault(root(key), []).append(key)
    return {'scenario_id': scenario_id, 'created_count': len(added),
            'created_link_ids': [link.id for link in added], 'deactivated_link_ids': disabled,
            'active_nodes': len(active), 'components': list(components.values()),
            'component_count': len(components), 'new_links_by_layer': dict(layers),
            'neighbors_per_node': neighbors, 'source': 'geometric_database_snapshot',
            'note': 'LOS and type distance limits checked for this snapshot. Existing terrestrial links retained. No physical link-budget or continuous orbital availability guarantee.'}
