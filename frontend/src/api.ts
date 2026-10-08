export const BASE = "http://127.0.0.1:8000";
export let token = "";
export async function connect(accessCode = "") {
  const res = await fetch(`${BASE}/api/session`, {
    headers: {
      "X-Local-Client": "internship-ui",
      "X-Blink-Access": accessCode,
    },
  });
  if (!res.ok)
    throw new Error(
      res.status === 403
        ? "Enter your private access code to unlock Blink."
        : "Cannot connect to the local backend. Start FastAPI on port 8000.",
    );
  const data = await res.json();
  token = data.token;
  return data;
}
export async function api(path: string, method = "GET", body?: unknown) {
  const isForm = body instanceof FormData;
  const res = await fetch(`${BASE}/api${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body && !isForm ? { "Content-Type": "application/json" } : {}),
    },
    body: body
      ? ((isForm ? body : JSON.stringify(body)) as BodyInit)
      : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : data.detail?.message || JSON.stringify(data.detail),
    );
  }
  return res.status === 204 ? null : res.json();
}
export async function previewBlob(id: string) {
  const res = await fetch(`${BASE}/api/applications/${id}/preview`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.status === 200 ? URL.createObjectURL(await res.blob()) : null;
}
