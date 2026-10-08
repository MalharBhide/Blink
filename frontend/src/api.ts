export const BASE = "http://127.0.0.1:8000";
export let token = "";
export class ConnectionError extends Error {
  constructor(
    message: string,
    public kind: "locked" | "offline",
  ) {
    super(message);
  }
}
// A launch ticket is one-use and expires in two minutes. Clear it before making requests.
function takeLaunchTicket() {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const ticket = fragment.get("launch") || "";
  if (ticket)
    window.history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search,
    );
  return ticket;
}
const openingTicket = takeLaunchTicket();
type SessionConfig = {
  token: string;
  session: string;
  ai_enabled: boolean;
  mock_enabled: boolean;
  model: string;
};
let initial: Promise<SessionConfig> | undefined;
export function connectNewLaunch() {
  const ticket = takeLaunchTicket();
  return ticket ? sessionRequest("", ticket) : null;
}
async function sessionRequest(accessCode = "", ticket = "") {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/session${ticket ? "/launch" : ""}`, {
      method: ticket ? "POST" : "GET",
      headers: {
        "X-Local-Client": "internship-ui",
        "X-Blink-Session": readTabSession(),
        ...(ticket
          ? { "X-Blink-Launch": ticket }
          : { "X-Blink-Access": accessCode }),
      },
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    throw new ConnectionError(
      "Blink isn't running yet. Open Launch Blink, then try again.",
      "offline",
    );
  }
  if (!res.ok)
    throw new ConnectionError(
      res.status === 403
        ? ticket
          ? "This opening link has expired. Open Launch Blink again for a fresh, private link."
          : accessCode
            ? "That code doesn't match. Try again, or open Launch Blink."
            : "Open Launch Blink to securely unlock your workspace."
        : "Blink is still starting. Wait a moment and check again.",
      res.status === 403 ? "locked" : "offline",
    );
  const data: SessionConfig = await res.json();
  token = data.token;
  try {
    sessionStorage.setItem("blink_session", data.session);
  } catch {
    /* Browsers may disable tab storage; pairing still works. */
  }
  return data;
}
export function initialConnect() {
  // React StrictMode must not consume a one-use ticket twice.
  return (initial ||= sessionRequest("", openingTicket));
}
export function connect(accessCode = "") {
  return sessionRequest(accessCode);
}
function readTabSession() {
  try {
    return sessionStorage.getItem("blink_session") || "";
  } catch {
    return "";
  }
}
export function clearSession() {
  try {
    sessionStorage.removeItem("blink_session");
  } catch {
    /* No persistent login. */
  }
  token = "";
  initial = undefined;
}
export async function api(path: string, method = "GET", body?: unknown) {
  const isForm = body instanceof FormData;
  const res = await fetch(`${BASE}/api${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(path === "/session" ? { "X-Blink-Session": readTabSession() } : {}),
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
