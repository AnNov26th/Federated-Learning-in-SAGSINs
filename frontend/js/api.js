export async function checkBackend() {
    try {
        const response = await fetch("/api/health");

        if (!response.ok) {
            throw new Error("Backend error");
        }

        return await response.json();

    } catch (error) {
        console.error(error);
        return null;
    }
}

export async function fetchNodes({ strict = false } = {}) {
    try {
        const response = await fetch("/api/nodes");
        if (!response.ok) {
            throw new Error("Failed to fetch nodes");
        }
        const data = await response.json();
        if (data.status !== "success" || !Array.isArray(data.data)) throw new Error("Dữ liệu node không hợp lệ.");
        return data.data;
    } catch (error) {
        console.error("API fetchNodes error:", error);
        if (strict) throw error;
        return [];
    }
}

export async function fetchLinks({ strict = false } = {}) {
    try {
        const response = await fetch("/api/links");
        if (!response.ok) throw new Error("Failed to fetch network links");
        const data = await response.json();
        if (data.status !== "success" || !Array.isArray(data.data)) throw new Error("Dữ liệu link không hợp lệ.");
        return data.data;
    } catch (error) {
        console.error("API fetchLinks error:", error);
        if (strict) throw error;
        return [];
    }
}
