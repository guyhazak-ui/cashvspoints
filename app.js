// Cash vs Points -- frontend logic
// Dual-mode homepage: AI chat (Mode A) + structured search (Mode B).
// Both modes hit the same FastAPI backend and render results identically.

const CABIN_ORDER = ["economy", "premium_economy", "business", "first"];
const CABIN_LABELS = {
  economy: "Economy",
  premium_economy: "Premium Economy",
  business: "Business",
  first: "First Class",
};

const LOADING_MESSAGES = [
  "Digging through fare classes…",
  "Pinging award charts across alliances…",
  "Calculating cents-per-point yield…",
  "Cross-checking cash vs miles…",
  "Almost there — ranking your best options…",
];

const modeAiBtn = document.getElementById("mode-ai-btn");
const modeSearchBtn = document.getElementById("mode-search-btn");
const panelAi = document.getElementById("panel-ai");
const panelSearch = document.getElementById("panel-search");

const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

const searchForm = document.getElementById("search-form");

const loadingEl = document.getElementById("loading");
const loadingTextEl = document.getElementById("loading-text");
const resultsEl = document.getElementById("results");
const summaryCardEl = document.getElementById("summary-card");
const cabinSectionsEl = document.getElementById("cabin-sections");
const warningsEl = document.getElementById("warnings");

let loadingInterval = null;

function setMode(mode) {
  const isAi = mode === "ai";
  modeAiBtn.classList.toggle("active", isAi);
  modeSearchBtn.classList.toggle("active", !isAi);
  modeAiBtn.setAttribute("aria-selected", String(isAi));
  modeSearchBtn.setAttribute("aria-selected", String(!isAi));
  panelAi.classList.toggle("hidden", !isAi);
  panelSearch.classList.toggle("hidden", isAi);
}

modeAiBtn.addEventListener("click", () => setMode("ai"));
modeSearchBtn.addEventListener("click", () => setMode("search"));

function showLoading() {
  resultsEl.classList.add("hidden");
  loadingEl.classList.remove("hidden");
  let i = 0;
  loadingTextEl.textContent = LOADING_MESSAGES[0];
  loadingInterval = setInterval(() => {
    i = (i + 1) % LOADING_MESSAGES.length;
    loadingTextEl.textContent = LOADING_MESSAGES[i];
  }, 1600);
}

function hideLoading() {
  clearInterval(loadingInterval);
  loadingEl.classList.add("hidden");
}

