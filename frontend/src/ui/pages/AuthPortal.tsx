"use client";
/** The one sign-in surface: sign in, register (invite code when the server is invite-only), confirm email, forgot / reset password.
 *  Links from emails arrive as /settings?tab=profile&verify=TOKEN | reset=TOKEN | invite=CODE. Tokens are read once, removed from the address bar
 *  (so they are not in history or screenshots), and the destructive step is always a button + POST, never a page load. */
import { useEffect, useState, type FormEvent } from "react";
import { Card } from "../primitives";
import { api, why } from "./acct";

type Mode = "login" | "register" | "forgot" | "reset" | "verify" | "check_email" | "reset_done" | "verified" | "forgot_sent";

function takeParam(name: string): string {
  if (typeof window === "undefined") return "";
  const u = new URL(window.location.href);
  const v = u.searchParams.get(name) ?? "";
  if (v) { u.searchParams.delete(name); window.history.replaceState(null, "", u.pathname + (u.search || "") + u.hash); }
  return v;
}

export function AuthPortal({ registration, onDone, standalone = false }: { registration?: string; onDone: () => void; standalone?: boolean }) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [name, setName] = useState("");
  const [invite, setInvite] = useState(""); const [token, setToken] = useState(""); const [teamInvite, setTeamInvite] = useState(false);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [note, setNote] = useState("");
  const [unverified, setUnverified] = useState(false);

  useEffect(() => {
    const v = takeParam("verify"), r = takeParam("reset"), inv = takeParam("invite");
    if (v) { setToken(v); setMode("verify"); }
    else if (r) { setToken(r); setMode("reset"); }
    else if (inv) { setInvite(inv); setMode("register"); }
    if (new URLSearchParams(window.location.search).get("team_invite")) setTeamInvite(true);
  }, []);

  const go = (m: Mode) => { setMode(m); setErr(""); setNote(""); setUnverified(false); };
  const inviteOnly = registration === "invite";
  const closed = registration === "closed";

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(""); setNote(""); setUnverified(false);
    try {
      if (mode === "login") {
        const r = await api("/api/account/login", { email, password });
        if (r.ok) { setPassword(""); onDone(); return; }
        setPassword(""); setErr(why(r)); setUnverified(r.error === "email_not_verified");
      } else if (mode === "register") {
        const ref = new URLSearchParams(window.location.search).get("ref") ?? undefined;
        const r = await api("/api/account/register", { email, password, display_name: name, ref, invite: invite || undefined });
        setPassword("");
        if (r.ok) go("check_email"); else setErr(why(r));
      } else if (mode === "forgot") {
        const r = await api("/api/account/forgot-password", { email });
        if (r.ok) go("forgot_sent"); else setErr(why(r));
      } else if (mode === "reset") {
        const r = await api("/api/account/reset-password", { token, new: password });
        setPassword("");
        if (r.ok) { setToken(""); go("reset_done"); } else setErr(why(r));
      } else if (mode === "verify") {
        const r = await api("/api/account/verify-email", { token });
        if (r.ok) { setToken(""); go("verified"); } else setErr(why(r));
      }
    } finally { setBusy(false); }
  };

  const resend = async () => {
    setBusy(true); setErr("");
    const r = await api<{ message?: string }>("/api/account/resend-verification", { email });
    setBusy(false);
    if (r.ok) { setNote(r.data.message ?? "If that address is waiting for confirmation, we sent a new link."); setUnverified(false); } else setErr(why(r));
  };

  const title = { login: "Sign in", register: inviteOnly ? "Create your account (invitation)" : "Create your account", forgot: "Reset your password", reset: "Choose a new password",
    verify: "Confirm your email address", check_email: "Check your email", reset_done: "Password changed", verified: "Email confirmed", forgot_sent: "Check your email" }[mode];
  const link = (m: Mode, label: string) => <button type="button" className="ux-link-btn" onClick={() => go(m)}>{label}</button>;

  const body = (
    <Card title={title} subtitle="Your connector keys are stored encrypted and only your account can use them. ATLAS never places live trades." span="full">
      {teamInvite && mode !== "verify" && mode !== "reset" ? <p className="ux-action-msg" data-tone="warn" role="status">You have a team invitation. Sign in or create an account with the invited email, then accept it under Settings → Profile.</p> : null}
      {mode === "check_email" || mode === "forgot_sent" ? (
        <>
          <p role="status" aria-live="polite">{mode === "check_email"
            ? "If that address can be registered, we have sent it a message with the next step. Open the link in it to confirm your email, then sign in. If you used an invitation sent to this address, you can sign in now."
            : "If an account exists for that address, we have sent a password reset link. It works once and expires soon."}</p>
          <p className="ux-small">{link("login", "Back to sign in")}</p>
        </>
      ) : mode === "verified" || mode === "reset_done" ? (
        <>
          <p className="ux-action-msg" data-tone="good" role="status">{mode === "verified" ? "Your email address is confirmed. You can sign in now." : "Your password was changed and every device was signed out. Sign in with the new password."}</p>
          <p><button type="button" className="ux-btn" data-variant="primary" onClick={() => go("login")}>Go to sign in</button></p>
        </>
      ) : mode === "verify" ? (
        <form onSubmit={submit} className="ux-form-row" aria-label="Confirm email">
          <p>Press the button to confirm this email address.</p>
          <button type="submit" className="ux-btn" data-variant="primary" disabled={busy}>{busy ? "Please wait" : "Confirm my email"}</button>
        </form>
      ) : (
        <form onSubmit={submit} className="ux-form-row" aria-label={title}>
          {mode === "register" ? <label className="ux-field">Name (optional)<input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={80} /></label> : null}
          {mode !== "reset" ? <label className="ux-field">Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label> : null}
          {mode === "register" && (inviteOnly || invite) ? <label className="ux-field">Invitation code<input required={inviteOnly} value={invite} onChange={(e) => setInvite(e.target.value.trim())} autoComplete="off" spellCheck={false} /></label> : null}
          {mode !== "forgot" ? (
            <label className="ux-field">{mode === "reset" ? "New password" : "Password"}{mode === "register" || mode === "reset" ? " (12+ characters)" : ""}
              <input type="password" required minLength={mode === "login" ? 1 : 12} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
            </label>
          ) : null}
          <button type="submit" className="ux-btn" data-variant="primary" disabled={busy}>
            {busy ? "Please wait" : { login: "Sign in", register: "Create account", forgot: "Send reset link", reset: "Change password" }[mode as "login" | "register" | "forgot" | "reset"]}
          </button>
        </form>
      )}
      {err ? <p className="ux-action-msg" data-tone="bad" role="alert">{err}</p> : null}
      {note ? <p className="ux-action-msg" data-tone="good" role="status">{note}</p> : null}
      {unverified ? <p className="ux-small">Did not get the email? <button type="button" className="ux-link-btn" onClick={() => void resend()} disabled={busy || !email}>Send the confirmation link again</button></p> : null}
      {mode === "login" ? (
        <p className="ux-small">
          {link("forgot", "Forgot your password?")}
          {closed ? " · Registration is closed on this server." : <> · {inviteOnly ? "Have an invitation? " : "New here? "}{link("register", inviteOnly ? "Use it" : "Create an account")}</>}
        </p>
      ) : mode === "register" || mode === "forgot" || mode === "reset" || mode === "verify" ? <p className="ux-small">Already have an account? {link("login", "Sign in")}</p> : null}
    </Card>
  );
  return standalone ? <div className="ux-auth">{body}</div> : body;
}
