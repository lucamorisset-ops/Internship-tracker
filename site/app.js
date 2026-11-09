// Tracker stages césure : site statique (GitHub Pages) branché sur Supabase.
// Pas de build, pas de framework. supabase-js est chargé à la demande depuis
// jsDelivr (version figée) ; en mode démo (?demo=1) rien n'est chargé du réseau.

const SUPABASE_JS = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm";
const PLACEHOLDER = "REMPLACER_PAR_LA_PUBLISHABLE_KEY";

const params = new URLSearchParams(location.search);
const DEMO = params.has("demo") && params.get("demo") !== "0";

/* ------------------------------------------------------------ libellés */
const STATUS = [
  ["nouvelle", "Nouvelle"], ["a_postuler", "À postuler"], ["postule", "Postulé"],
  ["entretien", "Entretien"], ["refuse", "Refusé"], ["pas_interesse", "Pas intéressé"],
];
const SLABEL = {
  ok: "Lu en entier", partiel: "Partiel", resiste: "Résiste", sans_catalogue: "Pas de catalogue",
  a_configurer: "À configurer", erreur: "Erreur",
};
const PROBLEM = ["resiste", "erreur", "partiel", "sans_catalogue", "a_configurer"];
const METHOD = { api: "API publique", html: "Page HTML", navigateur: "Navigateur robot", veille: "Veille de page" };
const TRIGGER = {
  schedule: "passage automatique", "demande du site": "demandé depuis le site",
  workflow_dispatch: "lancé à la main", manual: "lancé à la main", push: "après une mise à jour du robot",
};
const DEFAULT_WHY = {
  resiste: ["Le site refuse la lecture automatique.",
    "Ouvre le catalogue avec le bouton et regarde les offres toi-même de temps en temps. Le robot réessaie à chaque passage."],
  erreur: ["Le dernier passage a échoué sur ce site.",
    "Relance avec « Mettre à jour maintenant ». Si l'erreur revient, ouvre le catalogue pour vérifier que l'adresse marche encore."],
  partiel: ["Le robot ne lit qu'une partie du catalogue.",
    "Complète en ouvrant le catalogue avec le bouton, de temps en temps."],
  sans_catalogue: ["Le site officiel ne publie pas de liste d'offres lisible.",
    "Regarde la page de l'entreprise toi-même ou envoie une candidature spontanée."],
  a_configurer: ["Pas encore configurée : le robot n'a pas encore cherché son catalogue.",
    "Rien à faire : elle sera configurée au prochain passage (dans les 15 minutes)."],
};
const TYPES = ["Gestion d'actifs", "Equity research", "Investment specialist", "Investment analyst",
  "Private equity", "Crédit / obligataire", "Quant", "ESG / ISR", "Sales / relations investisseurs",
  "Marchés / trading"];
const TYPES_ON = 4;
const STARTS = ["Décembre 2026", "Janvier 2027", "Février 2027", "Mars 2027", "Avril 2027", "Mai 2027", "Juin 2027"];
const STARTS_ON = ["Janvier 2027", "Mars 2027"];
const TABS = ["offres", "sources", "blocages", "ajouter"];
const OFFER_COLS = "id,source_id,title,company,url,location,contract,published,published_label,start_label," +
  "relevance,reasons,status,note,first_seen,last_seen,closed,closed_on,manual";
const STALE_REQUEST_MS = 2 * 3600 * 1000;

/* ------------------------------------------------------------ outils */
const $ = (id) => document.getElementById(id);
function el(tag, cls, txt) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
}
function safeUrl(u) {
  if (!u) return null;
  try {
    const x = new URL(String(u), location.href);
    return x.protocol === "https:" || x.protocol === "http:" ? x.href : null;
  } catch { return null; }
}
function link(href, txt, cls) {
  const ok = safeUrl(href);
  if (!ok) return el("span", cls, txt);
  const a = el("a", cls, txt);
  a.href = ok; a.target = "_blank"; a.rel = "noopener";
  return a;
}
function pill(cls, txt) { return el("span", "pill " + cls, txt); }
function fold(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
function slugify(s) {
  return fold(s).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/, "");
}
function store(key, val) { try { localStorage.setItem("trk-" + key, val); } catch { /* stockage indisponible */ } }
function recall(key) { try { return localStorage.getItem("trk-" + key); } catch { return null; } }
function setMsg(n, text, cls) { if (!n) return; n.textContent = text || ""; n.className = n.className.replace(/\s*\b(ok|err)\b/g, "") + (cls ? " " + cls : ""); }
function urlList(v) {
  if (!Array.isArray(v)) return [];
  return v.map((u) => (typeof u === "string" ? u : u && (u.url || u.href))).filter(Boolean);
}

/* dates */
const pad = (n) => String(n).padStart(2, "0");
function parseDay(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}
function fmtDay(d) { return d ? `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}` : ""; }
function toDate(iso) { if (!iso) return null; const d = new Date(iso); return isNaN(d) ? null : d; }
function fmtTs(iso) { return fmtDay(toDate(iso)); }
function fmtWhen(iso) {
  const d = toDate(iso);
  if (!d) return "";
  const y = d.getFullYear() !== new Date().getFullYear() ? "/" + d.getFullYear() : "";
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}${y} à ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtTime(iso) { const d = toDate(iso); return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : ""; }
function age(d) {
  if (!d) return "";
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const n = Math.round((t - d) / 86400000);
  if (isNaN(n) || n < 0) return "";
  if (n === 0) return "aujourd'hui";
  if (n === 1) return "hier";
  if (n < 60) return `il y a ${n} j`;
  return `il y a ${Math.round(n / 30)} mois`;
}
function ago(iso) {
  const d = toDate(iso);
  if (!d) return "";
  const m = Math.round((Date.now() - d) / 60000);
  if (m < 1) return "à l'instant";
  if (m < 60) return `il y a ${m} min`;
  if (m < 48 * 60) return `il y a ${Math.round(m / 60)} h`;
  return `il y a ${Math.round(m / 1440)} j`;
}
function plural(n, one, many) { return `${n} ${n > 1 ? many : one}`; }

/* erreurs en français */
function explain(e) {
  if (!e) return "erreur inconnue";
  const msg = String(e.message || e.error_description || e);
  const code = e.code || "";
  if (code === "not_updated") return "la base n'a rien modifié (accès refusé ou ligne introuvable)";
  if (/failed to fetch|networkerror|load failed|network request failed|fetch failed/i.test(msg)) return "pas de connexion avec la base (réseau coupé ?)";
  if (code === "42501" || /permission denied|row-level security/i.test(msg)) return "accès refusé par les règles de la base";
  if (code === "23505") return "cet identifiant existe déjà";
  if (code === "PGRST301" || /jwt|expired/i.test(msg)) return "ta session a expiré : déconnecte-toi puis reconnecte-toi";
  if (/rate limit|only request this after|too many/i.test(msg)) return "trop de demandes rapprochées : attends une minute puis réessaie";
  return msg.length > 220 ? msg.slice(0, 220) + "…" : msg;
}

/* ------------------------------------------------------------ état */
const state = { sources: [], offers: [], runs: [], lastRun: null, pending: [], loaded: false };
const ui = {
  tab: "offres", filter: recall("filter") || "cible", sort: recall("sort") || "rank",
  showClosed: recall("closed") === "1", q: "", confirmDelete: null, srcMsg: {}, runMsg: null, flash: null,
};
if (!["cible", "proche", "todo", "all"].includes(ui.filter)) ui.filter = "cible";
if (!["rank", "recent", "old"].includes(ui.sort)) ui.sort = "rank";
const drafts = new Map(); // id d'offre -> { value, error } : notes pas encore enregistrées
const flashes = new Map(); // id d'offre -> { text, cls, at } : retour « Enregistré » qui survit à un rafraîchissement
function flashFor(id) {
  const f = flashes.get(id);
  if (!f) return null;
  if (Date.now() - f.at > 6000) { flashes.delete(id); return null; }
  return f;
}
let api = null;           // couche données (Supabase ou démo)
let sb = null;            // client Supabase
let userId = null;
let refreshing = false, refreshAgain = false, lastRefresh = 0;
let pollTimer = null, channel = null, rtTimer = null;
const sourceById = () => new Map(state.sources.map((s) => [s.id, s]));

/* ------------------------------------------------------------ vues */
const VIEWS = ["loading", "setup", "login", "denied", "app"];
function showView(v) {
  VIEWS.forEach((x) => { $("view-" + x).hidden = x !== v; });
  $("who").hidden = !(v === "app" || v === "denied");
}
function setBanner(text, cls = "err") {
  const b = $("banner");
  b.hidden = !text;
  b.textContent = text || "";
  b.className = "banner " + cls;
}
function setWho(email) {
  $("who-email").textContent = email || "";
  $("denied-email").textContent = email || "";
  $("demo-pill").hidden = !DEMO;
}

