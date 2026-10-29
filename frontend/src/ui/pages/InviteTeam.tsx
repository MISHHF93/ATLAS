"use client";
/** Admin registration invites and the Team seats card. A freshly minted code/link is shown ONCE (only its hash is stored server-side). */
import { useCallback, useEffect, useState } from "react";
import { Badge, Card, CopyButton, DataTable } from "../primitives";
import { api, why } from "./acct";

type R = Record<string, unknown>;
const when = (t: unknown) => (typeof t === "number" && t > 0 ? new Date(t * 1000).toLocaleString() : "never");
const origin = () => (typeof window === "undefined" ? "" : window.location.origin);
type Msg = { tone: "good" | "bad"; text: string } | null;

export function InvitesCard() {
  const [rows, setRows] = useState<R[]>([]); const [mode, setMode] = useState("");
  const [email, setEmail] = useState(""); const [note, setNote] = useState(""); const [days, setDays] = useState("7"); const [uses, setUses] = useState("1");
  const [fresh, setFresh] = useState<{ code: string; email: string | null } | null>(null); const [msg, setMsg] = useState<Msg>(null);
  const load = useCallback(async () => { const r = await api<{ invites: R[]; registration: string }>("/api/admin/invites"); if (r.ok) { setRows(r.data.invites); setMode(r.data.registration); } }, []);
  useEffect(() => { void load(); }, [load]);
  const create = async (e: React.FormEvent) => {
    e.preventDefault(); setMsg(null);
    const r = await api<{ code: string; email: string | null }>("/api/admin/invites/create", { email: email || undefined, note, ttl_days: Number(days) || 7, max_uses: Number(uses) || 1 });
    if (r.ok) { setFresh({ code: r.data.code, email: r.data.email }); setEmail(""); setNote(""); void load(); } else setMsg({ tone: "bad", text: why(r) });
  };
  const link = fresh ? `${origin()}/settings?tab=profile&invite=${fresh.code}` : "";
  return (
    <Card title="Invitations (admin)" span="full" subtitle={`Registration mode: ${mode || "checking"}. In invite mode nobody can register without a code. An email-bound invite is mailed to that address and also confirms it.`}>
      <form className="ux-form-row" onSubmit={create} aria-label="Create invitation">
        <label className="ux-field">Email (optional, binds the code)<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="ux-field">Note<input value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} /></label>
        <label className="ux-field">Valid days<input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} /></label>
        {!email ? <label className="ux-field">Uses<input type="number" min={1} max={100} value={uses} onChange={(e) => setUses(e.target.value)} /></label> : null}
        <button type="submit" className="ux-btn" data-variant="primary">Create invitation</button>
      </form>
      {msg ? <p className="ux-action-msg" data-tone={msg.tone} role="alert">{msg.text}</p> : null}
      {fresh ? (
        <div className="ux-action-msg" data-tone="good" role="status">
          <strong>Copy it now, it is shown once.</strong>{fresh.email ? ` Also sent to ${fresh.email} by the configured mail backend.` : ""}
          <div><code data-testid="new-invite-link">{link}</code> <CopyButton text={link} label="Copy link" /></div>
        </div>
      ) : null}
      <DataTable rows={rows} empty="No invitations yet" columns={[
        { key: "email", label: "For", render: (r) => String(r.email ?? "anyone with the code") }, { key: "note", label: "Note" },
        { key: "state", label: "State", render: (r) => <Badge tone={r.state === "open" ? "good" : "neutral"}>{String(r.state)}</Badge> },
        { key: "uses", label: "Used", render: (r) => `${r.uses}/${r.max_uses}` }, { key: "expires_at", label: "Expires", render: (r) => when(r.expires_at) },
        { key: "id", label: "", render: (r) => (r.state === "open" ? <button type="button" className="ux-btn" onClick={() => void api("/api/admin/invites/revoke", { id: r.id }).then(load)}>Revoke</button> : null) },
      ]} />
    </Card>
  );
}

type Team = { role: "owner" | "member" | "none"; can_manage: boolean; plan?: string; owner_email?: string; seat_active?: boolean;
  seats?: { limit: number; used: number; pending: number }; members?: { id: string; email: string; joined_at: number }[]; invites?: { id: string; email: string; expires_at: number }[] };

