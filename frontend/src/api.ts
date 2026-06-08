/**
 * API base: empty in dev (Vite proxies /api → backend). In production, set
 * VITE_API_BASE_URL if the UI is hosted on a different origin than the API.
 */
const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const inflightGetRequests = new Map<string, Promise<unknown>>();

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const method = (init?.method ?? "GET").toUpperCase();
  const canDeduplicate = method === "GET" && !init?.body;
  const cacheKey = canDeduplicate ? `${method}:${url}` : "";
  if (canDeduplicate) {
    const existing = inflightGetRequests.get(cacheKey);
    if (existing) return existing as Promise<T>;
  }

  const request = (async () => {
    const r = await fetch(url, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
    const data = (await r.json().catch(() => ({}))) as Record<string, unknown>;
    if (!r.ok) {
      const detail = data.detail;
      const msg =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : String(d))).join("; ")
            : r.statusText;
      throw new Error(msg || `HTTP ${r.status}`);
    }
    return data as T;
  })();

  if (canDeduplicate) {
    inflightGetRequests.set(cacheKey, request);
    request.then(
      () => inflightGetRequests.delete(cacheKey),
      () => inflightGetRequests.delete(cacheKey),
    );
  }
  return request;
}
