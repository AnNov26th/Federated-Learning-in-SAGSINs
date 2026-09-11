import sqlite3
import os
import pandas as pd
from datetime import datetime


class SAGSINDatabase:
    def __init__(self, db_path="sagsins_simulation.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Bảng dữ liệu thô do thiết bị biên thu thập
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS collected_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    data_samples INTEGER NOT NULL,
                    description TEXT,
                    timestamp TEXT NOT NULL
                )
            """)

            # 2. Bảng nhật ký huấn luyện cục bộ (FL Training Logs)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS training_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round INTEGER NOT NULL,
                    node_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    local_loss REAL NOT NULL,
                    local_accuracy REAL NOT NULL,
                    privacy_epsilon REAL NOT NULL,
                    weight_size_kb REAL NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            # 3. Bảng nhật ký định tuyến thông tin (Routing Logs)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS routing_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_node TEXT NOT NULL,
                    target_server TEXT NOT NULL,
                    path_hops TEXT NOT NULL,
                    total_latency_ms REAL NOT NULL,
                    bottleneck_bw_mbps REAL NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def insert_collected_data(self, node_id, node_name, layer, data_type, samples, description):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO collected_data (node_id, node_name, layer, data_type, data_samples, description, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (node_id, node_name, layer, data_type, samples, description, now))
            conn.commit()

    def insert_training_log(self, round_num, node_id, node_name, loss, acc, epsilon, weight_kb):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO training_logs (round, node_id, node_name, local_loss, local_accuracy, privacy_epsilon, weight_size_kb, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (round_num, node_id, node_name, loss, acc, epsilon, weight_kb, now))
            conn.commit()

    def insert_routing_log(self, source, target, path_str, latency, bw):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO routing_logs (source_node, target_server, path_hops, total_latency_ms, bottleneck_bw_mbps, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source, target, path_str, latency, bw, now))
            conn.commit()

    def fetch_collected_data(self):
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM collected_data ORDER BY id DESC LIMIT 50", conn)

    def fetch_training_logs(self):
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM training_logs ORDER BY id DESC LIMIT 50", conn)

    def fetch_routing_logs(self):
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM routing_logs ORDER BY id DESC LIMIT 50", conn)