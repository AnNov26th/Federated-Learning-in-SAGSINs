import socket
import threading
import pickle
import struct

class FLController:
    """Controller quản lý kết nối TCP Socket và điều phối luồng dữ liệu Federated Learning"""
    def __init__(self, host='127.0.0.1', port=8080):
        self.host = host
        self.port = port
        self.server_socket = None
        self.is_running = False
        self.received_weights = []
        self.lock = threading.Lock()  # Mutex Lock bảo vệ RAM Cache khỏi dính lỗi đa luồng

    def start_server(self):
        """Khởi chạy TCP Socket Server lắng nghe kết nối từ các nút biên (UAV, Vệ tinh, Tàu biển)"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.is_running = True
        print(f"📡 [Controller/SocketServer] Server đang lắng nghe tại {self.host}:{self.port}...")

        # Luồng nhận kết nối liên tục
        listen_thread = threading.Thread(target=self._accept_clients, daemon=True)
        listen_thread.start()

    def _accept_clients(self):
        while self.is_running:
            try:
                client_socket, address = self.server_socket.accept()
                print(f"🤝 [Controller] Nút biên kết nối thành công từ địa chỉ: {address}")
                # Sinh Thread riêng xử lý cho từng Client kết nối tới
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, address),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if not self.is_running:
                    break
                print(f"⚠️ Lỗi tiếp nhận kết nối: {e}")

    def _handle_client(self, client_socket, address):
        """Xử lý truyền nhận thông điệp qua Socket TCP từ 1 Client"""
        try:
            while self.is_running:
                # Đọc Header 4-byte chứa độ dài gói tin
                header = client_socket.recv(4)
                if not header:
                    break
                payload_size = struct.unpack('!I', header)[0]

                # Nhận đủ dung lượng payload
                data = bytearray()
                while len(data) < payload_size:
                    packet = client_socket.recv(payload_size - len(data))
                    if not packet:
                        break
                    data.extend(packet)

                if len(data) == payload_size:
                    # Giải nén chuỗi byte (Deserialization)
                    message = pickle.loads(data)
                    print(f"📥 [Controller] Đã nhận gói tin từ {address}: {message.get('node_id', 'Unknown')}")

                    # Lưu vào RAM Cache an toàn luồng nhờ Mutex Lock
                    with self.lock:
                        if 'weights' in message:
                            self.received_weights.append(message['weights'])

        except Exception as e:
            print(f"❌ Kết nối với {address} bị ngắt: {e}")
        finally:
            client_socket.close()

    def stop_server(self):
        self.is_running = False
        if self.server_socket:
            self.server_socket.close()
        print("🛑 [Controller] Đã dừng Socket Server.")

if __name__ == "__main__":
    controller = FLController()
    controller.start_server()
    print("✅ [Controller/SocketServer] Khởi tạo Controller mẫu thành công!")