export function TeamCard({ reload }: { reload: () => void }) {
  const [t, setT] = useState<Team | null>(null); const [email, setEmail] = useState(""); const [code, setCode] = useState("");
  const [fresh, setFresh] = useState<{ email: string; code: string } | null>(null); const [msg, setMsg] = useState<Msg>(null);
  const load = useCallback(async () => { const r = await api<Team>("/api/team"); if (r.ok) setT(r.data); }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { // an emailed team link: ?team_invite=CODE (kept until accepted so it survives sign-in)
    const u = new URL(window.location.href); const c = u.searchParams.get("team_invite");
    if (c) setCode(c);
  }, []);
  const run = async (p: Promise<{ ok: boolean; error: string; message: string; status: number }>, ok: string) => {
    const r = await p; setMsg(r.ok ? { tone: "good", text: ok } : { tone: "bad", text: why(r) }); if (r.ok) { void load(); reload(); } return r.ok;
  };
  const accept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (await run(api("/api/team/accept", { code }), "You joined the team.")) {
      const u = new URL(window.location.href); u.searchParams.delete("team_invite"); window.history.replaceState(null, "", u.pathname + u.search + u.hash); setCode("");
    }
  };
  const invite = async (e: React.FormEvent) => {
    e.preventDefault(); setMsg(null);
    const r = await api<{ code: string; email: string }>("/api/team/invite", { email });
    if (r.ok) { setFresh({ email: r.data.email, code: r.data.code }); setEmail(""); void load(); } else setMsg({ tone: "bad", text: why(r) });
  };
  if (!t) return null;
  const link = fresh ? `${origin()}/settings?tab=profile&team_invite=${fresh.code}` : "";
  return (
    <Card title="Team" span="full" subtitle={t.role === "member" ? `You hold a seat on ${t.owner_email}'s team.` : t.can_manage ? `Seats: ${(t.seats?.used ?? 0) + (t.seats?.pending ?? 0)} of ${t.seats?.limit} used (pending invitations hold a seat). Plan: ${t.plan}.` : "Seats are part of the Team plan."}>
      {t.role === "member" ? (
        <p><Badge tone={t.seat_active ? "good" : "warn"}>{t.seat_active ? "seat active" : "seat inactive: the owner's plan lapsed"}</Badge>{" "}
          <button type="button" className="ux-btn" onClick={() => { if (window.confirm("Leave this team?")) void run(api("/api/team/leave", {}), "You left the team."); }}>Leave team</button></p>
      ) : (
        <>
          {t.can_manage ? (
            <>
              <form className="ux-form-row" onSubmit={invite} aria-label="Invite a teammate">
                <label className="ux-field">Teammate email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
                <button type="submit" className="ux-btn" data-variant="primary">Invite</button>
              </form>
              {fresh ? <div className="ux-action-msg" data-tone="good" role="status"><strong>Invitation for {fresh.email}. Shown once:</strong> <code data-testid="new-team-link">{link}</code> <CopyButton text={link} label="Copy link" /></div> : null}
              <DataTable rows={(t.members ?? []) as unknown as R[]} empty="No teammates yet" columns={[
                { key: "email", label: "Member" }, { key: "joined_at", label: "Joined", render: (r) => when(r.joined_at) },
                { key: "id", label: "", render: (r) => <button type="button" className="ux-btn" onClick={() => { if (window.confirm(`Remove ${r.email}?`)) void run(api("/api/team/remove", { user_id: r.id }), "Member removed."); }}>Remove</button> }]} />
              {(t.invites ?? []).length ? <DataTable rows={(t.invites ?? []) as unknown as R[]} columns={[
                { key: "email", label: "Pending invitation" }, { key: "expires_at", label: "Expires", render: (r) => when(r.expires_at) },
                { key: "id", label: "", render: (r) => <button type="button" className="ux-btn" onClick={() => void run(api("/api/team/invite/revoke", { id: r.id }), "Invitation revoked.")}>Revoke</button> }]} /> : null}
            </>
          ) : <p>Upgrade to Team under Billing to invite teammates.</p>}
          <form className="ux-form-row" onSubmit={accept} aria-label="Join a team">
            <label className="ux-field">Have a team invitation code?<input value={code} onChange={(e) => setCode(e.target.value.trim())} autoComplete="off" spellCheck={false} /></label>
            <button type="submit" className="ux-btn" disabled={!code}>Join team</button>
          </form>
        </>
      )}
      {msg ? <p className="ux-action-msg" data-tone={msg.tone} role="status">{msg.text}</p> : null}
    </Card>
  );
}
