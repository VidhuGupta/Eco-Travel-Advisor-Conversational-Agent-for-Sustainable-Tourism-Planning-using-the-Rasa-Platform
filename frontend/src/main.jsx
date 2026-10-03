import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";
import AdminApp from "./admin.jsx";

const DEFAULT_ENDPOINT = import.meta.env.VITE_RASA_WEBHOOK_URL || "http://localhost:5005/webhooks/rest/webhook";
const EMPTY_TRIP = {
  destination: "", origin: "", travel_start: "", travel_end: "", currency: "EUR", budget: "",
  sustainability_level: "", transport_preference: "", accommodation_preference: "", carbon_estimate_preference: "",
};
const STARTER_SETS = [
  { kind: "destination", cards: [
    { icon: "🇯🇵", title: "Tokyo", subtitle: "Temples & city lights", message: '/start_consultation{"destination": "Tokyo"}' },
    { icon: "🇫🇷", title: "Paris", subtitle: "Museums & architecture", message: '/start_consultation{"destination": "Paris"}' },
    { icon: "🇪🇬", title: "Cairo", subtitle: "Ancient history", message: '/start_consultation{"destination": "Cairo"}' },
    { icon: "🇰🇪", title: "Nairobi", subtitle: "Safari gateway", message: '/start_consultation{"destination": "Nairobi"}' },
  ] },
  { kind: "dates", cards: [
    { title: "Next week", subtitle: "Quick getaway", message: '/start_consultation{"travel_start": "next week"}' },
    { title: "In a few days", subtitle: "Spontaneous trip", message: '/start_consultation{"travel_start": "in 3 days"}' },
    { title: "Next month", subtitle: "Plan ahead", message: '/start_consultation{"travel_start": "next month"}' },
    { title: "Flexible dates", subtitle: "Open to anytime", message: '/start_consultation{"travel_start": "flexible"}' },
  ] },
  { kind: "eco", cards: [
    { title: "Maximum eco", subtitle: "Greenest options only", message: '/start_consultation{"sustainability_level": "maximum"}' },
    { title: "Balanced", subtitle: "Sustainable and practical", message: '/start_consultation{"sustainability_level": "balanced"}' },
    { title: "Low carbon travel", subtitle: "Train & ground transport", message: '/start_consultation{"transport_preference": "train"}' },
    { title: "Eco stays", subtitle: "Certified sustainable hotels", message: '/start_consultation{"accommodation_preference": "eco-certified"}' },
  ] },
];

const DESTINATIONS = [
  { city: "Tokyo", country: "Japan", flag: "🇯🇵", pos: [35.6762, 139.6503] }, { city: "Paris", country: "France", flag: "🇫🇷", pos: [48.8566, 2.3522] },
  { city: "Cairo", country: "Egypt", flag: "🇪🇬", pos: [30.0444, 31.2357] }, { city: "Nairobi", country: "Kenya", flag: "🇰🇪", pos: [-1.2921, 36.8219] },
  { city: "London", country: "United Kingdom", flag: "🇬🇧", pos: [51.5074, -0.1278] }, { city: "Madrid", country: "Spain", flag: "🇪🇸", pos: [40.4168, -3.7038] },
  { city: "Berlin", country: "Germany", flag: "🇩🇪", pos: [52.5200, 13.4050] }, { city: "Bangkok", country: "Thailand", flag: "🇹🇭", pos: [13.7563, 100.5018] },
  { city: "Mexico City", country: "Mexico", flag: "🇲🇽", pos: [19.4326, -99.1332] }, { city: "Seoul", country: "South Korea", flag: "🇰🇷", pos: [37.5665, 126.9780] },
];

function getStored(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}

function getStoredList(key) {
  try { const value = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(value) ? value : []; } catch { return []; }
}