/* ------------------------------------------------------------ onglets */
function showTab(id, focus) {
  if (!TABS.includes(id)) id = "offres";
  ui.tab = id;
  TABS.forEach((t) => {
    $(t).hidden = t !== id;
    const b = $("tab-" + t);
    b.setAttribute("aria-selected", t === id ? "true" : "false");
    b.tabIndex = t === id ? 0 : -1;
  });
  if (focus) $("tab-" + id).focus();
  store("tab", id);
  // Ne jamais toucher à un hash de connexion (#access_token=…, #error=…) : supabase-js doit le lire.
  if (/[=&]/.test(location.hash)) return;
  try { history.replaceState(null, "", location.pathname + location.search + "#" + id); } catch { /* ignore */ }
}
function bindTabs() {
  TABS.forEach((t, i) => {
    const b = $("tab-" + t);
    b.addEventListener("click", () => showTab(t));
    b.addEventListener("keydown", (ev) => {
      let j = null;
      if (ev.key === "ArrowRight") j = (i + 1) % TABS.length;
      else if (ev.key === "ArrowLeft") j = (i - 1 + TABS.length) % TABS.length;
      else if (ev.key === "Home") j = 0;
      else if (ev.key === "End") j = TABS.length - 1;
      if (j != null) { ev.preventDefault(); showTab(TABS[j], true); }
    });
  });
  const h = (location.hash || "").slice(1);
  showTab(TABS.includes(h) ? h : recall("tab") || "offres");
}

/* ------------------------------------------------------------ rendu protégé */
// Ne pas reconstruire une liste pendant que l'utilisateur y tape ou choisit : on
// attend qu'il quitte le champ.
const dirty = new Set();
function busy(box) {
  const a = document.activeElement;
  return !!(a && box.contains(a) && a.matches("textarea, select, input[type=text], input[type=search]"));
}
function guarded(id, fn) {
  const box = $(id);
  if (busy(box)) { dirty.add(id); return; }
  dirty.delete(id);
  fn(box);
}
function watchFocus(id, fn) {
  $(id).addEventListener("focusout", (ev) => {
    if (ev.relatedTarget && $(id).contains(ev.relatedTarget)) return;
    setTimeout(() => { if (dirty.has(id)) guarded(id, fn); }, 0);
  });
}

/* ------------------------------------------------------------ offres */
const companyOf = (o, map) => o.company || (map.get(o.source_id) || {}).company || o.source_id || "";
function inFilter(o, f) {
  if (f === "cible") return o.relevance === "cible";
  if (f === "proche") return o.relevance === "proche";
  if (f === "todo") return (o.status || "nouvelle") === "nouvelle" && o.relevance !== "exclue";
  return true;
}
function baseVisible(o, map) {
  if (o.closed && !ui.showClosed) return false;
  const q = fold(ui.q.trim());
  if (q && !fold((o.title || "") + " " + companyOf(o, map)).includes(q)) return false;
  return true;
}
const REL_ORDER = { cible: 0, proche: 1, exclue: 2 };
function sortOffers(list, map) {
  const rankOf = (o) => { const s = map.get(o.source_id); return s && s.rank != null ? s.rank : 9999; };
  const seen = (o) => (o.first_seen || "");
  if (ui.sort === "rank") {
    return list.slice().sort((a, b) =>
      (REL_ORDER[a.relevance] ?? 3) - (REL_ORDER[b.relevance] ?? 3) ||
      rankOf(a) - rankOf(b) ||
      (b.published || "").localeCompare(a.published || "") ||
      seen(b).localeCompare(seen(a)));
  }
  const dir = ui.sort === "recent" ? -1 : 1;
  return list.slice().sort((a, b) => {
    const x = a.published || "", y = b.published || "";
    if (!x && !y) return seen(b).localeCompare(seen(a));
    if (!x) return 1;
    if (!y) return -1;
    return dir * x.localeCompare(y) || rankOf(a) - rankOf(b);
  });
}
function pubNode(o) {
  const d = parseDay(o.published);
  if (d) {
    const a = age(d);
    return el("span", "pub", "Publiée le " + fmtDay(d) + (a ? " · " + a : ""));
  }
  if (o.published_label) return el("span", null, "Publication : " + o.published_label);
  return el("span", null, "Date non affichée par le site");
}

function renderFilterButtons(base) {
  document.querySelectorAll("#offres .filters button").forEach((b) => {
    const f = b.dataset.f;
    b.setAttribute("aria-pressed", f === ui.filter ? "true" : "false");
    b.querySelector(".n").textContent = state.loaded ? String(base.filter((o) => inFilter(o, f)).length) : "";
  });
}
function renderOffers() {
  const map = sourceById();
  renderFilterButtons(state.offers.filter((o) => baseVisible(o, map)));
  guarded("offer-list", buildOffers);
}
function buildOffers(box) {
  const map = sourceById();
  const base = state.offers.filter((o) => baseVisible(o, map));
  renderFilterButtons(base);
  box.textContent = "";
  if (!state.loaded) { box.appendChild(el("div", "empty", "Chargement des offres…")); return; }
  const list = sortOffers(base.filter((o) => inFilter(o, ui.filter)), map);
  if (!list.length) {
    let t = "Aucune offre dans ce filtre pour l'instant.";
    if (!state.offers.length) t = "Aucune offre enregistrée pour l'instant. Elles apparaîtront ici après le prochain passage du robot.";
    else if (ui.q.trim()) t = `Aucune offre ne correspond à « ${ui.q.trim()} » dans ce filtre.`;
    box.appendChild(el("div", "empty", t));
    return;
  }
  const frag = document.createDocumentFragment();
  list.forEach((o) => frag.appendChild(offerCard(o, map)));
  box.appendChild(frag);
}
function offerCard(o, map) {
  const status = o.status || "nouvelle";
  const row = el("article", "offer" + (o.relevance === "cible" ? " cible" : "") + (o.closed ? " closed" : ""));
  const main = el("div", "main");
  const t = el("div", "t");
  t.appendChild(link(o.url, o.title || "(offre sans titre)"));
  main.appendChild(t);
  const m = el("div", "meta");
  m.appendChild(el("span", "co", companyOf(o, map)));
  if (o.location) m.appendChild(el("span", null, o.location));
  if (o.contract) m.appendChild(el("span", null, o.contract));
  if (o.start_label) m.appendChild(el("span", null, "Début : " + o.start_label));
  m.appendChild(pubNode(o));
  if (o.first_seen) m.appendChild(el("span", "mono", "Repérée le " + fmtTs(o.first_seen)));
  if (o.relevance === "cible") m.appendChild(pill("p-cible", "Ciblée"));
  else if (o.relevance === "proche") m.appendChild(pill("p-proche", "À vérifier"));
  else if (o.relevance === "exclue") m.appendChild(pill("p-exclue", "Exclue"));
  if (o.closed) {
    const d = parseDay(o.closed_on);
    m.appendChild(pill("p-closed", "Plus en ligne" + (d ? " depuis le " + fmtDay(d) : "")));
  } else if (status === "nouvelle") m.appendChild(pill("p-new", "Nouvelle"));
  if (o.manual) m.appendChild(pill("p-manual", "Ajoutée à la main"));
  main.appendChild(m);
  if (o.reasons) main.appendChild(el("p", "reasons", o.reasons));
  row.appendChild(main);

  // statut de suivi
  const sbox = el("div", "statusbox");
  const sel = el("select");
  sel.setAttribute("aria-label", "Ton suivi pour : " + (o.title || "offre"));
  const known = STATUS.some((s) => s[0] === status);
  (known ? STATUS : STATUS.concat([[status, status]])).forEach(([v, l]) => {
    const op = el("option", null, l); op.value = v; if (v === status) op.selected = true; sel.appendChild(op);
  });
  const fl = flashFor(o.id);
  const sst = el("span", "save-state" + (fl && fl.cls ? " " + fl.cls : ""), fl ? fl.text : "");
  sst.setAttribute("role", "status");
  sel.addEventListener("change", () => saveStatus(o.id, sel, sst));
  sbox.append(sel, sst);
  row.appendChild(sbox);

  // note personnelle
  const nbox = el("div", "notebox");
  const ta = el("textarea");
  ta.rows = 1;
  ta.placeholder = "Ta note (enregistrée quand tu quittes le champ)";
  ta.setAttribute("aria-label", "Ta note sur : " + (o.title || "offre"));
  const draft = drafts.get(o.id);
  ta.value = draft ? draft.value : o.note || "";
  const nst = el("span", "save-state" + (draft && draft.error ? " err" : ""), draft && draft.error ? draft.error : "");
  nst.id = "ns-" + o.id;
  nst.setAttribute("role", "status");
  ta.addEventListener("input", () => autosize(ta));
  ta.addEventListener("focus", () => autosize(ta));
  ta.addEventListener("blur", () => saveNote(o.id, ta));
  nbox.append(ta, nst);
  row.appendChild(nbox);
  return row;
}
function autosize(ta) {
  if (CSS.supports && CSS.supports("field-sizing", "content")) return;
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight + 2, 240) + "px";
}
function offerById(id) { return state.offers.find((x) => x.id === id); }

