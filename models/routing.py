import math
import heapq


class SAGSINRoutingEngine:
    @staticmethod
    def calculate_distance_km(lat1, lon1, lat2, lon2):
        R = 6371.0  # Bán kính Trái Đất (km)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def calculate_link_latency(node_a, node_b, data_size_mb=2.0):
        dist_km = SAGSINRoutingEngine.calculate_distance_km(node_a['lat'], node_a['lon'], node_b['lat'], node_b['lon'])

        alt_a = node_a.get('orbit_altitude', 0) if node_a.get('layer') == 'Space' else (
            10 if node_a.get('layer') == 'Air' else 0)
        alt_b = node_b.get('orbit_altitude', 0) if node_b.get('layer') == 'Space' else (
            10 if node_b.get('layer') == 'Air' else 0)

        total_dist_km = math.sqrt(dist_km ** 2 + (alt_a - alt_b) ** 2)

        # Độ trễ lan truyền quang học/vô tuyến (Propagation delay)
        propagation_delay_ms = (total_dist_km / 300000.0) * 1000.0

        # Băng thông cổ chai nhỏ nhất
        bw_a = node_a.get('bandwidth', 50.0)
        bw_b = node_b.get('bandwidth', 50.0)
        bottleneck_bw = min(bw_a, bw_b)

        # Độ trễ truyền tải (Transmission delay)
        transmission_delay_ms = (data_size_mb * 8.0 / bottleneck_bw) * 1000.0
        processing_delay_ms = 1.5 if node_a.get('layer') == 'Space' or node_b.get('layer') == 'Space' else 0.5

        return propagation_delay_ms + transmission_delay_ms + processing_delay_ms, bottleneck_bw

    @staticmethod
    def find_optimal_route(all_entities, source_id, target_id, max_range_km=3000.0):
        entity_dict = {e['id']: e for e in all_entities}
        if source_id not in entity_dict or target_id not in entity_dict:
            return None, 0, 0

        graph = {e['id']: [] for e in all_entities}

        for i, u in enumerate(all_entities):
            for j, v in enumerate(all_entities):
                if i != j:
                    dist = SAGSINRoutingEngine.calculate_distance_km(u['lat'], u['lon'], v['lat'], v['lon'])
                    max_link_dist = 5000.0 if (u['layer'] == 'Space' or v['layer'] == 'Space') else max_range_km

                    if dist <= max_link_dist:
                        lat, bw = SAGSINRoutingEngine.calculate_link_latency(u, v)
                        graph[u['id']].append((v['id'], lat, bw))

        distances = {e['id']: float('inf') for e in all_entities}
        distances[source_id] = 0
        predecessors = {e['id']: None for e in all_entities}
        bottlenecks = {e['id']: float('inf') for e in all_entities}

        pq = [(0, source_id)]

        while pq:
            current_dist, u = heapq.heappop(pq)
            if current_dist > distances[u]:
                continue
            if u == target_id:
                break

            for v, lat, bw in graph[u]:
                if distances[u] + lat < distances[v]:
                    distances[v] = distances[u] + lat
                    predecessors[v] = u
                    bottlenecks[v] = min(bottlenecks[u], bw)
                    heapq.heappush(pq, (distances[v], v))

        path = []
        curr = target_id
        if distances[target_id] == float('inf'):
            return None, float('inf'), 0

        while curr is not None:
            path.append(curr)
            curr = predecessors[curr]
        path.reverse()

        return path, distances[target_id], bottlenecks[target_id]