function addChatMessage(text, sender) {
  const msg = document.createElement("div");
  msg.className = `chat-msg ${sender}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = sender === "user" ? "🙂" : "✈";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  msg.appendChild(avatar);
  msg.appendChild(bubble);
  chatWindow.appendChild(msg);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function money(n) {
  if (n === null || n === undefined) return "—";
  return `$${Number(n).toFixed(0)}`;
}

function pointsFmt(n) {
  if (n === null || n === undefined) return "—";
  return `${Number(n).toLocaleString()} pts`;
}

function flightDetailsCell(o) {
  const status = o.direct
    ? "Direct"
    : `Connecting${o.connection_airport ? " via " + o.connection_airport : ""}`;
  const times = [o.depart_time, o.arrival_time].filter(Boolean).join(" → ");
  return `
    <span class="flight-name">${o.airline || "Unknown"} ${o.flight_number || ""}</span>
    <span class="flight-meta">${times || "Time TBD"} · ${status}</span>
  `;
}

function renderSummary(summary) {
  summaryCardEl.innerHTML = "";
  const bp = summary.best_points_value;
  const cc = summary.cheapest_cash_deal;

  const bpLine = document.createElement("div");
  bpLine.className = "summary-line";
  bpLine.innerHTML = bp
    ? `<span class="summary-label points">🟢 Best Points Value</span> ${bp.airline} — ${pointsFmt(bp.points_cost)} + ${money(bp.taxes_fees)} fees (${bp.cpp_yield ?? "—"}¢/pt) in ${CABIN_LABELS[bp.cabin] || bp.cabin}.`
    : `<span class="summary-label points">🟢 Best Points Value</span> No award availability found.`;

  const ccLine = document.createElement("div");
  ccLine.className = "summary-line";
  ccLine.innerHTML = cc
    ? `<span class="summary-label cash">💵 Cheapest Cash Deal</span> ${cc.airline} — ${money(cc.cash_price)} in ${CABIN_LABELS[cc.cabin] || cc.cabin}.`
    : `<span class="summary-label cash">💵 Cheapest Cash Deal</span> No cash fares found.`;

  summaryCardEl.appendChild(bpLine);
  summaryCardEl.appendChild(ccLine);
}

function renderCabinSections(cabins) {
  cabinSectionsEl.innerHTML = "";
  CABIN_ORDER.forEach((cabinKey) => {
    const options = cabins[cabinKey];
    if (!options || options.length === 0) return;

    const section = document.createElement("div");
    section.className = "cabin-section";

    const title = document.createElement("div");
    title.className = "cabin-title";
    title.textContent = CABIN_LABELS[cabinKey];
    section.appendChild(title);

    const table = document.createElement("table");
    table.className = "results-table";
    table.innerHTML = `
      <thead>
        <tr>
          <th>Flight Details &amp; Airline</th>
          <th>Cash Price</th>
          <th>Points Cost</th>
          <th>Taxes &amp; Fees</th>
          <th>Transfer From</th>
          <th>CPP Yield</th>
          <th>Verdict</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");

    options.forEach((o) => {
      const tr = document.createElement("tr");
      const icons = o.verdict_icons || [];
      if (icons.includes("🟢") || icons.includes("💵")) tr.classList.add("best-row");
      tr.innerHTML = `
        <td>${flightDetailsCell(o)}</td>
        <td class="price-cash">${money(o.cash_price)}</td>
        <td class="price-points">${pointsFmt(o.points_cost)}</td>
        <td>${money(o.taxes_fees)}</td>
        <td>${o.transfer_from || "—"}</td>
        <td>${o.cpp_yield !== null && o.cpp_yield !== undefined ? o.cpp_yield + "¢" : "—"}</td>
        <td class="verdict-icons">${icons.join(" ") || "—"}</td>
      `;
      tbody.appendChild(tr);
    });

    section.appendChild(table);
    cabinSectionsEl.appendChild(section);
  });
}

function renderWarnings(warnings) {
  if (!warnings || warnings.length === 0) {
    warningsEl.classList.add("hidden");
    warningsEl.innerHTML = "";
    return;
  }
  warningsEl.classList.remove("hidden");
  warningsEl.innerHTML = `⚠️ Some searches had issues:<ul>${warnings
    .map((w) => `<li>${w}</li>`)
    .join("")}</ul>`;
}

function renderResults(data) {
  hideLoading();
  if (data.error) {
    resultsEl.classList.remove("hidden");
    summaryCardEl.innerHTML = `<div class="summary-line">${data.error}</div>`;
    cabinSectionsEl.innerHTML = "";
    renderWarnings(data.warnings);
    return;
  }
  renderSummary(data.summary || {});
  renderCabinSections(data.cabins || {});
  renderWarnings(data.warnings);
  resultsEl.classList.remove("hidden");
}

// ---- Mode A: AI chat ----
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = chatInput.value.trim();
  if (!query) return;
  addChatMessage(query, "user");
  chatInput.value = "";
  showLoading();

  try {
    const res = await fetch("/api/ai-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    if (data.assistant_reply) addChatMessage(data.assistant_reply, "assistant");
    else if (data.error) addChatMessage(data.error, "assistant");
    renderResults(data);
  } catch (err) {
    hideLoading();
    addChatMessage("Something went wrong reaching the search backend. Please try again.", "assistant");
  }
});

// ---- Mode B: structured search ----
searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  showLoading();

  const payload = {
    origin: document.getElementById("origin").value.trim(),
    destination: document.getElementById("destination").value.trim(),
    depart_date: document.getElementById("depart_date").value,
    return_date: document.getElementById("return_date").value || null,
    passengers: parseInt(document.getElementById("passengers").value, 10) || 1,
  };

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    renderResults(data);
  } catch (err) {
    hideLoading();
    resultsEl.classList.remove("hidden");
    summaryCardEl.innerHTML = `<div class="summary-line">Something went wrong reaching the search backend. Please try again.</div>`;
    cabinSectionsEl.innerHTML = "";
  }
});