async function saveStatus(id, sel, sst) {
  const o = offerById(id);
  const prev = (o && o.status) || "nouvelle";
  const next = sel.value;
  // pas de disabled : un champ désactivé perd le focus et la carte disparaîtrait du filtre en cours
  sel.setAttribute("aria-busy", "true");
  setMsg(sst, "Enregistrement…");
  try {
    await api.updateOffer(id, { status: next });
    if (o) o.status = next;
    flashes.set(id, { text: "Enregistré", cls: "ok", at: Date.now() });
    setMsg(sst, "Enregistré", "ok");
    renderCounts();
    refresh();
  } catch (e) {
    sel.value = prev;
    flashes.set(id, { text: "Non enregistré : " + explain(e) + ".", cls: "err", at: Date.now() });
    setMsg(sst, "Non enregistré : " + explain(e) + ".", "err");
  } finally {
    sel.removeAttribute("aria-busy");
  }
}
async function saveNote(id, ta) {
  const o = offerById(id);
  const value = ta.value;
  const clean = value.trim() ? value.trim() : null;
  const cur = (o && o.note) || null;
  const nst = () => document.getElementById("ns-" + id);
  if ((clean || "") === (cur || "")) {
    if (drafts.has(id)) { drafts.delete(id); setMsg(nst(), ""); }
    return;
  }
  drafts.set(id, { value });
  setMsg(nst(), "Enregistrement de la note…");
  try {
    await api.updateOffer(id, { note: clean });
    const cur2 = offerById(id);
    if (cur2) cur2.note = clean;
    drafts.delete(id);
    setMsg(nst(), "Note enregistrée", "ok");
    refresh();
  } catch (e) {
    const err = "Note non enregistrée : " + explain(e) + ". Ton texte est gardé ici : quitte de nouveau le champ pour réessayer.";
    drafts.set(id, { value, error: err });
    setMsg(nst(), err, "err");
  }
}

/* ------------------------------------------------------------ chiffres */
function renderCounts() {
  const live = state.offers.filter((o) => !o.closed);
  const enabled = state.sources.filter((s) => s.enabled !== false);
  const L = state.loaded;
  $("n-cible").textContent = L ? live.filter((o) => o.relevance === "cible").length : "–";
  $("n-proche").textContent = L ? live.filter((o) => o.relevance === "proche").length : "–";
  $("n-src").textContent = L ? enabled.filter((s) => s.status === "ok" || s.status === "partiel").length + " / " + enabled.length : "–";
  $("n-cand").textContent = L ? state.offers.filter((o) => o.status === "postule" || o.status === "entretien").length : "–";
  $("c-offres").textContent = L ? String(live.filter((o) => o.relevance !== "exclue").length || "") : "";
  $("c-sources").textContent = L ? String(state.sources.length || "") : "";
  $("c-blocages").textContent = L ? String(state.sources.filter(isProblem).length || "") : "";
}
const isProblem = (s) => s.enabled !== false && PROBLEM.includes(s.status || "a_configurer");

/* ------------------------------------------------------------ sources */
function kv(dl, k, v) {
  if (v == null || v === "") return;
  dl.appendChild(el("dt", null, k));
  const dd = el("dd");
  if (typeof v === "string") dd.textContent = v; else dd.appendChild(v);
  dl.appendChild(dd);
}
function urlsNode(urls) {
  const ul = el("ul", "urls");
  urls.forEach((u) => { const li = el("li"); li.appendChild(link(u, u, "url")); ul.appendChild(li); });
  return ul;
}
function criteriaText(cr) {
  if (!cr || typeof cr !== "object") return "";
  const parts = [
    (cr.types || []).join(", "), (cr.starts || []).join(", "), cr.cities || "",
    cr.keywords ? "Mots-clés : " + cr.keywords : "",
  ].filter(Boolean);
  return parts.join(" · ");
}
function lastPassText(s) {
  if (!s.last_checked) return "Pas encore lue par le robot";
  const bits = [fmtWhen(s.last_checked)];
  if (s.last_method) bits.push(METHOD[s.last_method] || s.last_method);
  if (typeof s.last_count === "number") bits.push(plural(s.last_count, "offre lue", "offres lues"));
  return bits.join(" · ");
}
function catalogNode(s) {
  const href = safeUrl(s.catalog_url);
  if (!href) return null;
  const w = el("div", "cat");
  const b = link(href, "Ouvrir le catalogue", "btn ghost sm");
  b.setAttribute("aria-label", "Ouvrir le catalogue officiel de " + s.company);
  w.append(b, el("span", "url", s.catalog_url));
  return w;
}

function renderSources() { guarded("source-list", buildSources); }
function buildSources(box) {
  box.textContent = "";
  if (!state.loaded) { box.appendChild(el("div", "empty", "Chargement des sources…")); return; }
  if (!state.sources.length) { box.appendChild(el("div", "empty", "Aucune source enregistrée.")); return; }
  const frag = document.createDocumentFragment();
  state.sources.forEach((s) => frag.appendChild(sourceCard(s)));
  box.appendChild(frag);
  if (ui.focusConfirm) { ui.focusConfirm = false; const c = document.getElementById("confirm-yes"); if (c) c.focus(); }
}
function sourceCard(s) {
  const enabled = s.enabled !== false;
  const c = el("article", "src" + (enabled ? "" : " paused"));
  const top = el("div", "src-top");
  top.appendChild(el("h3", null, s.company || s.id));
  const st = s.status || "a_configurer";
  top.appendChild(pill("s-" + st, SLABEL[st] || st));
  if (!enabled) top.appendChild(pill("s-pause", "En pause"));
  if (s.last_method) {
    top.appendChild(s.last_method === "navigateur"
      ? pill("s-navigateur", "Navigateur robot")
      : el("span", "foot", "Lecture cloud · " + (METHOD[s.last_method] || s.last_method)));
  }
  if (typeof s.last_count === "number") top.appendChild(el("span", "foot mono", plural(s.last_count, "offre lue", "offres lues")));
  const sw = el("label", "switch");
  const cb = el("input"); cb.type = "checkbox"; cb.checked = enabled;
  cb.setAttribute("aria-label", "Suivre " + (s.company || s.id) + " à chaque passage");
  cb.addEventListener("change", () => toggleSource(s, cb));
  sw.append(cb, document.createTextNode("Suivie"));
  top.appendChild(sw);
  c.appendChild(top);

  const dl = el("dl", "kv");
  kv(dl, "Catalogue", catalogNode(s) || "À trouver au prochain passage");
  kv(dl, "Filtres appliqués", s.filters || "");
  kv(dl, "Tes critères", criteriaText(s.criteria) || "Critères généraux du tracker");
  kv(dl, "Dernier passage", lastPassText(s));
  const used = urlList(s.last_urls);
  kv(dl, `URL lues au dernier passage (${used.length})`, used.length ? urlsNode(used) : "Aucune pour l'instant");
  const configured = urlList(s.read_urls).filter((u) => !used.includes(u));
  if (configured.length) kv(dl, "URL configurées", urlsNode(configured));
  if (st !== "ok" && s.reason) kv(dl, "Pourquoi", s.reason);
  kv(dl, "Remarque", s.note || "");
  c.appendChild(dl);

  if (s.last_error) {
    const d = el("details");
    d.appendChild(el("summary", null, "Dernière erreur technique"));
    d.appendChild(el("pre", "err", s.last_error));
    c.appendChild(d);
  }

  const m = ui.srcMsg[s.id];
  if (s.added_from_site || m) {
    const act = el("div", "src-actions");
    if (s.added_from_site) {
      act.appendChild(el("span", "foot", "Ajoutée depuis le site" + (s.created_at ? " le " + fmtTs(s.created_at) : "")));
      if (ui.confirmDelete === s.id) {
        const box = el("div", "confirm");
        box.setAttribute("role", "group");
        box.setAttribute("aria-label", "Confirmer la suppression");
        box.appendChild(el("span", null, `Supprimer ${s.company} et toutes ses offres du tracker ?`));
        const yes = el("button", "btn danger solid sm", "Oui, supprimer");
        yes.type = "button"; yes.id = "confirm-yes";
        yes.addEventListener("click", () => doDelete(s, yes));
        const no = el("button", "btn ghost sm", "Annuler");
        no.type = "button";
        no.addEventListener("click", () => { ui.confirmDelete = null; renderSources(); });
        box.append(yes, no);
        act.appendChild(box);
      } else {
        const del = el("button", "btn danger sm", "Supprimer");
        del.type = "button";
        del.setAttribute("aria-label", "Supprimer " + s.company);
        del.addEventListener("click", () => { ui.confirmDelete = s.id; ui.focusConfirm = true; renderSources(); });
        act.appendChild(del);
      }
    }
    if (m) { const p = el("span", "msg " + (m.cls || ""), m.text); p.setAttribute("role", "status"); act.appendChild(p); }
    c.appendChild(act);
  }
  return c;
}
async function toggleSource(s, cb) {
  const want = cb.checked;
  cb.disabled = true;
  ui.srcMsg[s.id] = { text: want ? "Réactivation…" : "Mise en pause…" };
  try {
    await api.updateSource(s.id, { enabled: want });
    s.enabled = want;
    ui.srcMsg[s.id] = { text: want ? "Suivie à nouveau à chaque passage." : "En pause : le robot ne la lit plus.", cls: "ok" };
  } catch (e) {
    cb.checked = !want;
    ui.srcMsg[s.id] = { text: "Changement non enregistré : " + explain(e) + ".", cls: "err" };
  }
  cb.disabled = false;
  renderAll();
  refresh();
}
async function doDelete(s, btn) {
  btn.disabled = true;
  ui.srcMsg[s.id] = { text: "Suppression…" };
  try {
    await api.deleteSource(s.id);
    ui.confirmDelete = null;
    delete ui.srcMsg[s.id];
    setMsg($("src-msg"), `${s.company} a été supprimée du suivi.`, "ok");
    state.sources = state.sources.filter((x) => x.id !== s.id);
    state.offers = state.offers.filter((o) => o.source_id !== s.id);
    renderAll();
    refresh();
  } catch (e) {
    ui.srcMsg[s.id] = { text: "Suppression impossible : " + explain(e) + ".", cls: "err" };
    btn.disabled = false;
    renderSources();
  }
}

