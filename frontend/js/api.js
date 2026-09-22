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

export async function fetchNodes() {
    try {
        const response = await fetch("/api/nodes");
        if (!response.ok) {
            throw new Error("Failed to fetch nodes");
        }
        const data = await response.json();
        return data.status === "success" ? data.data : [];
    } catch (error) {
        console.error("API fetchNodes error:", error);
        return [];
    }
}