import React, { useEffect, useState } from "react";
import "../styles.css";
import "./admin.css";

const API = import.meta.env.VITE_ADMIN_API_URL || `http://${window.location.hostname}:8060/api/admin`;
const RASA_API = import.meta.env.VITE_RASA_API_URL || `http://${window.location.hostname}:5005`;

function summarizeTrackerEvent(event) {
  if (event.event === "user" && event.text) return { role: "user", text: event.text, at: event.timestamp };
  if (event.event === "bot") {
    if (event.text) return { role: "bot", text: event.text, at: event.timestamp };
    const custom = event.data && event.data.custom;
    if (custom && custom.type) return { role: "bot", text: `[${custom.type} results card]`, at: event.timestamp };
    if (custom && custom.handover) return { role: "bot", text: "[Handover card prepared]", at: event.timestamp };
    return null;
  }
  return null;
}

const PAGE_SIZE = 10;

function Pager({ page, setPage, total }) {
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (pageCount <= 1) return null;
  return <div className="admin-pager"><button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>‹ Prev</button><span>Page {page + 1} of {pageCount}</span><button type="button" disabled={page >= pageCount - 1} onClick={() => setPage((p) => p + 1)}>Next ›</button></div>;
}

function AdminApp() {
  const [authenticated, setAuthenticated] = useState(false);
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [transcript, setTranscript] = useState(null);
  const [busySender, setBusySender] = useState(null);
  const [handoverPage, setHandoverPage] = useState(0);
  const [sessionPage, setSessionPage] = useState(0);

  async function viewTranscript(senderFull, label) {
    setTranscript({ label, loading: true, error: "", messages: [] });
    try {
      const response = await fetch(`${RASA_API}/conversations/${encodeURIComponent(senderFull)}/tracker?include_events=AFTER_RESTART`);
      if (!response.ok) throw new Error("Could not load this conversation from the Rasa server.");
      const tracker = await response.json();
      const messages = (tracker.events || []).map(summarizeTrackerEvent).filter(Boolean);
      setTranscript({ label, loading: false, error: "", messages });
    } catch (e) {
      setTranscript({ label, loading: false, error: e.message || "Could not load this conversation. Is the Rasa server running?", messages: [] });
    }
  }

  async function loadAnalytics() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/analytics`, { credentials: "include" });
      if (response.status === 401) { setAuthenticated(false); return; }
      if (!response.ok) throw new Error("Analytics service is unavailable.");
      setData(await response.json());
    } catch (e) { setError(e.message || "Could not load analytics."); }
    finally { setLoading(false); }
  }

  async function resolveHandover(sender, resolved) {
    setBusySender(sender); setError("");
    try {
      const response = await fetch(`${API}/handover/resolve`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sender, resolved }) });
      if (!response.ok) throw new Error((await response.json()).error || "Could not update this handover.");
      await loadAnalytics();
    } catch (e) { setError(e.message || "Could not update this handover."); }
    finally { setBusySender(null); }
  }

  async function deleteConversation(sender, label) {
    if (!window.confirm(`Permanently delete the conversation "${label}"? This removes it from the tracker store and cannot be undone.`)) return;
    setBusySender(sender); setError("");
    try {
      const response = await fetch(`${API}/session/delete`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sender }) });
      if (!response.ok) throw new Error((await response.json()).error || "Could not delete this conversation.");
      await loadAnalytics();
    } catch (e) { setError(e.message || "Could not delete this conversation."); }
    finally { setBusySender(null); }
  }

  async function clearAllConversations(count) {
    const typed = window.prompt(`This permanently deletes all ${count} recorded conversations and cannot be undone. Type DELETE ALL to confirm.`);
    if (typed !== "DELETE ALL") return;
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/sessions/clear`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: "DELETE ALL" }) });
      if (!response.ok) throw new Error((await response.json()).error || "Could not clear conversations.");
      setSessionPage(0); setHandoverPage(0);
      await loadAnalytics();
    } catch (e) { setError(e.message || "Could not clear conversations."); setLoading(false); }
  }

  useEffect(() => {
    fetch(`${API}/session`, { credentials: "include" }).then((r) => r.json()).then((r) => { setAuthenticated(r.authenticated); setReady(true); if (r.authenticated) loadAnalytics(); }).catch(() => { setError("Start the local admin service to view analytics."); setReady(true); });
  }, []);

  async function login(event) {
    event.preventDefault(); setError("");
    try {
      const response = await fetch(`${API}/login`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
      if (!response.ok) throw new Error((await response.json()).error || "Sign-in failed.");
      setToken(""); setAuthenticated(true); await loadAnalytics();
    } catch (e) { setError(e.message || "Could not sign in."); }
  }

  async function logout() {
    await fetch(`${API}/logout`, { method: "POST", credentials: "include" }).catch(() => {});
    setAuthenticated(false); setData(null);
  }

  if (!ready) return <div className="admin-loading">Opening secure analytics…</div>;
  if (!authenticated) return <main className="admin-login-shell"><a className="admin-back" href="/">← Back to trip planner</a><form className="admin-login-card" onSubmit={login}><div className="admin-mark">✳</div><div className="section-kicker">TERRA WORKSPACE</div><h1>Admin sign in</h1><p>Enter your access token to view aggregated chatbot activity.</p><label htmlFor="admin-token">Access token</label><input id="admin-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} required />{error && <div className="admin-error" role="alert">{error}</div>}<button className="admin-primary" type="submit">Sign in securely</button></form></main>;

  const totals = data?.totals || {};
  const maxDay = Math.max(1, ...(data?.daily || []).map((d) => d.conversations));
  const groups = [["Popular destinations", data?.destinations], ["Transport preferences", data?.transport], ["Currencies", data?.currencies]];
  const handoverQueue = data?.handover_queue || [];
  const sessions = data?.sessions || [];
  const handoverReasonLabel = { requested: "User requested", confusion: "Repeated confusion", recommendations_complete: "After results" };
  const statusClass = { Escalated: "is-escalated", Handled: "is-handled", Completed: "is-completed", "In progress": "is-progress", New: "is-new" };
  const handoverPageItems = handoverQueue.slice(handoverPage * PAGE_SIZE, handoverPage * PAGE_SIZE + PAGE_SIZE);
  const sessionPageItems = sessions.slice(sessionPage * PAGE_SIZE, sessionPage * PAGE_SIZE + PAGE_SIZE);
  return <><main className="admin-shell"><header className="admin-topbar"><a className="admin-brand" href="/"><span>✳</span> terra.<small>ADMIN ANALYTICS</small></a><div className="admin-actions"><a href="/">Trip planner</a><button onClick={loadAnalytics} disabled={loading}>{loading ? "Refreshing…" : "↻ Refresh"}</button><button onClick={logout}>Sign out</button></div></header><section className="admin-content"><div className="admin-title-row"><div><div className="section-kicker">OVERVIEW</div><h1>Chatbot analytics</h1><p>Aggregated usage from the local Rasa conversation store.</p></div><span className="admin-live"><i /> Database connected</span></div>{error && <div className="admin-error">{error}</div>}<section className="admin-kpis" aria-label="Chatbot totals">{[["Conversations", totals.conversations], ["Messages", totals.messages], ["Visitor turns", totals.user_turns], ["Plans generated", totals.plans_generated], ["Human handovers", totals.handovers]].map(([label, value]) => <article className="admin-kpi" key={label}><span>{label}</span><strong>{Number(value || 0).toLocaleString()}</strong><small>All recorded activity</small></article>)}</section><div className="admin-grid"><section className="admin-panel admin-activity"><div className="admin-panel-heading"><div><div className="section-kicker">LAST 14 DAYS</div><h2>Conversation activity</h2></div><span>New sessions</span></div>{data?.daily?.length ? <div className="admin-chart" role="img" aria-label="Daily new conversation counts">{data.daily.map((day) => <div className="admin-bar-column" key={day.date} title={`${day.date}: ${day.conversations} conversations`}><strong>{day.conversations || ""}</strong><div className="admin-bar" style={{ height: `${Math.max(5, day.conversations / maxDay * 100)}%` }} /><small>{day.date.slice(5)}</small></div>)}</div> : <div className="admin-empty">No recorded sessions yet.</div>}</section><section className="admin-panel admin-source"><div className="section-kicker">DATA SOURCE</div><h2>Local tracker store</h2><p>Analytics are calculated from Rasa event metadata. Aggregate analytics never store message text. Opening a conversation below fetches it live and read-only from the Rasa server itself.</p><small>Latest event: {data?.last_updated ? new Date(data.last_updated).toLocaleString() : "No events recorded"}</small></section></div><section className="admin-panel admin-handover-queue"><div className="admin-panel-heading"><div><div className="section-kicker">ESCALATIONS</div><h2>Human handover queue</h2></div><span>{handoverQueue.filter((h) => !h.resolved).length} pending · {handoverQueue.length} total</span></div>{handoverQueue.length ? <><ol className="admin-handover-list">{handoverPageItems.map((item) => <li key={item.sender} className={item.resolved ? "is-resolved" : ""}><span className={`admin-status-pill ${item.resolved ? "is-handled" : "is-escalated"}`}>{item.resolved ? "Resolved" : "Pending"}</span><span className="admin-handover-meta">…{item.sender.slice(-8)} · {new Date(item.at).toLocaleString()} · {handoverReasonLabel[item.reason] || item.reason}</span><span className="admin-handover-actions"><button type="button" className="admin-link-button" onClick={() => viewTranscript(item.sender, "…" + item.sender.slice(-8))}>Open</button><button type="button" className="admin-link-button" disabled={busySender === item.sender} onClick={() => resolveHandover(item.sender, !item.resolved)}>{item.resolved ? "Reopen" : "Mark resolved"}</button><button type="button" className="admin-link-button admin-link-danger" disabled={busySender === item.sender} onClick={() => deleteConversation(item.sender, "…" + item.sender.slice(-8))}>Delete</button></span></li>)}</ol><Pager page={handoverPage} setPage={setHandoverPage} total={handoverQueue.length} /></> : <div className="admin-empty">No conversations have been escalated to a human advisor yet.</div>}</section><section className="admin-panel admin-sessions"><div className="admin-panel-heading"><div><div className="section-kicker">MANAGE</div><h2>Conversations</h2></div><span className="admin-panel-heading-actions"><span>{sessions.length} total</span>{sessions.length > 0 && <button type="button" className="admin-link-button admin-link-danger" onClick={() => clearAllConversations(sessions.length)}>Clear all</button>}</span></div>{sessions.length ? <><table className="admin-sessions-table"><thead><tr><th>Session</th><th>Status</th><th>Route</th><th>Dates</th><th>Budget</th><th>Sustainability</th><th>Last activity</th><th /></tr></thead><tbody>{sessionPageItems.map((session) => <tr key={session.sender_full}><td><button type="button" className="admin-link-button" onClick={() => viewTranscript(session.sender_full, session.sender)}>{session.sender}</button></td><td><span className={`admin-status-pill ${statusClass[session.status] || ""}`}>{session.status}{session.handover_reason && <small> · {handoverReasonLabel[session.handover_reason] || session.handover_reason}</small>}</span></td><td>{session.brief.route || "-"}</td><td>{session.brief.dates || "-"}</td><td>{session.brief.budget || "-"}</td><td>{session.brief.sustainability || "-"}</td><td>{session.last_updated ? new Date(session.last_updated).toLocaleString() : "-"}</td><td><button type="button" className="admin-link-button admin-link-danger" disabled={busySender === session.sender_full} onClick={() => deleteConversation(session.sender_full, session.sender)}>Delete</button></td></tr>)}</tbody></table><Pager page={sessionPage} setPage={setSessionPage} total={sessions.length} /></> : <div className="admin-empty">No conversations recorded yet.</div>}</section><div className="admin-breakdowns">{groups.map(([title, entries]) => <section className="admin-panel" key={title}><div className="section-kicker">BREAKDOWN</div><h2>{title}</h2>{entries?.length ? <ol className="admin-ranking">{entries.map((item) => <li key={item.name}><span>{item.name}</span><strong>{item.count}</strong></li>)}</ol> : <div className="admin-empty">No data available yet.</div>}</section>)}</div><footer className="admin-footer">Terra admin · Local analytics · {loading ? "Updating" : "Current"}</footer></section></main>{transcript && <div className="admin-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setTranscript(null); }}><section className="admin-transcript-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-transcript-heading"><div className="admin-transcript-heading"><h2 id="admin-transcript-heading">Conversation · {transcript.label}</h2><button className="admin-dialog-close" type="button" aria-label="Close conversation" onClick={() => setTranscript(null)}>×</button></div>{transcript.loading && <div className="admin-empty">Loading conversation…</div>}{transcript.error && <div className="admin-error">{transcript.error}</div>}{!transcript.loading && !transcript.error && (transcript.messages.length ? <ol className="admin-transcript-list">{transcript.messages.map((message, index) => <li key={index} className={`admin-transcript-${message.role}`}><span className="admin-transcript-role">{message.role === "user" ? "Traveler" : "Terra"}</span><p>{message.text}</p></li>)}</ol> : <div className="admin-empty">No readable messages recorded for this conversation.</div>)}</section></div>}</>;
}

export default AdminApp;