/* ------------------------------------------------------------ sites qui résistent */
function renderBlocks() {
  const box = $("block-list");
  box.textContent = "";
  if (!state.loaded) { box.appendChild(el("div", "empty", "Chargement…")); return; }
  const list = state.sources.filter(isProblem);
  if (!list.length) { box.appendChild(el("div", "empty", "Tous les sites sont lisibles.")); return; }
  list.forEach((s) => {
    const st = s.status || "a_configurer";
    const c = el("article", "block " + st);
    const top = el("div", "src-top");
    top.appendChild(el("h3", null, s.company || s.id));
    top.appendChild(pill("s-" + st, SLABEL[st] || st));
    if (s.last_method === "navigateur") top.appendChild(pill("s-navigateur", "Navigateur robot"));
    c.appendChild(top);
    const dl = el("dl", "why");
    const def = DEFAULT_WHY[st] || ["Raison non renseignée.", ""];
    kv(dl, "Pourquoi", s.reason || def[0]);
    kv(dl, "Ce que tu peux faire", s.fix || def[1]);
    kv(dl, "Catalogue", catalogNode(s) || "Pas encore trouvé");
    kv(dl, "Dernier passage", lastPassText(s));
    const used = urlList(s.last_urls);
    kv(dl, `URL essayées (${used.length})`, used.length ? urlsNode(used) : "Aucune pour l'instant");
    c.appendChild(dl);
    if (s.last_error) {
      const d = el("details");
      d.appendChild(el("summary", null, "Détail technique de l'erreur"));
      d.appendChild(el("pre", "err", s.last_error));
      c.appendChild(d);
    }
    box.appendChild(c);
  });
}

/* ------------------------------------------------------------ barre de passage */
function lastRunInfo() {
  if (state.lastRun && (state.lastRun.finished_at || state.lastRun.started_at)) return state.lastRun;
  return state.runs[0] || null;
}
function totalsText(t) {
  if (!t) return "";
  const bits = [];
  if (t.sources != null) bits.push(`${t.ok ?? 0}/${t.sources} sources lues`);
  if (t.resiste) bits.push(plural(t.resiste, "résiste", "résistent"));
  if (t.erreur) bits.push(`${t.erreur} en erreur`);
  bits.push(plural(t.new || 0, "nouvelle offre", "nouvelles offres"));
  if (t.closed) bits.push(plural(t.closed, "offre fermée", "offres fermées"));
  return bits.join(" · ");
}
const triggerText = (t) => (t ? TRIGGER[t] || t : "");
function pendingInfo() {
  const p = state.pending.slice().sort((a, b) => (a.requested_at || "").localeCompare(b.requested_at || ""));
  if (!p.length) return null;
  const oldest = p[0];
  const stale = Date.now() - (toDate(oldest.requested_at) || new Date()).getTime() > STALE_REQUEST_MS;
  return { count: p.length, oldest, stale };
}
function renderRun() {
  const dot = $("run-dot"), title = $("run-title"), det = $("run-detail"), pend = $("run-pending");
  const btn = $("refresh"), msg = $("refresh-msg");
  const lr = lastRunInfo();
  const p = pendingInfo();
  dot.className = "dot";
  if (!state.loaded) { title.textContent = "Chargement…"; det.textContent = ""; }
  else if (lr) {
    const when = lr.finished_at || lr.started_at;
    title.textContent = "Dernier passage : " + fmtWhen(when) + " (" + ago(when) + ")";
    det.textContent = [totalsText(lr.totals), triggerText(lr.trigger)].filter(Boolean).join(" · ");
    const t = lr.totals || {};
    dot.className = "dot " + (t.resiste || t.erreur ? "warn" : "ok");
  } else { title.textContent = "Aucun passage enregistré"; det.textContent = "Le robot n'a pas encore tourné."; }

  if (p) {
    pend.hidden = false;
    const n = p.count > 1 ? `${p.count} demandes en attente` : "1 demande en attente";
    pend.textContent = p.stale
      ? `${n} depuis le ${fmtWhen(p.oldest.requested_at)} : le robot ne semble pas tourner. Regarde l'onglet Actions du dépôt GitHub.`
      : `${n} depuis ${fmtTime(p.oldest.requested_at)} : le robot passe dans les 15 minutes.`;
    if (!p.stale) dot.className = "dot run";
  } else pend.hidden = true;

  btn.disabled = !state.loaded || ui.runBusy || (p && !p.stale);
  if (ui.runMsg) setMsg(msg, ui.runMsg.text, ui.runMsg.cls);
  else setMsg(msg, p && !p.stale ? "Demande déjà envoyée : le bouton revient après le passage." : "");
  renderHistory();
}
function renderHistory() {
  const box = $("run-list");
  box.textContent = "";
  const runs = state.runs.slice(0, 10);
  if (!runs.length) { box.appendChild(el("p", "foot", "Aucun passage enregistré pour l'instant.")); return; }
  runs.forEach((r) => {
    const d = el("details", "run");
    const when = r.finished_at || r.started_at;
    d.appendChild(el("summary", null, [fmtWhen(when), triggerText(r.trigger), totalsText(r.totals)].filter(Boolean).join(" · ")));
    const ul = el("ul", "rep");
    const rep = Array.isArray(r.report) ? r.report : [];
    if (!rep.length) ul.appendChild(el("li", "foot", "Pas de détail pour ce passage."));
    rep.forEach((it) => {
      const li = el("li");
      const line = el("div", "line");
      line.appendChild(el("b", null, it.company || it.source || "?"));
      const st = it.status || "ok";
      line.appendChild(pill("s-" + st, SLABEL[st] || st));
      const nums = [plural(it.found || 0, "trouvée", "trouvées"), plural(it.new || 0, "nouvelle", "nouvelles")];
      if (it.hits) nums.push(plural(it.hits, "intéressante", "intéressantes"));
      if (it.closed) nums.push(plural(it.closed, "fermée", "fermées"));
      line.appendChild(el("span", "foot mono", nums.join(" · ")));
      if (it.method) line.appendChild(el("span", "foot", METHOD[it.method] || it.method));
      li.appendChild(line);
      if (it.reason) li.appendChild(el("span", "foot", it.reason));
      if (it.error && !it.reason) li.appendChild(el("span", "foot", it.error));
      const urls = urlList(it.urls).concat(urlList(it.details));
      if (urls.length) li.appendChild(urlsNode(urls));
      ul.appendChild(li);
    });
    d.appendChild(ul);
    box.appendChild(d);
  });
}
async function requestFullRun() {
  const btn = $("refresh");
  ui.runBusy = true;
  btn.disabled = true;
  ui.runMsg = { text: "Envoi de la demande…" };
  renderRun();
  try {
    await api.requestRun(null);
    ui.runMsg = { text: "Demande envoyée : le robot passe dans les 15 minutes", cls: "ok" };
    state.pending = state.pending.concat([{ id: -1, requested_at: new Date().toISOString(), sources: null }]);
  } catch (e) {
    ui.runMsg = { text: "La demande n'a pas pu être envoyée : " + explain(e) + ".", cls: "err" };
  }
  ui.runBusy = false;
  renderRun();
  refresh();
}