function newSenderId() {
  return `advisor-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
}

function detectFieldFromPrompt(message) {
  const text = message.toLowerCase();
  if (/where will you be (travelling|traveling) from|choose a departure city|use your current location/.test(text)) return "origin";
  if (/what are your preferred dates|choose your (travel )?dates|departure date/.test(text)) return "travel_start";
  if (/what date would you like to return|return date/.test(text)) return "travel_end";
  if (/where would you like to go|choose a destination/.test(text)) return "destination";
  if (/comfortable travel budget|approximate (travel )?budget|numeric budget|what's your budget|typical budget/.test(text)) return "budget";
  if (/how much would you like to prioritize sustainability|choose standard, balanced/.test(text)) return "sustainability_level";
  if (/how would you prefer to travel|preferred transport|preferred mode of transport/.test(text)) return "transport_preference";
  if (/what kind of stay feels right|what accommodation/.test(text)) return "accommodation_preference";
  if (/would you like a carbon emissions comparison|choose whether you’d like an emissions comparison|choose whether you'd like an emissions comparison/.test(text)) return "carbon_estimate_preference";
  return null;
}

function parseFeasibleModes(message) {
  const match = /choose:\s*([^.]+?)(?:,\s*or\s*no preference)?\.?$/i.exec(message || "");
  if (!match) return null;
  const modes = match[1].split(",").map((mode) => mode.trim().toLowerCase()).filter(Boolean);
  return modes.length ? modes : null;
}

function parseBudgetRange(message) {
  const match = /roughly\s+([A-Z]{3})\s+(\d+(?:,\d{3})*)\s*-\s*(\d+(?:,\d{3})*)/.exec(message || "");
  if (!match) return null;
  const low = Number(match[2].replace(/,/g, ""));
  const high = Number(match[3].replace(/,/g, ""));
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return null;
  return { currency: match[1], low, high };
}

function roundNice(value) {
  const step = value < 200 ? 10 : value < 1000 ? 25 : value < 5000 ? 50 : value < 20000 ? 250 : 1000;
  return Math.round(value / step) * step;
}

function parseRoute(message) {
  const normalized = message.toLowerCase();
  const cities = DESTINATIONS.map((place) => place.city).sort((a, b) => b.length - a.length);
  const hits = [];
  for (const city of cities) {
    const match = new RegExp(`\\b${city}\\b`, "i").exec(normalized);
    if (match) hits.push({ city, index: match.index });
  }
  hits.sort((a, b) => a.index - b.index);
  const unique = hits.filter((hit, index) => hits.findIndex((other) => other.city === hit.city) === index);
  if (unique.length < 2) return null;
  const first = unique[0].city;
  const second = unique[1].city;
  const fromCity = unique.find(({ city }) => new RegExp(`\\bfrom\\s+(?:the\\s+)?${city}\\b`, "i").test(normalized))?.city;
  const toCity = unique.find(({ city }) => new RegExp(`\\bto\\s+${city}\\b`, "i").test(normalized))?.city;
  if (fromCity && toCity && fromCity !== toCity) return { origin: fromCity, destination: toCity };
  return { origin: first, destination: second };
}

function getRouteCity(route, field) {
  return route?.[field] || null;
}

function readReply(field, message) {
  if (!field || !message) return null;
  if (field === "budget") {
    const amount = message.replace(/,/g, "").match(/\d+(?:\.\d{1,2})?/);
    return amount ? amount[0] : null;
  }
  if (field === "travel_start" || field === "travel_end") {
    return message.match(/\d{4}-\d{2}-\d{2}/)?.[0] || null;
  }
  return message.trim();
}

function LogoMark() {
  return <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M25.8 6.1C17 6 9 8.2 6.3 14.1c-2 4.4.3 9.2 4.5 10.3 4.6 1.2 8.1-2.7 8.4-7.6-3.5 2-6.1 4.8-7.6 7.1 1.8-5.3 6.2-10.1 14.2-13.2Z"/><path d="M8 26.2c3.5-5.4 8.2-9.7 14.6-13.2"/></svg></span>;
}

function NavRail({ onRecent, onSaved, recentCount, savedCount }) {
  return <aside className="nav-rail" aria-label="Main navigation">
    <div className="nav-rail-heading"><span className="brand"><LogoMark /><span className="brand-name">terra<span>.</span></span></span></div>
    <button className="nav-item" type="button" title="Recent" onClick={onRecent}><span className="nav-icon">◷</span><span className="nav-label">Recent</span> <small className="nav-count">{recentCount}</small></button>
    <button className="nav-item" type="button" title="Saved" onClick={onSaved}><span className="nav-icon">♧</span><span className="nav-label">Saved</span> <small className="nav-count">{savedCount}</small></button>
    <a className="nav-item" href="/admin" title="Admin"><span className="nav-icon">▤</span><span className="nav-label">Admin</span></a>
  </aside>;
}

const HANDOVER_LABELS = [
  ["destination", "Destination"],
  ["origin", "Travelling from"],
  ["travel_start", "Departure date"],
  ["travel_end", "Return date"],
  ["budget", "Budget"],
  ["sustainability", "Sustainability priority"],
  ["transport", "Transport preference"],
  ["accommodation", "Accommodation preference"],
];

function HandoverCard({ context }) {
  return <div className="handover-card">
    <div className="handover-card-heading"><span className="handover-symbol">↗</span><div><strong>Specialist handover prepared</strong><small>This consultation context has been shared with an advisor.</small></div></div>
    <div className="handover-card-grid">{HANDOVER_LABELS.map(([key, label]) => <div className="handover-card-row" key={key}><small>{label}</small><span>{context?.[key] || "Not provided"}</span></div>)}</div>
  </div>;
}

function Message({ item }) {
  if (item.type === "handover") {
    return <article className="message bot-message" data-message-id={item.id}>
      <span className="message-avatar">✳</span>
      <div className="message-content"><div className="message-meta"><span>Terra</span><time>{item.time}</time></div><HandoverCard context={item.handoverContext} /></div>
    </article>;
  }
  if (item.type === "category") {
    return <article className="message bot-message" data-message-id={item.id}>
      <span className="message-avatar">✳</span>
      <div className="message-content"><div className="message-meta"><span>Terra</span><time>{item.time}</time></div><CategorySection {...item} /></div>
    </article>;
  }
  return <article className={`message ${item.sender === "user" ? "user-message" : "bot-message"}`} data-message-id={item.id}>
    <span className="message-avatar">{item.sender === "user" ? "You" : "✳"}</span>
    <div className="message-content"><div className="message-meta"><span>{item.sender === "user" ? "You" : "Terra"}</span><time>{item.time}</time></div><div className="bubble">{item.text}</div></div>
  </article>;
}

function IntakeControl({ field, busy, currency = "EUR", feasibleModes, budgetRange, travelStart, onChoose }) {
  const [query, setQuery] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [locationError, setLocationError] = useState("");
  if (!field) return null;
  if (field === "destination" || field === "origin") {
    const label = field === "destination" ? "Where would you like to go?" : "Where are you travelling from?";
    const submit = () => { if (query.trim()) onChoose(query.trim(), query.trim()); };
    const chooseCurrentLocation = () => {
      setLocationError("");
      if (!navigator.geolocation) { setLocationError("Location isn’t available in this browser. Type your city instead."); return; }
      navigator.geolocation.getCurrentPosition(
        ({ coords }) => {
          const coordStr = `${coords.latitude.toFixed(4)},${coords.longitude.toFixed(4)}`;
          onChoose("My current location", "📍 My current location", `/provide_destination{"origin": "${coordStr}"}`);
        },
        () => setLocationError("Location permission wasn’t granted. Type your city instead."),
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
      );
    };
    return <div className="intake-control place-input"><label className="intake-label" htmlFor={`${field}-input`}>{label}</label>
      {field === "origin" && <button type="button" className="current-location-button" disabled={busy} onClick={chooseCurrentLocation}>⌖ Use my current location</button>}
      <input id={`${field}-input`} className="place-search" placeholder="Type a city, e.g. Lisbon" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
      <button className="intake-primary" type="button" disabled={busy || !query.trim()} onClick={submit}>Continue</button>
      {locationError && <p className="location-error" role="alert">{locationError}</p>}
    </div>;
  }
  const today = new Date().toISOString().slice(0, 10);
  if (field === "travel_start") return <div className="intake-control date-controls"><div className="intake-label">What dates work best for you?</div><div className="date-inputs"><label>From<input type="date" min={today} value={start} onChange={(e) => setStart(e.target.value)} /></label><label>Until<input type="date" min={start || today} value={end} onChange={(e) => setEnd(e.target.value)} /></label></div><button className="intake-primary" type="button" disabled={busy || !start || !end} onClick={() => onChoose(`from ${start} to ${end}`, `${start} → ${end}`)}>Use these dates</button><button className="flexible-button" disabled={busy} type="button" onClick={() => onChoose("My dates are flexible.", "My dates are flexible")}>My dates are flexible</button></div>;
  if (field === "travel_end") {
    const minEnd = travelStart && travelStart !== "Flexible" ? travelStart : (start || today);
    return <div className="intake-control date-controls"><label className="intake-label" htmlFor="return-date">Choose your return date</label><input id="return-date" type="date" min={minEnd} value={end} onChange={(e) => setEnd(e.target.value)} /><button className="intake-primary" type="button" disabled={busy || !end} onClick={() => onChoose(end, end)}>Use this return date</button></div>;
  }
  if (field === "budget") {
    const range = budgetRange || { currency, low: 300, high: 3000 };
    const span = range.high - range.low;
    const fmt = (value) => new Intl.NumberFormat(undefined, { style: "currency", currency: range.currency, maximumFractionDigits: 0 }).format(value);
    const centers = [
      { label: "Budget-friendly", raw: range.low },
      { label: "Balanced", raw: range.low + span * 0.45 },
      { label: "Comfortable", raw: range.low + span * 0.85 },
      { label: "Flexible", raw: range.high * 1.3 },
    ];
    const categories = centers.map(({ label, raw }) => {
      const amount = roundNice(raw);
      const low = roundNice(Math.max(1, amount * 0.85));
      const high = roundNice(amount * 1.15);
      return { label, amount, low, high };
    });
    return <div className="intake-control"><div className="intake-label">What's your comfortable budget?</div><div className="choice-cards">{categories.map((cat) => <button key={cat.label} type="button" disabled={busy} className="choice-card" onClick={() => onChoose(String(cat.amount), `${fmt(cat.low)} - ${fmt(cat.high)}`)}><strong>{fmt(cat.low)} - {fmt(cat.high)}</strong><small>{cat.label}</small></button>)}</div></div>;
  }
  if (field === "carbon_estimate_preference") return <div className="intake-control"><div className="intake-label">Would you like a carbon emissions comparison for your route?</div><p className="carbon-form-hint">We’ll compare transport options when emissions data is available for your route.</p><div className="choice-cards"><button type="button" disabled={busy} className="choice-card" onClick={() => onChoose("Compare route emissions", "Yes, compare route emissions")}><strong>Show emissions</strong><small>Include estimated CO₂e by travel option</small></button><button type="button" disabled={busy} className="choice-card" onClick={() => onChoose("Skip carbon comparison", "Skip for now")}><strong>Skip for now</strong><small>Continue with the rest of your trip</small></button></div></div>;
  const transportHints = { train: "Scenic, lower-impact routes", flight: "When speed matters", bus: "An affordable ground option", car: "Travel at your own pace" };
  const choices = {
    sustainability_level: [["Standard", "Keep sustainability in mind"], ["Balanced", "A thoughtful balance"], ["High", "Prioritize lower-impact choices"], ["Maximum", "Choose the greenest options"]],
    transport_preference: [...(feasibleModes || ["train", "flight", "bus", "car"]).map((mode) => [mode[0].toUpperCase() + mode.slice(1), transportHints[mode] || ""]), ["No preference", "Show me the options"]],
    accommodation_preference: [["Eco-certified", "Verified sustainable stays"], ["Budget", "Keep the cost down"], ["Standard", "Comfort and value"], ["Luxury", "A special stay"], ["No preference", "Show me the options"]],
  }[field] || [];
  return <div className="intake-control"><div className="intake-label">Choose what feels right</div><div className="choice-cards">{choices.map(([value, hint]) => <button key={value} type="button" disabled={busy} className="choice-card" onClick={() => onChoose(value, value)}><strong>{value}</strong><small>{hint}</small></button>)}</div></div>;
}

function RouteSummary({ destination, origin }) {
  const hasRoute = Boolean(origin && destination);
  return <div className="route-summary" aria-label={hasRoute ? `Route from ${origin} to ${destination}` : "Route not yet set"}>
    {hasRoute ? <>
      <div className="route-summary-stop"><span className="route-summary-dot" /><strong>{origin}</strong><small>Departing</small></div>
      <div className="route-summary-track"><span /><span /><span /></div>
      <div className="route-summary-stop route-summary-stop-end"><span className="route-summary-dot route-summary-dot-end" /><strong>{destination}</strong><small>Arriving</small></div>
    </> : <p className="route-summary-empty">Choose an origin and destination to see your route here.</p>}
  </div>;
}

function TripBrief({ trip, onSaveItinerary }) {
  const dates = trip.travel_start && trip.travel_end ? `${trip.travel_start} → ${trip.travel_end}` : trip.travel_start || trip.travel_end || "Not set yet";
  const budgetDisplay = trip.budget ? new Intl.NumberFormat(undefined, { style: "currency", currency: trip.currency || "EUR" }).format(Number(trip.budget)) : "Not set yet";
  const preferenceChips = [
    ["✳", "Sustainability", trip.sustainability_level],
    ["⇢", "Transport", trip.transport_preference],
    ["⌂", "Stay", trip.accommodation_preference],
    ["CO₂", "Carbon comparison", trip.carbon_estimate_preference === "yes" ? "Yes" : trip.carbon_estimate_preference === "no" ? "No" : null],
  ].filter(([, , value]) => value);
  return <section className="trip-panel">
    <div className="panel-heading compact-heading"><h2>Trip brief</h2><button className="save-itinerary-button" type="button" onClick={onSaveItinerary}>＋ Save</button></div>
    <RouteSummary destination={trip.destination} origin={trip.origin} />
    <div className="trip-row"><span className="field-icon">▣</span><span className="trip-row-label">Dates</span><strong className="trip-row-value">{dates}</strong></div>
    <div className="trip-row"><span className="field-icon">€</span><span className="trip-row-label">Budget</span><strong className="trip-row-value">{budgetDisplay}{trip.currency ? <small className="trip-row-note"> · {trip.currency}</small> : null}</strong></div>
    {preferenceChips.length > 0 && <div className="trip-chip-row">{preferenceChips.map(([icon, label, value]) => <span className="trip-chip" key={label}><i>{icon}</i>{label}: <strong>{value}</strong></span>)}</div>}
  </section>;
}

function CarbonTag({ value }) {
  const emissions = Number(value);
  const level = Number.isFinite(emissions) && emissions < 100 ? "low" : Number.isFinite(emissions) && emissions < 300 ? "moderate" : "high";
  return <span className={`emission-tag emission-${level}`}>{Number.isFinite(emissions) ? emissions : value} kg CO₂e</span>;
}

const CATEGORY_HEADINGS = { transport: "Transport", stays: "Stays", events: "Events", sights: "Sights" };

function CategorySection({ categoryType, options, carbonResults, totalEmissionsKg, note, offsetNote }) {
  const hasItems = options?.length > 0;
  const hasCarbon = categoryType === "transport" && carbonResults?.length > 0;
  return <section className={`recommendations-carousel category-${categoryType || "other"}`}>
    <div className="category-heading"><span className="category-heading-dot" />{CATEGORY_HEADINGS[categoryType] || "Options"}</div>
    {!hasItems && !hasCarbon && <div className="integration-empty"><span className="empty-icon">✳</span><strong>No live options for these dates</strong><p>The connected providers didn't return matching offers for this route and date range.</p></div>}
    
    {hasCarbon && <div className="carbon-summary">
      <div className="carbon-summary-heading">Estimated CO₂e by transport mode</div>
      {carbonResults.map((entry) => <div className={`carbon-summary-row ${entry.recommended ? "is-recommended" : ""}`} key={entry.mode}>
        <span className="carbon-summary-label">{entry.label}{entry.recommended && <span className="carbon-summary-tag recommended-tag">Recommended</span>}{entry.preferred && <span className="carbon-summary-tag preferred-tag">Your preference</span>}</span>
        <CarbonTag value={entry.emissions_kg} />
      </div>)}
      {totalEmissionsKg != null && <div className="carbon-summary-total">Total estimated emissions: <strong>{totalEmissionsKg} kg CO₂e</strong></div>}
      <small className="carbon-summary-source">Calculated by {carbonResults[0]?.source || "Climatiq"} from the route's real distance - a per-person estimate, not a live quote.</small>
    </div>}
    {hasItems && <div className="recommendation-track">
      {options.map((item, index) => <article className={`recommendation-card ${item.badge || item.recommended ? "is-best" : ""}`} key={item.id || `${item.name}-${index}`}>
        {item.image && <img className="recommendation-image" src={item.image} alt="" loading="lazy" />}
        <div className="recommendation-card-heading"><span className="category-tag">{item.category || "Travel option"}</span>{item.recommended && <span className="best-badge">Recommended</span>}{item.preferred && <span className="carbon-summary-tag preferred-tag">Your preference</span>}{item.badge && <span className="best-badge">{item.badge}</span>}{item.over_budget && <span className="over-budget-badge">Over budget</span>}</div>
        <h3>{item.name || item.title || item.airline || item.hotel_name || "Travel option"}</h3>
        <p>{item.description || item.summary || item.route || item.location || "Details supplied by the connected data service."}</p>
        <div className="recommendation-meta">{item.price_label ? <span>{item.price_label}</span> : item.price != null && <span>{item.currency || "€"} {Number(item.price).toLocaleString()} {item.price_unit || ""}</span>}{item.distance_km != null && <span>{item.distance_km} km away</span>}{(item.emissions_kg ?? item.carbon_kg ?? item.co2e_kg) != null && <CarbonTag value={item.emissions_kg ?? item.carbon_kg ?? item.co2e_kg} />}</div>
        {item.source_url && <a className="recommendation-link" href={item.source_url} target="_blank" rel="noreferrer">View on {item.source || "provider"} ↗</a>}
      </article>)}
    </div>}
    {note && <p className="category-note">{note}</p>}
    {offsetNote && <p className="category-note">{offsetNote}</p>}
  </section>;
}

function SettingsDialog({ endpoint, setEndpoint, open, onClose }) {
  const [draft, setDraft] = useState(endpoint);
  useEffect(() => setDraft(endpoint), [endpoint, open]);
  if (!open) return null;
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <form onSubmit={(event) => { event.preventDefault(); setEndpoint(draft.trim().replace(/\/$/, "")); onClose(); }}>
        <div className="dialog-heading"><div><div className="section-kicker">CONNECTION</div><h2 id="settings-title">Assistant settings</h2></div><button className="dialog-close" type="button" aria-label="Close settings" onClick={onClose}>×</button></div>
        <label htmlFor="rasa-url">Rasa REST endpoint</label><input id="rasa-url" type="url" value={draft} onChange={(event) => setDraft(event.target.value)} required />
        <p>Use the local REST channel while running the Rasa server. The browser and server must be on the same machine, or the endpoint must be reachable over your network.</p>
        <button className="save-settings" type="submit">Save connection</button>
      </form>
    </section>
  </div>;
}

function LibraryDialog({ mode, records, onClose, onOpenRecord, onDeleteRecord }) {
  if (!mode) return null;
  const isSaved = mode === "saved";
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="settings-dialog library-dialog" role="dialog" aria-modal="true" aria-labelledby="library-title">
      <div className="library-dialog-inner"><div className="dialog-heading"><div><div className="section-kicker">WORKSPACE</div><h2 id="library-title">{isSaved ? "Saved itineraries" : "Recent conversations"}</h2></div><button className="dialog-close" type="button" aria-label="Close" onClick={onClose}>×</button></div>
        {!records.length ? <p className="library-empty">{isSaved ? "Save a trip brief to keep it here." : "Your recent chats will appear here as you plan."}</p> : <div className="library-list">{records.map((record) => <article className="library-item" key={record.id}>
          <button type="button" className="library-record-open" onClick={() => onOpenRecord(record)}><strong>{record.title || "Untitled trip"}</strong><small>{record.subtitle || "Trip details not set"}</small><time>{new Date(record.updatedAt || record.createdAt || Date.now()).toLocaleString()}</time></button>
          <button className="library-delete" type="button" title={isSaved ? "Remove saved itinerary" : "Remove recent conversation"} onClick={() => onDeleteRecord(record.id)}>×</button>
        </article>)}</div>}
      </div>
    </section>
  </div>;
}

function App() {
  const [endpoint, setEndpointState] = useState(() => getStored("terra-rasa-rest-url", DEFAULT_ENDPOINT));
  const [sender, setSender] = useState(() => newSenderId());
  const [status, setStatus] = useState("checking");
  const [messages, setMessages] = useState(() => [{ id: "welcome", sender: "bot", text: "Hello! I can help you plan a thoughtful trip. Start a consultation and we’ll choose a destination, dates, budget, and travel preferences together.", time: "Just now" }]);
  const [trip, setTrip] = useState(() => EMPTY_TRIP);
  const [recommendations, setRecommendations] = useState(() => []);
  const [carbonResults, setCarbonResults] = useState(() => []);
  const [mockData, setMockData] = useState(() => false);
  const [providerStatus, setProviderStatus] = useState({});
  const [handover, setHandover] = useState(false);
  const [handoverPrompt, setHandoverPrompt] = useState(false);
  const [pendingField, setPendingField] = useState(null);
  const [feasibleModes, setFeasibleModes] = useState(null);
  const [budgetRange, setBudgetRange] = useState(null);
  const [starterSetIndex, setStarterSetIndex] = useState(0);
  const [tripPanelOpen, setTripPanelOpen] = useState(false);
  const [serverButtons, setServerButtons] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [libraryMode, setLibraryMode] = useState(null);
  const [recentConversations, setRecentConversations] = useState(() => getStoredList("terra-recent-conversations"));
  const [savedItineraries, setSavedItineraries] = useState(() => getStoredList("terra-saved-itineraries"));
  const feedRef = useRef(null);
  const pendingRef = useRef(null);
  const busyRef = useRef(false);
  const textareaRef = useRef(null);

  useEffect(() => { localStorage.setItem("terra-rasa-rest-url", endpoint); }, [endpoint]);
  useEffect(() => { pendingRef.current = pendingField; }, [pendingField]);
  useEffect(() => {
    if (messages.length !== 1) return;
    const timer = setInterval(() => setStarterSetIndex((index) => (index + 1) % STARTER_SETS.length), 4500);
    return () => clearInterval(timer);
  }, [messages.length]);
  const prevMessageCountRef = useRef(0);
  useEffect(() => {
    const node = feedRef.current;
    if (!node) return;
    const prevCount = prevMessageCountRef.current;
    prevMessageCountRef.current = messages.length;
    if (messages.length > prevCount) {
      const firstNew = messages[prevCount];
      const el = firstNew && node.querySelector(`[data-message-id="${firstNew.id}"]`);
      if (el) { el.scrollIntoView({ block: "start", behavior: prevCount === 0 ? "auto" : "smooth" }); return; }
    }
    node.scrollTop = node.scrollHeight;
  }, [messages]);
  useEffect(() => { if (feedRef.current && busy) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [busy, serverButtons, pendingField]);
  useEffect(() => {
    const hasActivity = messages.length > 1 || Object.values(trip).some(Boolean) || recommendations.length > 0;
    if (!hasActivity) return;
    const now = new Date().toISOString();
    const record = { id: sender, sender, messages, trip, recommendations, carbonResults, mockData, updatedAt: now, title: trip.destination ? `${trip.origin ? `${trip.origin} → ` : ""}${trip.destination}` : "Eco-travel conversation", subtitle: [trip.travel_start && trip.travel_end ? `${trip.travel_start} → ${trip.travel_end}` : "Dates not set", trip.budget ? `${trip.currency || "EUR"} ${trip.budget}` : "Budget not set"].join(" · ") };
    setRecentConversations((current) => {
      const next = [record, ...current.filter((item) => item.id !== sender)].slice(0, 30);
      try { localStorage.setItem("terra-recent-conversations", JSON.stringify(next)); } catch {}
      return next;
    });
  }, [sender, messages, trip, recommendations, carbonResults, mockData]);
  useEffect(() => { try { localStorage.setItem("terra-saved-itineraries", JSON.stringify(savedItineraries)); } catch {} }, [savedItineraries]);
  useEffect(() => {
    const controller = new AbortController();
    fetch(endpoint, { method: "OPTIONS", signal: controller.signal }).then(() => setStatus("connected")).catch(() => setStatus("offline"));
    return () => controller.abort();
  }, [endpoint]);

  function addMessage(text, senderRole = "bot") {
    setMessages((current) => [...current, { id: `${Date.now()}-${Math.random()}`, sender: senderRole, text, time: new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date()) }]);
  }

  function addHandoverMessage(context) {
    setMessages((current) => [...current, { id: `${Date.now()}-${Math.random()}`, sender: "bot", type: "handover", handoverContext: context, time: new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date()) }]);
  }

  function addCategoryMessage(custom) {
    setMessages((current) => [...current, { id: `${Date.now()}-${Math.random()}`, sender: "bot", type: "category", categoryType: custom.type, options: custom.options || [], carbonResults: custom.carbon_results || [], totalEmissionsKg: custom.total_emissions_kg, note: custom.note, offsetNote: custom.offset_note, time: new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date()) }]);
  }

  async function refreshTripFromTracker(conversationId = sender) {
    try {
      const base = endpoint.replace(/\/webhooks\/rest\/webhook\/?$/, "");
      const response = await fetch(`${base}/conversations/${encodeURIComponent(conversationId)}/tracker`);
      if (!response.ok) return;
      const data = await response.json();
      const slots = data?.slots || {};
      setTrip((current) => {
        const next = { ...current };
        for (const key of Object.keys(EMPTY_TRIP)) {
          const value = slots[key];
          if (value !== undefined && value !== null && value !== "") next[key] = String(value);
        }
        return next;
      });
    } catch {
    }
  }

  function updateTrip(field, value) {
    if (!field || !value || !(field in EMPTY_TRIP)) return;
    setTrip((current) => ({ ...current, [field]: String(value).trim() }));
  }

  function inspectBotItem(item) {
    const text = item.text || "";
    const hasServerButtons = Array.isArray(item.buttons) && item.buttons.length > 0;
    const field = hasServerButtons ? null : detectFieldFromPrompt(text);
    if (field) {
      setPendingField(field);
      pendingRef.current = field;
      setServerButtons([]);
      setFeasibleModes(field === "transport_preference" ? parseFeasibleModes(text) : null);
      setBudgetRange(field === "budget" ? parseBudgetRange(text) : null);
    } else if (hasServerButtons) {
      setServerButtons(item.buttons);
    }
    const custom = item.custom;
    let structuredHandover = false;
    let structuredConfirm = false;
    if (custom && typeof custom === "object") {
      if (custom.mock_data !== undefined) setMockData(Boolean(custom.mock_data));
      if (custom.provider_status && typeof custom.provider_status === "object") setProviderStatus(custom.provider_status);
      if (Array.isArray(custom.carbon_results)) setCarbonResults(custom.carbon_results);
      if (custom.handover || custom.escalated) structuredHandover = true;
      if (custom.awaiting_handover_confirm) structuredConfirm = true;
      if (CATEGORY_TYPES.includes(custom.type) && Array.isArray(custom.options)) {
        setRecommendations((current) => [...current, ...custom.options]);
      } else {
        const items = custom.recommendations || custom.options || custom.results;
        if (Array.isArray(items) && items.length) setRecommendations((current) => [...current, ...items]);
      }
    }
    const textIndicatesHandover = !custom && /specialist review required|handover (has been )?prepared|escalat(ed|ion)/i.test(text);
    if (structuredHandover || textIndicatesHandover) setHandover(true);
    setHandoverPrompt(structuredConfirm);
  }

  async function postToAssistant(message, senderId = sender) {
    const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sender: senderId, message }) });
    if (!response.ok) throw new Error(`Rasa returned HTTP ${response.status}`);
    return response.json();
  }

  const CATEGORY_TYPES = ["transport", "stays", "events", "sights"];

  function displayAssistantPayload(payload) {
    if (!Array.isArray(payload) || !payload.length) { addMessage("I received that. What would you like to do next?"); return; }
    if (payload.some((item) => CATEGORY_TYPES.includes(item?.custom?.type))) setRecommendations([]);
    payload.forEach((item) => {
      const structuredContext = item.custom && typeof item.custom === "object" && item.custom.handover_context && typeof item.custom.handover_context === "object" ? item.custom.handover_context : null;
      const categoryType = item.custom?.type;
      if (structuredContext) addHandoverMessage(structuredContext);
      else if (CATEGORY_TYPES.includes(categoryType)) addCategoryMessage(item.custom);
      else if (item.text) addMessage(item.text);
      inspectBotItem(item);
    });
  }

  function prettifyPayloadText(text) {
    if (!text || !text.startsWith("/")) return text;
    const intent = text.slice(1).split("{")[0];
    if (intent === "confirm_positive") return "Yes";
    if (intent === "confirm_negative") return "No";
    return intent.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
  }

  async function loadConversationFromBackend(senderId) {
    const base = endpoint.replace(/\/webhooks\/rest\/webhook\/?$/, "");
    const response = await fetch(`${base}/conversations/${encodeURIComponent(senderId)}/tracker`);
    if (!response.ok) throw new Error(`Could not load this conversation (HTTP ${response.status})`);
    const data = await response.json();
    const rebuilt = [];
    (data.events || []).forEach((event, index) => {
      const time = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date((event.timestamp || 0) * 1000));
      if (event.event === "user" && event.text) rebuilt.push({ id: `${event.timestamp}-${index}-u`, sender: "user", text: prettifyPayloadText(event.text), time });
      else if (event.event === "bot" && event.text) rebuilt.push({ id: `${event.timestamp}-${index}-b`, sender: "bot", text: event.text, time });
    });
    const slots = data.slots || {};
    const nextTrip = { ...EMPTY_TRIP };
    for (const key of Object.keys(EMPTY_TRIP)) if (slots[key]) nextTrip[key] = String(slots[key]);
    return { messages: rebuilt, trip: nextTrip };
  }

  async function syncTripSlots(changes, conversationId = sender) {
    const base = endpoint.replace(/\/webhooks\/rest\/webhook\/?$/, "");
    const events = Object.entries(changes).filter(([key]) => key in EMPTY_TRIP).map(([name, value]) => ({ event: "slot", name, value }));
    if (!events.length) return;
    const response = await fetch(`${base}/conversations/${encodeURIComponent(conversationId)}/tracker/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(events) });
    if (!response.ok) throw new Error(`Trip updated here, but assistant sync returned HTTP ${response.status}`);
  }

  async function sendMessage(message, visibleText = message, payloadOverride = null) {
    if (!message || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    const currentField = pendingRef.current;
    setServerButtons([]);
    addMessage(visibleText, "user");
    const extracted = currentField === "travel_start" && /flexible/i.test(message) ? "Flexible" : readReply(currentField, message);
    if (currentField && extracted) updateTrip(currentField, extracted);
    if (currentField === "travel_start" && /\d{4}-\d{2}-\d{2}/.test(message)) {
      const dates = message.match(/\d{4}-\d{2}-\d{2}/g);
      if (dates?.[0]) updateTrip("travel_start", dates[0]);
      if (dates?.[1]) updateTrip("travel_end", dates[1]);
    }
    if (currentField === "travel_start" && /flexible/i.test(message)) updateTrip("travel_end", "Flexible");
    setPendingField(null);
    setFeasibleModes(null);
    setBudgetRange(null);
    pendingRef.current = null;
    try {
      const route = parseRoute(message);
      const canResolveRoute = route && ["destination", "origin"].includes(currentField);
      const firstField = currentField === "destination" ? "destination" : "origin";
      let payload = await postToAssistant(canResolveRoute ? getRouteCity(route, firstField) : (payloadOverride || message));
      setStatus("connected");
      displayAssistantPayload(payload);
      if (canResolveRoute) {
        const otherField = firstField === "destination" ? "origin" : "destination";
        updateTrip(firstField, getRouteCity(route, firstField));
        if (pendingRef.current === otherField) {
          payload = await postToAssistant(getRouteCity(route, otherField));
          displayAssistantPayload(payload);
          updateTrip(otherField, getRouteCity(route, otherField));
        }
      }
      await refreshTripFromTracker();
    } catch (error) {
      setStatus("offline");
      addMessage(`I couldn’t reach the Rasa assistant. Check that the server is running and the REST endpoint is enabled. (${error.message})`);
    } finally {
      busyRef.current = false;
      setBusy(false);
      textareaRef.current?.focus();
    }
  }

  function submitMessage(event) {
    event.preventDefault();
    const message = draft.trim();
    if (!message) return;
    setDraft("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    sendMessage(message);
  }

  function chooseReply(button) {
    const title = typeof button === "string" ? button : button.title || button.payload;
    const payload = typeof button === "string" ? button : button.payload || title;
    sendMessage(payload, title);
  }

  function resetConversation() {
    const nextSender = newSenderId();
    setSender(nextSender);
    setMessages([{ id: `${Date.now()}`, sender: "bot", text: "This conversation has been reset. Start a new consultation whenever you’re ready.", time: "Just now" }]);
    setTrip(EMPTY_TRIP);
    setRecommendations([]);
    setCarbonResults([]);
    setMockData(false);
    setProviderStatus({});
    setHandover(false);
    setHandoverPrompt(false);
    setPendingField(null);
    setFeasibleModes(null);
    setBudgetRange(null);
    pendingRef.current = null;
    setServerButtons([]);
  }

  function saveItinerary() {
    if (!trip.destination && !trip.origin) { addMessage("Choose a destination or departure city before saving this itinerary."); return; }
    const now = new Date().toISOString();
    const record = { id: `saved-${Date.now()}`, title: trip.destination ? `${trip.origin ? `${trip.origin} → ` : ""}${trip.destination}` : trip.origin, subtitle: [trip.travel_start && trip.travel_end ? `${trip.travel_start} → ${trip.travel_end}` : "Dates flexible or unset", trip.budget ? `${trip.currency || "EUR"} ${trip.budget}` : "Budget unset"].join(" · "), trip: { ...trip }, recommendations: [...recommendations], carbonResults: [...carbonResults], mockData, createdAt: now, updatedAt: now };
    setSavedItineraries((current) => [record, ...current]);
    addMessage(`Saved itinerary: ${record.title}. You can reopen it from Saved itineraries.`);
  }

  async function openRecent(record) {
    const senderId = record.sender || record.id;
    setSender(senderId);
    setRecommendations([]);
    setCarbonResults([]);
    setLibraryMode(null);
    try {
      const { messages: rebuilt, trip: rebuiltTrip } = await loadConversationFromBackend(senderId);
      setMessages(rebuilt.length ? rebuilt : [{ id: "welcome", sender: "bot", text: "This conversation is empty on the assistant's side - start chatting to pick it back up.", time: "Just now" }]);
      setTrip(rebuiltTrip);
    } catch (error) {
      setMessages(record.messages || []);
      setTrip(record.trip || EMPTY_TRIP);
      addMessage(`Showing the last saved view of this conversation - couldn't confirm it against the assistant yet. ${error.message}`);
    }
  }

  async function openSaved(record) {
    const nextSender = newSenderId();
    const trip = { ...EMPTY_TRIP, ...(record.trip || {}) };
    setSender(nextSender);
    setMessages([{ id: `welcome-${Date.now()}`, sender: "bot", text: `Reopening saved itinerary: ${record.title}…`, time: "Just now" }]);
    setTrip(trip);
    setRecommendations([]);
    setCarbonResults([]);
    setMockData(false);
    setLibraryMode(null);
    setBusy(true);
    try {
      await postToAssistant("/start_consultation", nextSender);
      await syncTripSlots(trip, nextSender);
      const payload = await postToAssistant("/generate_recommendations", nextSender);
      displayAssistantPayload(payload);
      await refreshTripFromTracker(nextSender);
    } catch (error) {
      addMessage(`Couldn't fully resume this saved itinerary. ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  function deleteLibraryRecord(id) {
    if (libraryMode === "saved") setSavedItineraries((current) => current.filter((item) => item.id !== id));
    else {
      setRecentConversations((current) => {
        const next = current.filter((item) => item.id !== id);
        try { localStorage.setItem("terra-recent-conversations", JSON.stringify(next)); localStorage.removeItem(`terra-session-${id}`); } catch {}
        return next;
      });
    }
  }

  const replies = pendingField ? [] : serverButtons;
  const hasBrief = Boolean(trip.destination || trip.origin || trip.travel_start || trip.travel_end || trip.budget || trip.sustainability_level || trip.transport_preference || trip.accommodation_preference || trip.carbon_estimate_preference);

  return <div className="app-shell">
    <header className="topbar">
      <span className="brand"><LogoMark /><span className="brand-name">terra<span>.</span></span></span>
      <div className="assistant-status-line"><i className={status === "connected" ? "dot-connected" : status === "offline" ? "dot-error" : ""} />{status === "connected" ? "Connected" : status === "offline" ? "Offline" : "Connecting…"}</div>
      <div className="topbar-actions">
        <button className="text-icon-button" onClick={() => sendMessage("start a new consultation", "＋ Start a new consultation")} type="button" title="Start a new consultation">＋ <span>New</span></button>
        <button className="text-icon-button" onClick={resetConversation} type="button" title="Clear this conversation">↻ <span>Reset</span></button>
        {!handover && <button className="text-icon-button human-handover-topbar-button" disabled={busy} onClick={() => sendMessage("/request_specialist", "Talk to a human advisor")} type="button" title="Talk to a human advisor">↗ <span>Talk to a human</span></button>}
        <button className="icon-button" onClick={() => setSettingsOpen(true)} type="button" aria-label="Connection settings" title="Connection settings">⚙</button>
      </div>
    </header>
    <main className="workspace">
      <NavRail onRecent={() => setLibraryMode("recent")} onSaved={() => setLibraryMode("saved")} recentCount={recentConversations.length} savedCount={savedItineraries.length} />
      <section className="chat-column">
        <div className="chat-feed" id="chat-feed" role="log" aria-live="polite" aria-relevant="additions text" ref={feedRef}>
          {messages.map((message) => <Message key={message.id} item={message} />)}
          {pendingField && <IntakeControl key={pendingField} field={pendingField} currency={trip.currency || "EUR"} feasibleModes={feasibleModes} budgetRange={budgetRange} travelStart={trip.travel_start} busy={busy} onChoose={(message, label, payloadOverride) => sendMessage(message, label, payloadOverride)} />}
          {messages.length === 1 && <div className="starter-actions">
            <div className={`starter-grid starter-grid-${STARTER_SETS[starterSetIndex].kind}`} key={starterSetIndex}>{STARTER_SETS[starterSetIndex].cards.map((card) => <button key={card.title} type="button" className="starter-card" onClick={() => sendMessage(card.message, STARTER_SETS[starterSetIndex].kind === "destination" ? `Planning a trip to ${card.title} ${card.icon}` : `Planning a trip - ${card.title}`)}>
              {card.icon && <span className="starter-card-flag">{card.icon}</span>}<strong>{card.title}</strong><small>{card.subtitle}</small>
            </button>)}</div>
            <div className="starter-dots">{STARTER_SETS.map((set, index) => <span key={set.kind} className={index === starterSetIndex ? "is-active" : ""} />)}</div>
          </div>}
          {replies.length > 0 && <div className={`quick-replies ${handoverPrompt ? "quick-replies-confirm" : ""}`} aria-label={handoverPrompt ? "Confirm human handover" : "Suggested responses"}>{replies.map((button, index) => <button className="quick-reply" type="button" key={`${typeof button === "string" ? button : button.title}-${index}`} onClick={() => chooseReply(button)}>{typeof button === "string" ? button : button.title || button.payload}</button>)}</div>}
          {busy && <div className="message bot-message" aria-label="Assistant is responding"><span className="message-avatar">✳</span><div className="bubble typing-indicator"><i /><i /><i /></div></div>}
        </div>
        {handover && <div className="handover-status-strip"><span className="handover-symbol">↗</span><span>Specialist handover prepared</span><span className="handover-status">READY</span></div>}
        <form className="composer" onSubmit={submitMessage}><label className="sr-only" htmlFor="message-input">Message the travel assistant</label>
          <textarea id="message-input" ref={textareaRef} rows="1" placeholder="Share a trip detail or ask a question…" autoComplete="off" value={draft} onChange={(event) => { setDraft(event.target.value); event.target.style.height = "auto"; event.target.style.height = `${Math.min(event.target.scrollHeight, 100)}px`; }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} />
          <div className="composer-footer"><span className="composer-hint"><kbd>Enter</kbd> to send <span>·</span> <kbd>Shift + Enter</kbd> for a new line</span><button className="send-button" type="submit" aria-label="Send message" disabled={busy}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 4.8 20 12 4.5 19.2l1.7-6.1L14 12l-7.8-1.1-1.7-6.1Z" /></svg></button></div>
        </form>
      </section>
      
      <aside className={`side-panel ${tripPanelOpen ? "is-floating-open" : ""}`} aria-label="Trip details">
        <div className="side-panel-heading"><span className="section-kicker">TRIP BOARD</span><button type="button" className="side-panel-close" aria-label="Close trip board" onClick={() => setTripPanelOpen(false)}>×</button></div>
        <div className="side-panel-body">
          {hasBrief ? <TripBrief trip={trip} onSaveItinerary={saveItinerary} /> : <p className="side-panel-empty">Your trip details will appear here once you start planning.</p>}
        </div>
      </aside>
      <button type="button" className={`trip-fab ${hasBrief ? "has-brief" : ""}`} aria-label="Show trip board" onClick={() => setTripPanelOpen((value) => !value)}>▣</button>
    </main>
    <SettingsDialog endpoint={endpoint} setEndpoint={(value) => { setEndpointState(value); setStatus("checking"); }} open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    <LibraryDialog mode={libraryMode} records={libraryMode === "saved" ? savedItineraries : recentConversations} onClose={() => setLibraryMode(null)} onOpenRecord={libraryMode === "saved" ? openSaved : openRecent} onDeleteRecord={deleteLibraryRecord} />
  </div>;
}

createRoot(document.getElementById("root")).render(<React.StrictMode>{window.location.pathname.startsWith("/admin") ? <AdminApp /> : <App />}</React.StrictMode>);
