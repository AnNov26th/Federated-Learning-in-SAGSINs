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