/* ------------------------------------------------------------ ajout d'une entreprise */
function buildForm() {
  const tbox = $("a-types"), sbox = $("a-starts");
  TYPES.forEach((t, i) => tbox.appendChild(checkLabel("a-type", t, i < TYPES_ON)));
  STARTS.forEach((s) => sbox.appendChild(checkLabel("a-start", s, STARTS_ON.includes(s))));
  $("addform").addEventListener("submit", onAdd);
}
function checkLabel(name, value, on) {
  const l = el("label");
  const i = el("input"); i.type = "checkbox"; i.name = name; i.value = value; i.checked = on;
  l.append(i, document.createTextNode(value));
  return l;
}
const checkedValues = (name) => Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map((x) => x.value);
async function onAdd(ev) {
  ev.preventDefault();
  const amsg = $("a-msg"), abtn = $("a-submit");
  const name = $("a-company").value.trim();
  const raw = $("a-url").value.trim();
  if (!name) { setMsg(amsg, "Indique le nom de l'entreprise.", "err"); $("a-company").focus(); return; }
  let href = null;
  if (raw) {
    let u = null;
    try { u = new URL(/^[a-z]+:\/\//i.test(raw) ? raw : "https://" + raw); } catch { u = null; }
    if (!u || !/^https?:$/.test(u.protocol) || !u.hostname.includes(".")) {
      setMsg(amsg, "Le lien doit être une adresse complète, par exemple https://www.entreprise.com/carrieres", "err");
      $("a-url").focus(); return;
    }
    if (/(^|\.)(jobteaser|linkedin|indeed|welcometothejungle|glassdoor)\./i.test(u.hostname)) {
      setMsg(amsg, "Ce lien mène à un site d'annonces, pas au site officiel de l'entreprise. Indique sa page carrières officielle, ou laisse vide : le robot la cherchera.", "err");
      $("a-url").focus(); return;
    }
    href = u.href;
  }
  const types = checkedValues("a-type"), starts = checkedValues("a-start");
  if (!types.length) { setMsg(amsg, "Coche au moins un type de stage.", "err"); return; }
  if (!starts.length) { setMsg(amsg, "Coche au moins un mois de démarrage.", "err"); return; }

  const base = slugify(name) || "entreprise";
  const taken = new Set(state.sources.map((s) => s.id));
  let n = 2, id = base;
  while (taken.has(id)) id = `${base}-${n++}`;
  const rank = state.sources.reduce((m, s) => Math.max(m, s.rank || 0), 0) + 1;
  const row = {
    id, company: name, rank, kind: "auto",
    params: { url: href }, catalog_url: href,
    criteria: { types, starts, keywords: $("a-kw").value.trim(), cities: $("a-city").value.trim() },
    status: "a_configurer", added_from_site: true,
  };
  abtn.disabled = true;
  setMsg(amsg, "Ajout en cours…");
  try {
    for (let attempt = 0; ; attempt++) {
      try { await api.insertSource(row); break; } catch (e) {
        if (e && e.code === "23505" && attempt < 5) { row.id = `${base}-${n++}`; continue; }
        throw e;
      }
    }
  } catch (e) {
    setMsg(amsg, "L'ajout a échoué : " + explain(e) + ".", "err");
    abtn.disabled = false;
    return;
  }
  let text = "Ajoutée. Le robot la cherchera au prochain passage (dans les 15 minutes).", cls = "ok";
  try { await api.requestRun([row.id]); } catch (e) {
    text = "Ajoutée, mais la demande de passage n'a pas pu être envoyée (" + explain(e) + ") : le robot la cherchera au prochain passage automatique.";
  }
  setMsg(amsg, text, cls);
  $("a-company").value = ""; $("a-url").value = ""; $("a-kw").value = "";
  abtn.disabled = false;
  state.sources = state.sources.concat([Object.assign({ enabled: true, created_at: new Date().toISOString() }, row)]);
  renderAll();
  refresh();
}

/* ------------------------------------------------------------ chargement */
function renderAll() {
  renderCounts();
  renderOffers();
  renderSources();
  renderBlocks();
  renderRun();
}
async function refresh() {
  if (!api) return false;
  if (refreshing) { refreshAgain = true; return false; }
  refreshing = true;
  let ok = false;
  try {
    const d = await api.loadAll();
    Object.assign(state, d, { loaded: true });
    if (state.pending.length === 0 && ui.runMsg && ui.runMsg.cls === "ok") ui.runMsg = null;
    setBanner("");
    ok = true;
  } catch (e) {
    setBanner("Impossible de charger les données : " + explain(e) + ". Nouvel essai automatique dans une minute.");
  } finally {
    refreshing = false;
    lastRefresh = Date.now();
  }
  renderAll();
  if (refreshAgain) { refreshAgain = false; return refresh(); }
  return ok;
}
function startLive() {
  stopLive();
  pollTimer = setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 60000);
  if (sb) {
    // Temps réel : actif seulement si les tables sont dans la publication supabase_realtime.
    // Sinon rien ne se passe et le rafraîchissement toutes les 60 s prend le relais.
    const later = () => { clearTimeout(rtTimer); rtTimer = setTimeout(refresh, 1500); };
    try {
      channel = sb.channel("tracker-db");
      ["offers", "sources", "runs", "run_requests", "meta"].forEach((table) =>
        channel.on("postgres_changes", { event: "*", schema: "public", table }, later));
      channel.subscribe();
    } catch { channel = null; }
  }
}
function stopLive() {
  clearInterval(pollTimer); pollTimer = null;
  clearTimeout(rtTimer);
  if (channel && sb) { try { sb.removeChannel(channel); } catch { /* ignore */ } }
  channel = null;
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.loaded && Date.now() - lastRefresh > 20000) refresh();
});

/* ------------------------------------------------------------ couche Supabase */
function makeSupabaseApi(client) {
  const check = ({ data, error }) => { if (error) throw error; return data; };
  const one = (data) => {
    if (!data || !data.length) throw Object.assign(new Error("not_updated"), { code: "not_updated" });
  };
  async function allOffers() {
    const out = [];
    for (let from = 0; ; from += 1000) {
      const page = check(await client.from("offers").select(OFFER_COLS).order("id").range(from, from + 999));
      out.push(...page);
      if (page.length < 1000) return out;
    }
  }
  return {
    async isAllowed() {
      const { data, error } = await client.rpc("is_allowed");
      if (error) return null;
      return data === true;
    },
    async loadAll() {
      const [sources, offers, runs, meta, pending] = await Promise.all([
        client.from("sources").select("*").order("rank", { ascending: true, nullsFirst: false }).then(check),
        allOffers(),
        client.from("runs").select("*").order("id", { ascending: false }).limit(10).then(check),
        client.from("meta").select("key,value").eq("key", "last_run").then(check),
        client.from("run_requests").select("id,requested_at,sources").is("done_at", null).order("requested_at").then(check),
      ]);
      return { sources, offers, runs, lastRun: (meta[0] && meta[0].value) || null, pending };
    },
    async updateOffer(id, fields) { one(check(await client.from("offers").update(fields).eq("id", id).select("id"))); },
    async insertSource(row) { check(await client.from("sources").insert(row)); },
    async updateSource(id, fields) { one(check(await client.from("sources").update(fields).eq("id", id).select("id"))); },
    async deleteSource(id) { one(check(await client.from("sources").delete().eq("id", id).select("id"))); },
    async requestRun(sources) { check(await client.from("run_requests").insert({ sources })); },
  };
}

