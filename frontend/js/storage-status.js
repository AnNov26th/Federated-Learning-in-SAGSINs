// Shared by the shell and directly opened pages; never blocks page startup.
async function showStorageStatus() {
    if (window.self !== window.top) return;
    try {
        const response = await fetch('/api/health');
        if (!response.ok) return;
        const health = await response.json();
        if (!health.warnings?.length) return;
        const notice = document.createElement('details');
        notice.id = 'storage-warning';
        notice.setAttribute('role', 'status');
        const title = document.createElement('summary');
        title.textContent = 'Một số dữ liệu lịch sử đang tạm ngưng';
        const message = document.createElement('p');
        message.textContent = health.warnings.join(' ');
        notice.append(title, message);
        document.body.append(notice);
    } catch (error) {
        console.debug('Storage status unavailable', error);
    }
}
showStorageStatus();
