// The packaged app uses its own origin. Development uses the loopback API.
export const BASE =
  window.location.port === "8000" &&
  ["127.0.0.1", "localhost"].includes(window.location.hostname)
    ? window.location.origin
    : "http://127.0.0.1:8000";
export let token = "";
export class ConnectionError extends Error {
  constructor(
    message: string,
    public kind: "locked" | "offline",
  ) {
    super(message);
  }
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}
function connectionError(error: ConnectionError) {
  window.dispatchEvent(new CustomEvent("blink:connection", { detail: error }));
  return error;
}
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
let recovery: Promise<SessionConfig> | undefined;
let sessionEpoch = 0;
export function connectNewLaunch() {
  const ticket = takeLaunchTicket();
  return ticket ? sessionRequest("", ticket) : null;
}
async function sessionRequest(accessCode = "", ticket = "") {
  const epoch = sessionEpoch;
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
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    throw new ConnectionError(
      "Blink is unavailable. Open Launch Blink, then reconnect. Your unsaved changes stay in this tab.",
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
  if (epoch !== sessionEpoch)
    throw new ConnectionError("Your workspace is locked.", "locked");
  token = data.token;
  try {
    sessionStorage.setItem("blink_session", data.session);
  } catch {
    /* Pairing also works without tab storage. */
  }
  window.dispatchEvent(
    new CustomEvent("blink:connection", { detail: { kind: "connected" } }),
  );
  return data;
}
export function initialConnect() {
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
  sessionEpoch += 1;
  try {
    sessionStorage.removeItem("blink_session");
  } catch {
    /* No persistent login. */
  }
  token = "";
  initial = undefined;
  recovery = undefined;
}
async function authorizedFetch(path: string, init: RequestInit = {}) {
  const usedToken = token;
  const epoch = sessionEpoch;
  const request = () =>
    fetch(`${BASE}/api${path}`, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(20000),
    });
  let res: Response;
  try {
    res = await request();
  } catch {
    // Never retry a timed-out write: it might already have reached the backend.
    throw connectionError(
      new ConnectionError(
        "Connection to Blink was interrupted. Reconnect to check progress; your changes remain in this tab.",
        "offline",
      ),
    );
  }
  if (epoch !== sessionEpoch)
    throw new ConnectionError("Your workspace is locked.", "locked");
  if (res.status === 401) {
    try {
      if (token === usedToken) {
        recovery ||= sessionRequest().finally(() => {
          recovery = undefined;
        });
        await recovery;
      }
      // A 401 was rejected before execution. This is the only automatic retry of a write.
      res = await request();
    } catch (error) {
      throw connectionError(
        error instanceof ConnectionError
          ? error
          : new ConnectionError(
              "Open Launch Blink to unlock this workspace again.",
              "locked",
            ),
      );
    }
    if (res.status === 401)
      throw connectionError(
        new ConnectionError(
          "Open Launch Blink to unlock this workspace again.",
          "locked",
        ),
      );
  }
  return res;
}
async function checkResponse(res: Response) {
  if (res.ok) return;
  const data = await res.json().catch(() => ({
    detail: "Blink could not complete this request. Please try again.",
  }));
  const detail = data.detail;
  const message = Array.isArray(detail)
    ? detail
        .map((item: { loc?: string[]; msg?: string }) => {
          const name = (item.loc || [])
            .filter((part) => part !== "body")
            .join(" · ")
            .replaceAll("_", " ");
          return `${name ? name + ": " : ""}${item.msg || "Check this value."}`;
        })
        .join(". ")
    : typeof detail === "string"
      ? detail
      : detail?.message || "Blink could not complete this request.";
  throw new ApiError(
    message,
    res.status,
    detail && !Array.isArray(detail) && typeof detail === "object"
      ? detail
      : {},
  );
}
export async function api(path: string, method = "GET", body?: unknown) {
  const isForm = body instanceof FormData;
  const res = await authorizedFetch(path, {
    method,
    headers: {
      ...(path === "/session" ? { "X-Blink-Session": readTabSession() } : {}),
      ...(body && !isForm ? { "Content-Type": "application/json" } : {}),
    },
    body: body
      ? ((isForm ? body : JSON.stringify(body)) as BodyInit)
      : undefined,
  });
  await checkResponse(res);
  return res.status === 204 ? null : res.json();
}
export async function previewBlob(id: string) {
  const res = await authorizedFetch(`/applications/${id}/preview`);
  await checkResponse(res);
  return res.status === 200 ? URL.createObjectURL(await res.blob()) : null;
}
export async function downloadDocument(id: string, name: string) {
  const res = await authorizedFetch(`/documents/${id}/download`);
  await checkResponse(res);
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