/* ------------------------------------------------------------ connexion */
function urlAuthError() {
  const h = new URLSearchParams((location.hash || "").replace(/^#/, ""));
  const q = new URLSearchParams(location.search);
  const code = h.get("error_code") || q.get("error_code") || h.get("error") || q.get("error");
  if (!code) return null;
  const desc = h.get("error_description") || q.get("error_description") || "";
  try { history.replaceState(null, "", location.pathname + (DEMO ? location.search : "")); } catch { /* ignore */ }
  if (/expired|invalid/i.test(code + " " + desc)) return "Ce lien de connexion a expiré ou a déjà servi. Demande-en un nouveau ci-dessous.";
  return "La connexion n'a pas abouti (" + (desc || code) + "). Demande un nouveau lien.";
}
function keyProblem(key) {
  if (!key || key === PLACEHOLDER) return "La clé publique de Supabase n'est pas encore renseignée dans site/config.js.";
  if (/^sb_secret_/.test(key)) return "ATTENTION : site/config.js contient la clé SECRÈTE. Remplace-la tout de suite par la publishable key, puis régénère la clé secrète dans Supabase (elle est maintenant publique).";
  if (/^eyJ/.test(key)) {
    try {
      const p = JSON.parse(atob(key.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      if (p.role === "service_role") return "ATTENTION : site/config.js contient la clé service_role (secrète). Remplace-la par la publishable key et régénère la clé secrète dans Supabase.";
    } catch { /* clé anon classique */ }
  }
  return null;
}
function showSetup(reason) {
  $("setup-reason").textContent = reason;
  $("setup-url").textContent = location.origin + location.pathname;
  showView("setup");
}
let loginNotice = null;
function showLogin() {
  stopLive();
  state.loaded = false;
  setBanner("");
  showView("login");
  const m = $("login-msg");
  if (loginNotice) { setMsg(m, loginNotice, "err"); loginNotice = null; }
}
function bindLogin() {
  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const email = $("login-email").value.trim();
    const m = $("login-msg"), b = $("login-submit");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setMsg(m, "Indique une adresse e-mail valide.", "err"); $("login-email").focus(); return; }
    b.disabled = true;
    setMsg(m, "Envoi du lien…");
    try {
      if (DEMO) await new Promise((r) => setTimeout(r, 200));
      else {
        const { error } = await sb.auth.signInWithOtp({ email, options: { emailRedirectTo: location.origin + location.pathname } });
        if (error) throw error;
      }
      setMsg(m, "Lien envoyé, ouvre ton e-mail sur cet appareil.", "ok");
    } catch (e) {
      setMsg(m, "Le lien n'a pas pu être envoyé : " + explain(e) + ".", "err");
    }
    b.disabled = false;
  });
  const out = async () => {
    if (DEMO) { location.search = ""; return; }
    try { await sb.auth.signOut(); } catch { /* la session locale est effacée quand même */ }
    userId = null;
    showLogin();
  };
  $("logout").addEventListener("click", out);
  $("denied-logout").addEventListener("click", out);
}
async function onSession(session) {
  if (!session || !session.user) {
    if (userId !== "") { userId = ""; showLogin(); }
    return;
  }
  if (userId === session.user.id) return; // simple rafraîchissement du jeton
  userId = session.user.id;
  setWho(session.user.email);
  $("loading-text").textContent = "Chargement des offres…";
  showView("loading");
  const allowed = await api.isAllowed();
  if (allowed === false) { showView("denied"); return; }
  const ok = await refresh();
  if (allowed === null && ok && !state.sources.length && !state.offers.length && !state.runs.length && !state.lastRun) {
    showView("denied");
    return;
  }
  showView("app");
  startLive();
}

/* ------------------------------------------------------------ démarrage */
function bindStatic() {
  bindTabs();
  document.querySelectorAll("#offres .filters button").forEach((b) => b.addEventListener("click", () => {
    ui.filter = b.dataset.f; store("filter", ui.filter); renderOffers();
  }));
  const sort = $("sort");
  sort.value = ui.sort;
  sort.addEventListener("change", () => { ui.sort = sort.value; store("sort", ui.sort); renderOffers(); });
  const sc = $("show-closed");
  sc.checked = ui.showClosed;
  sc.addEventListener("change", () => { ui.showClosed = sc.checked; store("closed", sc.checked ? "1" : "0"); renderOffers(); });
  const q = $("q");
  let qt = null;
  q.addEventListener("input", () => {
    clearTimeout(qt);
    qt = setTimeout(() => { ui.q = q.value; dirty.delete("offer-list"); buildOffers($("offer-list")); }, 120);
  });
  $("refresh").addEventListener("click", requestFullRun);
  watchFocus("offer-list", buildOffers);
  watchFocus("source-list", buildSources);
  buildForm();
  bindLogin();
}

async function boot() {
  bindStatic();
  if (DEMO) return bootDemo();
  let cfg;
  try { cfg = await import("./config.js"); } catch {
    showSetup("Le fichier site/config.js est introuvable ou contient une erreur de syntaxe.");
    return;
  }
  const problem = !cfg.SUPABASE_URL ? "L'adresse du projet Supabase manque dans site/config.js." : keyProblem(cfg.SUPABASE_PUBLISHABLE_KEY);
  if (problem) { showSetup(problem); return; }
  loginNotice = urlAuthError();
  let createClient;
  try { ({ createClient } = await import(SUPABASE_JS)); } catch {
    $("loading-text").textContent = "Impossible de charger la bibliothèque Supabase (jsDelivr). Vérifie ta connexion internet, puis recharge la page.";
    $("loading-text").classList.add("err");
    return;
  }
  try {
    sb = createClient(cfg.SUPABASE_URL, cfg.SUPABASE_PUBLISHABLE_KEY, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  } catch (e) {
    showSetup("La configuration Supabase est invalide : " + explain(e) + ".");
    return;
  }
  api = makeSupabaseApi(sb);
  sb.auth.onAuthStateChange((event, session) => {
    // ne pas appeler Supabase directement dans ce rappel (verrou interne) : on diffère
    setTimeout(() => {
      if (event === "SIGNED_OUT") { userId = null; showLogin(); return; }
      onSession(session);
    }, 0);
  });
  try {
    const { data } = await sb.auth.getSession();
    await onSession(data && data.session);
  } catch (e) {
    loginNotice = "Session illisible : " + explain(e) + ". Reconnecte-toi.";
    showLogin();
  }
}

/* ------------------------------------------------------------ mode démo (?demo=1) */
// Données fictives mais réalistes, en mémoire : rien n'est envoyé sur le réseau.
// Options : &vue=login|setup|denied pour voir ces écrans, &echec=1 pour simuler
// des écritures refusées.
function bootDemo() {
  const vue = params.get("vue");
  setWho("demo@exemple.fr");
  if (vue === "setup") return showSetup("La clé publique de Supabase n'est pas encore renseignée dans site/config.js.");
  if (vue === "login") return showLogin();
  if (vue === "denied") return showView("denied");
  api = makeDemoApi(params.get("echec") === "1");
  showView("app");
  refresh();
}
function makeDemoApi(failWrites) {
  const db = demoData();
  const wait = (ms = 220) => new Promise((r) => setTimeout(r, ms));
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const fail = async () => { await wait(); if (failWrites) throw new TypeError("Failed to fetch"); };
  let nextReq = 100;
  return {
    async isAllowed() { return true; },
    async loadAll() {
      await wait(120);
      return clone({
        sources: db.sources.slice().sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999)),
        offers: db.offers, runs: db.runs, lastRun: db.meta.last_run,
        pending: db.run_requests.filter((r) => !r.done_at),
      });
    },
    async updateOffer(id, fields) {
      await fail();
      const o = db.offers.find((x) => x.id === id);
      if (!o) throw Object.assign(new Error("not_updated"), { code: "not_updated" });
      Object.assign(o, fields);
    },
    async insertSource(row) {
      await fail();
      if (db.sources.some((s) => s.id === row.id)) throw Object.assign(new Error("duplicate key"), { code: "23505" });
      db.sources.push(Object.assign({ read_urls: [], enabled: true, last_urls: null, created_at: new Date().toISOString() }, clone(row)));
    },
    async updateSource(id, fields) {
      await fail();
      const s = db.sources.find((x) => x.id === id);
      if (!s) throw Object.assign(new Error("not_updated"), { code: "not_updated" });
      Object.assign(s, fields);
    },
    async deleteSource(id) {
      await fail();
      db.sources = db.sources.filter((s) => s.id !== id);
      db.offers = db.offers.filter((o) => o.source_id !== id);
    },
    async requestRun(sources) {
      await fail();
      db.run_requests.push({ id: nextReq++, requested_at: new Date().toISOString(), sources, done_at: null });
    },
  };
}
function demoData() {
  const now = Date.now();
  const iso = (msAgo) => new Date(now - msAgo).toISOString();
  const H = 3600e3, D = 24 * H, MIN = 60e3;
  const day = (n) => { const d = new Date(now - n * D); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const defCrit = null;
  const S = (o) => Object.assign({
    kind: "auto", params: {}, read_urls: [], criteria: defCrit, status: "ok", reason: null, fix: null, note: null,
    enabled: true, last_checked: iso(25 * MIN), last_method: "html", last_error: null, last_count: 0,
    last_urls: [], added_from_site: false, created_at: iso(30 * D),
  }, o);
  const lazardApi = "https://icbpjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber=LazardStudentCareers,facetsList=NONE,limit=25,offset=0,sortBy=POSTING_DATES_DESC,selectedFlexFieldsFacets=%22AttributeChar8%7CAsset%20Management%3BCorporate%22";
  const sources = [
    S({ id: "amiral", rank: 1, company: "Amiral Gestion", kind: "sainoo", catalog_url: "https://amiralgestion.sainoo.com/careers",
      filters: "Le site n'a pas de filtre : le robot lit les 6 offres et garde les stages à Paris dans tes métiers.",
      last_count: 6, last_urls: ["https://amiralgestion.sainoo.com/careers"] }),
    S({ id: "dnca", rank: 2, company: "DNCA Finance", kind: "dnca", catalog_url: "https://www.dnca-investments.com/carrieres?contract=stage",
      filters: "Contrat = Stage (filtre du site, dans l'URL).", last_count: 4,
      last_urls: ["https://www.dnca-investments.com/carrieres?contract=stage",
        "https://www.dnca-investments.com/carrieres/stage-analyste-financier-actions-small-mid-caps",
        "https://www.dnca-investments.com/carrieres/stage-assistant-middle-office"] }),
    S({ id: "eleva", rank: 3, company: "Eleva Capital", kind: "page_watch", status: "sans_catalogue", last_method: "veille",
      catalog_url: "https://www.jobteaser.com/en/companies/eleva-capital/job-offers",
      filters: "Eleva ne publie ses offres que sur JobTeaser, que le robot ne lit pas (conditions d'utilisation).",
      reason: "Eleva ne publie ses offres que sur JobTeaser, que le robot ne lit pas (conditions d'utilisation de JobTeaser).",
      fix: "Ouvre la page JobTeaser d'Eleva toi-même une fois par semaine (bouton « Ouvrir le catalogue »), ou envoie une candidature spontanée.",
      last_count: 0, last_urls: [] }),
    S({ id: "mirova", rank: 4, company: "Mirova", kind: "wp_job", last_method: "api",
      catalog_url: "https://recrutement.natixis.com/nos-offres-demploi?tax_brands=mirova%2Cmirova-us&external=false",
      filters: "Marque = Mirova (filtre du site). Le robot lit l'API publique du site Natixis et garde les offres Mirova.",
      last_count: 3, last_urls: [
        "https://recrutement.natixis.com/app/wp-json/wp/v2/job?search=stage&per_page=100&page=1&_fields=id,date,title,link,class_list",
        "https://recrutement.natixis.com/app/wp-json/wp/v2/job?search=internship&per_page=100&page=1&_fields=id,date,title,link,class_list",
        "https://recrutement.natixis.com/job/stage-6-mois-analyste-investissement-f-h/"] }),
    S({ id: "amundi", rank: 5, company: "Amundi", kind: "talentsoft",
      catalog_url: "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79",
      read_urls: ["https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79",
        "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=162"],
      filters: "Pays = France puis Royaume-Uni (filtre du site, dans l'URL). Contrat et métier triés par le robot.",
      criteria: { types: ["Gestion d'actifs", "Equity research", "Investment specialist", "Investment analyst", "ESG / ISR"],
        starts: ["Janvier 2027", "Mars 2027"], keywords: "multi-asset, actions européennes", cities: "Paris, Londres" },
      last_count: 64, last_urls: [
        "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79",
        "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79&page=2",
        "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=162",
        "https://jobs.amundi.com/offre-de-emploi/emploi-stage-assistant-gerant-actions-europeennes-h-f_116937.aspx"] }),
    S({ id: "edram", rank: 10, company: "Edmond de Rothschild", kind: "oracle_hcm", status: "partiel", last_method: "api",
      catalog_url: "https://evht.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_7001/jobs",
      filters: "Toutes les offres du portail officiel (24), tri lieu et contrat par le robot.",
      reason: "Edmond de Rothschild publie la plupart de ses stages sur JobTeaser, que le robot ne lit pas (conditions d'utilisation) : seul le portail officiel est lu.",
      fix: "Jette un œil à la page JobTeaser d'Edmond de Rothschild de temps en temps.",
      last_count: 24, last_urls: ["https://evht.fa.ocs.oraclecloud.eu/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber=CX_7001,facetsList=NONE,limit=25,offset=0,sortBy=POSTING_DATES_DESC"] }),
    S({ id: "lazard", rank: 11, company: "Lazard Frères Gestion", kind: "oracle_hcm", last_method: "api",
      catalog_url: "https://icbpjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/LazardStudentCareers/jobs?lastSelectedFacet=LOCATIONS&selectedFlexFieldsFacets=%22AttributeChar8%7CAsset%20Management%3BCorporate%22&selectedLocationsFacet=300000000798421%3B300000000798256%3B300000000798598",
      filters: "Métier = Asset Management + Corporate, lieux Paris, Lyon, Nantes (filtres du lien officiel).",
      last_count: 9, last_urls: [lazardApi,
        "https://icbpjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id=%226313%22,siteNumber=LazardStudentCareers"] }),
    S({ id: "ms", rank: 14, company: "Morgan Stanley", kind: "talnet", status: "erreur", last_method: "html",
      catalog_url: "https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/",
      filters: "Les filtres du site sont des cases sans lien : le robot lit toutes les offres campus (2 pages) et trie lui-même.",
      reason: "La page du catalogue n'a pas répondu correctement (erreur 502 du serveur Morgan Stanley).",
      fix: "Rien à faire si ça ne dure pas : le robot réessaie à chaque passage. Si l'erreur revient plusieurs jours, ouvre le catalogue pour vérifier l'adresse.",
      last_count: 0, last_error: "FetchError: HTTP 502 Bad Gateway\nGET https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/\n3 tentatives, dernière à " + fmtTime(iso(25 * MIN)),
      last_urls: ["https://morganstanley.tal.net/robots.txt", "https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/"] }),
    S({ id: "pictet", rank: 15, company: "Pictet", kind: "blocked", status: "resiste", last_method: "navigateur",
      catalog_url: "https://career012.successfactors.eu/career?company=banquepict",
      filters: "Catalogue SuccessFactors de Pictet.",
      reason: "Le site refuse la lecture automatique (réponse 403) et affiche une page anti-robot, même dans le navigateur du robot.",
      fix: "Ouvre le catalogue avec le bouton et regarde les offres toi-même une fois par semaine. Le robot réessaie à chaque passage et te prévient s'il y arrive.",
      last_count: 0, last_error: "HTTP 403 Forbidden : page de défi anti-robot détectée (\"Access denied\").",
      last_urls: ["https://career012.successfactors.eu/robots.txt", "https://career012.successfactors.eu/career?company=banquepict"] }),
    S({ id: "blackrock", rank: 16, company: "BlackRock", kind: "talentbrew", enabled: false, last_method: "navigateur", last_checked: iso(6 * D),
      catalog_url: "https://careers.blackrock.com/category/students-and-graduates-jobs/45831/9022304/1",
      filters: "Catégorie Students and Graduates (lien du site), plusieurs pages, puis lieu et off-cycle triés par le robot.",
      note: "Mis en pause : pas de stage off-cycle à Paris cette saison.",
      last_count: 31, last_urls: ["https://careers.blackrock.com/category/students-and-graduates-jobs/45831/9022304/1",
        "https://careers.blackrock.com/category/students-and-graduates-jobs/45831/9022304/2"] }),
    S({ id: "jpm", rank: 17, company: "J.P. Morgan", kind: "oracle_hcm", last_method: "api",
      catalog_url: "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs?keyword=internship",
      filters: "Recherche du portail : « internship » et « off-cycle », pays France + Royaume-Uni (filtres du portail).",
      last_count: 57, last_urls: [
        "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=CX_1001,keyword=%22internship%22,selectedLocationsFacet=300000000289270%3B300000000289276",
        "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=CX_1001,keyword=%22off-cycle%22,selectedLocationsFacet=300000000289270%3B300000000289276"] }),
    S({ id: "gs", rank: 18, company: "Goldman Sachs", kind: "roles_watch", status: "partiel", last_method: "navigateur",
      catalog_url: "https://higher.gs.com/campus?LOCATION=Paris|London&page=1&sort=RELEVANCE",
      filters: "Lieu = Paris + Londres (filtre du site, dans l'URL).",
      reason: "Le site n'affiche ses offres qu'avec JavaScript et 20 à la fois : le robot lit la première page dans son navigateur, la suite peut manquer.",
      fix: "Ouvre le catalogue (filtre Paris + Londres déjà appliqué) et fais défiler jusqu'en bas une fois par semaine.",
      last_count: 20, last_urls: ["https://higher.gs.com/campus?LOCATION=Paris|London&page=1&sort=RELEVANCE"] }),
    S({ id: "tikehau-capital", rank: 21, company: "Tikehau Capital", status: "a_configurer", last_method: null, last_checked: null,
      last_count: null, catalog_url: null, added_from_site: true, created_at: iso(40 * MIN), params: { url: null },
      criteria: { types: ["Gestion d'actifs", "Investment analyst", "Private equity", "Crédit / obligataire"],
        starts: ["Janvier 2027", "Mars 2027"], keywords: "private debt, crédit", cities: "Paris, Londres" } }),
  ];
  const O = (o) => Object.assign({
    contract: "Stage", published: null, published_label: null, start_label: null, reasons: null, status: "nouvelle",
    note: null, first_seen: iso(2 * D), last_seen: iso(25 * MIN), closed: false, closed_on: null, manual: false,
  }, o);
  const lz = (id) => `https://icbpjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/LazardStudentCareers/job/${id}`;
  const offers = [
    O({ id: "amundi:116937", source_id: "amundi", company: "Amundi", title: "Stage - Assistant Gérant Actions Européennes (H/F)",
      url: "https://jobs.amundi.com/offre-de-emploi/emploi-stage-assistant-gerant-actions-europeennes-h-f_116937.aspx",
      location: "Paris", published: day(3), start_label: "Janvier 2027", relevance: "cible", first_seen: iso(3 * D - 5 * H),
      reasons: "Stage de 6 mois · gestion d'actifs (actions) · démarrage janvier 2027 · Paris" }),
    O({ id: "amundi:117020", source_id: "amundi", company: "Amundi", title: "Stage - Investment Specialist Multi-Asset (H/F)",
      url: "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79",
      location: "Paris", published: day(9), start_label: "Mars 2027", relevance: "cible", status: "a_postuler", first_seen: iso(9 * D),
      reasons: "Stage · investment specialist · démarrage mars 2027 · Paris", note: "Lettre à adapter : insister sur le multi-asset et le DCF." }),
    O({ id: "amundi:116811", source_id: "amundi", company: "Amundi", title: "Internship - ESG Research Analyst (F/M)",
      url: "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=162",
      location: "London", contract: "Internship", published: day(21), relevance: "proche", first_seen: iso(21 * D),
      reasons: "Stage · ESG / ISR · démarrage non précisé · Londres" }),
    O({ id: "amundi:116702", source_id: "amundi", company: "Amundi", title: "Stage - Analyste Risques de Marché (H/F)",
      url: "https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79",
      location: "Paris", published: day(34), start_label: "Janvier 2027", relevance: "proche", status: "refuse", first_seen: iso(34 * D),
      reasons: "Risques : proche de tes métiers sans en faire partie · janvier 2027 · Paris" }),
    O({ id: "lazard:6313", source_id: "lazard", company: "Lazard Frères Gestion", title: "Stage H/F - Analyste Actions – Janvier 2027",
      url: lz(6313), location: "Paris, France", published: "2026-06-30", start_label: "Janvier 2027", relevance: "cible",
      status: "postule", first_seen: iso(40 * D), reasons: "Stage · equity research · démarrage janvier 2027 · Paris",
      note: "Candidature envoyée le 02/11, relancer le 16/11." }),
    O({ id: "lazard:6316", source_id: "lazard", company: "Lazard Frères Gestion", title: "Stage H/F - Assistant de Gestion Fixed Income – Janvier 2027",
      url: lz(6316), location: "Paris, France", published: "2026-06-30", start_label: "Janvier 2027", relevance: "proche", first_seen: iso(40 * D),
      reasons: "Crédit / obligataire (pas coché dans tes types) · janvier 2027 · Paris" }),
    O({ id: "lazard:6687", source_id: "lazard", company: "Lazard Frères Gestion", title: "Stage H/F - Assistant Gestion de Portefeuilles Obligataires",
      url: lz(6687), location: "Paris, France", published: "2026-10-02", relevance: "proche", first_seen: iso(37 * D),
      closed: true, closed_on: day(2), reasons: "Gestion obligataire · démarrage non précisé · Paris" }),
    O({ id: "dnca:analyste-small-mid", source_id: "dnca", company: "DNCA Finance",
      title: "Stage – Analyste financier actions Small & Mid Caps (H/F) – 6 mois",
      url: "https://www.dnca-investments.com/carrieres/stage-analyste-financier-actions-small-mid-caps",
      location: "Paris", start_label: "Janvier 2027", relevance: "cible", status: "entretien", first_seen: iso(12 * D),
      reasons: "Stage · equity research small & mid caps · janvier 2027 · Paris", note: "Entretien le 12/11 à 10 h avec un gérant." }),
    O({ id: "dnca:middle-office", source_id: "dnca", company: "DNCA Finance", title: "Stage – Assistant Middle Office (H/F)",
      url: "https://www.dnca-investments.com/carrieres/stage-assistant-middle-office",
      location: "Paris", published_label: "Il y a 2 semaines", start_label: "Janvier 2027", relevance: "exclue", first_seen: iso(14 * D),
      reasons: "Middle office : hors de tes métiers" }),
    O({ id: "mirova:20732", source_id: "mirova", company: "Mirova", title: "Stage – 6 mois – Analyste Investissement F/H",
      url: "https://recrutement.natixis.com/job/stage-6-mois-analyste-investissement-f-h/", location: "Paris",
      published: day(2), start_label: "Janvier 2027", relevance: "cible", first_seen: iso(2 * D - 3 * H),
      reasons: "Stage de 6 mois · investment analyst · janvier 2027 · Paris" }),
    O({ id: "jpm:210802076", source_id: "jpm", company: "J.P. Morgan",
      title: "2027 Commercial & Investment Banking - Global Markets - Off-cycle Internship – Paris",
      url: "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210802076", location: "Paris, France",
      contract: "Internship", published: day(18), start_label: "2027", relevance: "exclue", first_seen: iso(17 * D),
      reasons: "Marchés / trading : hors de tes types cochés" }),
    O({ id: "gs:aw-paris-offcycle", source_id: "gs", company: "Goldman Sachs",
      title: "2027 | Paris | Asset & Wealth Management | Off-Cycle Internship",
      url: "https://higher.gs.com/campus?LOCATION=Paris|London&page=1&sort=RELEVANCE", location: "Paris",
      contract: "Internship", published_label: "Posted 5 days ago", relevance: "proche", first_seen: iso(5 * D),
      reasons: "Off-cycle (dates à confirmer) · gestion d'actifs · Paris" }),
  ];
  const rep = (id, extra) => {
    const s = sources.find((x) => x.id === id);
    return Object.assign({ source: id, company: s.company, status: s.status, method: s.last_method, urls: s.last_urls, details: [],
      found: s.last_count || 0, new: 0, hits: 0, closed: 0, reason: s.reason || "", error: s.last_error || "" }, extra || {});
  };
  const ids = sources.filter((s) => s.enabled && s.status !== "a_configurer").map((s) => s.id);
  const runs = [
    { id: 42, started_at: iso(29 * MIN), finished_at: iso(25 * MIN), trigger: "schedule",
      totals: { sources: ids.length, ok: ids.length - 2, resiste: 1, erreur: 1, new: 1, closed: 0 },
      report: ids.map((id) => rep(id, id === "mirova" ? { new: 1, hits: 1, details: ["https://recrutement.natixis.com/job/stage-6-mois-analyste-investissement-f-h/"] } : null)) },
    { id: 41, started_at: iso(3 * H + 34 * MIN), finished_at: iso(3 * H + 30 * MIN), trigger: "demande du site",
      totals: { sources: ids.length, ok: ids.length - 1, resiste: 1, erreur: 0, new: 2, closed: 1 },
      report: ids.map((id) => rep(id, id === "ms" ? { status: "ok", found: 41, reason: "", error: "" }
        : id === "lazard" ? { closed: 1 } : id === "amundi" ? { new: 2, hits: 1 } : null)) },
    { id: 40, started_at: iso(D + 4 * MIN), finished_at: iso(D), trigger: "schedule",
      totals: { sources: ids.length, ok: ids.length - 1, resiste: 1, erreur: 0, new: 0, closed: 0 },
      report: ids.map((id) => rep(id, id === "ms" ? { status: "ok", found: 40, reason: "", error: "" } : null)) },
  ];
  return {
    sources, offers, runs,
    meta: { last_run: { started_at: runs[0].started_at, finished_at: runs[0].finished_at, trigger: runs[0].trigger, totals: runs[0].totals } },
    run_requests: [],
  };
}

boot().catch((e) => {
  const t = $("loading-text");
  if (t) { t.textContent = "Le site n'a pas pu démarrer : " + explain(e) + ". Recharge la page."; t.classList.add("err"); }
  showView("loading");
});
