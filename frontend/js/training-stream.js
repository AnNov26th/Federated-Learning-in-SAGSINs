export const phases = {queued:'Đang chờ', preparing:'Chuẩn bị dữ liệu', selecting:'Chọn client', selected:'Phân phối global model', local_training:'Huấn luyện local', client_finished:'Nhận cập nhật client', aggregating:'Tổng hợp global model', round_completed:'Đã lưu kết quả vòng', completed:'Hoàn tất', failed:'Thất bại', running:'Đang chạy',evaluating:'Đánh giá test và đối chứng mạng',cancelled:'Đã hủy',interrupted:'Gián đoạn'};
export const terminal = status => ['COMPLETED','FAILED','CANCELLED','INTERRUPTED'].includes(status);

export function watchTraining(id, onUpdate, onConnection = () => {}) {
    let source, timer, closed = false, fetching = false;
    const accept = data => { if (closed) return; onUpdate(data); if (terminal(data.status)) stop(); };
    async function poll() {
        if (fetching || closed) return;
        fetching = true;
        try {
            const response = await fetch(`/api/fl/experiments/${id}/progress`);
            if (!response.ok) throw new Error('Không đọc được trạng thái');
            accept((await response.json()).data);
        } catch { onConnection('Mất kết nối; đang thử lại…'); }
        finally { fetching = false; }
    }
    function fallback() { if (!timer && !closed) { poll(); timer = setInterval(poll, 2500); } }
    function stop() { closed = true; source?.close(); clearInterval(timer); }
    if (typeof EventSource !== 'undefined') {
        source = new EventSource(`/api/fl/experiments/${id}/events`);
        source.addEventListener('progress', event => { try { accept(JSON.parse(event.data)); } catch { fallback(); } });
        source.onopen = () => { clearInterval(timer); timer = null; onConnection('Đang kết nối trực tiếp'); };
        source.onerror = () => { if (!closed) { onConnection('Đang kết nối lại · tạm cập nhật định kỳ'); fallback(); } };
    } else fallback();
    return stop;
}
