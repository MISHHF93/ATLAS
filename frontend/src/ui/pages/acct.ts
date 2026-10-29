/** Same-origin client for /api/account, /api/connectors and /api/billing. The session lives in an HttpOnly cookie the page cannot read;
 *  the per-session CSRF token is returned by /api/account/me and sent as X-CSRF-Token on every POST. Secret values are only ever sent, never received. */
export type User = { id: string; email: string; role: "owner" | "admin" | "user"; display_name: string; timezone: string; created_at: number; last_login_at: number | null; referral_code: string | null };
export type Me = { authenticated: boolean; user?: User; csrf_token?: string; require_auth: boolean; registration?: string };
export type ApiResult<T> = { ok: boolean; status: number; data: T; error: string; message: string };

let csrf = "";
export const setCsrf = (t: string | undefined) => { csrf = t ?? ""; };

export async function api<T = Record<string, unknown>>(path: string, body?: unknown): Promise<ApiResult<T>> {
  const post = body !== undefined;
  try {
    const r = await fetch(path, {
      method: post ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
      headers: post ? { "content-type": "application/json", "x-csrf-token": csrf } : undefined,
      body: post ? JSON.stringify(body) : undefined,
    });
    let data = {} as T;
    try { data = (await r.json()) as T; } catch { /* empty body */ }
    const d = data as Record<string, unknown>;
    const detail = typeof d.detail === "string" ? d.detail : "";
    return { ok: r.ok, status: r.status, data, error: String(d.error ?? detail ?? ""), message: String(d.message ?? detail ?? "") };
  } catch {
    return { ok: false, status: 0, data: {} as T, error: "offline", message: "ATLAS backend is unreachable" };
  }
}

const FRIENDLY: Record<string, string> = {
  login_required: "Please sign in first.", invalid_credentials: "Email or password is not right.", rate_limited: "Too many attempts. Wait a few minutes and try again.",
  email_unavailable: "That email cannot be used. Sign in instead, or try another email.", weak_password: "Use at least 12 characters.",
  csrf_failed: "Your session changed. Reload the page and try again.", refused_live_trading: "Refused: ATLAS only connects paper and practice accounts.",
  master_key_unavailable: "The server has no encryption key set (ATLAS_MASTER_KEY), so secrets cannot be stored yet.",
  quota_exceeded: "Your plan limit is reached.", feature_not_in_plan: "That feature is not in your plan.", registration_closed: "Registration is closed on this server.",
  stripe_not_configured: "Stripe test keys are not set on the server yet.", forbidden: "You do not have access to that.",
};
export function why(r: { error: string; message: string; status: number }): string {
  return r.message && r.message !== r.error ? r.message : FRIENDLY[r.error] ?? (r.status === 0 ? "ATLAS backend is unreachable" : r.error || `Request failed (${r.status})`);
}
