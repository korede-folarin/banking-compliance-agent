// Banking Compliance Agent, static demo. Reads data/overview.json and data/samples.json (built by
// `python -m src.site.build` from the saved results). No network calls beyond those two files.
"use strict";

const COLOURS = { "Possible breach": "#ff4f12", "Not enough evidence": "#8a8f7e", "Looks compliant": "#1e4a3b",
                  "Not applicable": "#cfcbbd", "No answer": "#0e0e0c" };
const DARK_TEXT = new Set(["Possible breach", "Not applicable"]);
const OUTCOMES = ["Price and value", "Consumer support", "Products and services", "Consumer understanding"];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (id) => document.getElementById(id);
const card = (label, value, hint = "", cls = "") =>
  `<div class="card ${cls}"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div>${hint ? `<div class="hint">${esc(hint)}</div>` : ""}</div>`;

function bar(name, counts, total, order) {
  const segs = order.filter((k) => counts[k]).map((k) => {
    const pct = (100 * counts[k]) / total;
    return `<div class="seg${DARK_TEXT.has(k) ? " dark-text" : ""}" style="width:${pct}%;background:${COLOURS[k] || "#1e4a3b"}"
      title="${esc(k)}: ${counts[k]}">${pct >= 7 ? counts[k] : ""}</div>`;
  }).join("");
  const label = order.filter((k) => counts[k]).map((k) => `${k}: ${counts[k]}`).join(", ");
  return `<div class="row"><div class="name">${esc(name)}</div><div class="track" role="img" aria-label="${esc(name)}: ${esc(label)}">${segs}</div></div>`;
}

function renderOverview(data, system) {
  const s = data.systems[system];
  const agent = system.startsWith("AI agent");
  $("kpis").innerHTML =
    card("Loan agreements reviewed", s.agreements) +
    card("With a possible breach", s.agreements_with_a_possible_breach) +
    card("A person must look closely", s.agreements_needing_a_person, "possible breach, not enough evidence, or a vulnerable-customer question") +
    card("Vulnerable customers to escalate", agent ? (s.escalation["Escalate: vulnerable customer"] || 0) : "n/a",
         agent ? "" : "only the AI agent checks customer accounts");

  const order = Object.keys(COLOURS);
  const total = s.agreements;
  $("found").innerHTML = OUTCOMES.map((o) => bar(o, s.found[o] || {}, total, order)).join("");
  const present = order.filter((k) => OUTCOMES.some((o) => (s.found[o] || {})[k]));
  $("found-legend").innerHTML = present.map((k) => `<span style="--c:${COLOURS[k]}">${esc(k)}</span>`).join("");

  $("rel-cap").textContent = `Measured on test agreements with known, planted problems: ${s.reviews} reviews in total. ` +
    "This is the system's own call, before any safety rule sent it to a person.";
  $("rel-kpis").innerHTML =
    card("Real problems caught", `${s.caught} of ${s.real_problems}`) +
    card("Real problems missed", s.missed, "a real problem called compliant: the most serious error", s.missed ? "alert" : "") +
    card("False alarms", s.false_alarms, "a compliant agreement flagged: costs reviewer time");
  const rows = OUTCOMES.map((o) => {
    const r = s.reliability[o] || {};
    return `<tr><th scope="row">${esc(o)}</th><td class="num">${r.caught || 0}</td><td class="num${r.missed ? " bad" : ""}">${r.missed || 0}</td>
      <td class="num">${r.false_alarm || 0}</td><td class="num">${r.unsure || 0}</td></tr>`;
  }).join("");
  $("rel-table").innerHTML = `<caption class="sr">Results per outcome against the known answers</caption>
    <thead><tr><th scope="col">Outcome</th><th scope="col">Problems caught</th><th scope="col">Problems missed</th>
    <th scope="col">False alarms</th><th scope="col">Unsure (sent to a person)</th></tr></thead><tbody>${rows}</tbody>`;
  const worst = OUTCOMES.reduce((a, o) => ((s.reliability[o] || {}).missed || 0) > ((s.reliability[a] || {}).missed || 0) ? o : a, OUTCOMES[0]);
  const note = $("rel-note");
  if (s.missed) {
    const w = (s.reliability[worst] || {}).missed || 0;
    note.className = "callout warn";
    note.textContent = `${s.missed} real ${s.missed === 1 ? "problem was" : "problems were"} missed, ${w === s.missed ? "all of them" : w + " of them"} in ` +
      `${worst.toLowerCase()}. This is why a person reviews every agreement.`;
  } else {
    note.className = "callout ok";
    note.textContent = "No real problem was missed in these tests. With this few test agreements that still cannot prove a low miss rate, so a person reviews every agreement.";
  }

  $("esc-block").hidden = !agent;
  if (agent) {
    const [right, n] = s.escalation_right;
    $("esc-cap").textContent = `Whether the customer's case should go to the vulnerable-customer team, decided from their account and Northbridge's policy. Right in ${right} of ${n} reviews.`;
    const entries = Object.entries(s.escalation).sort((a, b) => b[1] - a[1]);
    const max = Math.max(...entries.map((e) => e[1]));
    $("esc").innerHTML = entries.map(([k, v]) => `<div class="row"><div class="name">${esc(k)}</div>
      <div class="track" role="img" aria-label="${esc(k)}: ${v}"><div class="seg" style="width:${(100 * v) / max}%;background:#1e4a3b">${v}</div></div></div>`).join("");
  }
}

function renderHealth(h) {
  $("health-cap").textContent = `For the technical team, from the audit log (as of ${h.as_of}). Every agreement is flagged for a person by design.`;
  $("health").innerHTML = `<div><b>${h.agent_document_runs}</b>agent document runs</div>
    <div><b>${(100 * h.failure_rate).toFixed(1)}%</b>runs that failed</div>
    <div><b>${h.median_latency_s} s</b>median time per agreement</div>
    <div><b>$${h.live_spend_usd.toFixed(2)}</b>total live model spend</div>`;
}

function renderSample(x) {
  $("agreement").textContent = x.agreement;
  const f = x.facts;
  const steps = [];
  steps.push(`<h4>Before any AI: what the code reads</h4>
    <div class="facts"><div class="fact"><span>A loan agreement?</span><b>${f.loan_agreement ? "Yes" : "No"}</b></div>
    <div class="fact"><span>Lender</span><b>${esc(f.lender)}</b></div>
    <div class="fact"><span>Customer number</span><b>${esc(f.customer_number || "None")}</b></div></div><p>${esc(x.gate)}</p>`);

  const looks = x.lookups.length ? `<ol>${x.lookups.map((l) => `<li>${esc(l.what)} ${esc(l.detail)}${l.unnecessary
    ? ` <span class="flag">unnecessary: ${esc(l.unnecessary)}</span>` : ""}</li>`).join("")}</ol>` : "<p>Nothing: no lookup was needed.</p>";
  steps.push(`<h4>What the AI chose to look up</h4>${looks}${x.recorded_before_rules
    ? `<p class="cap">This run was recorded before the code rules in step 1 were added. Today the unnecessary tools would not even be offered.</p>` : ""}`);

  if (x.account) {
    const a = x.account;
    steps.push(`<h4>What the customer's account shows</h4>` + (a.found
      ? `<div class="facts"><div class="fact"><span>Account holder</span><b>${esc(a.holder)}</b></div>
         <div class="fact"><span>Missed payments, 12 months</span><b>${a.missed_payments}</b></div>
         <div class="fact"><span>Open hardship markers</span><b>${a.hardship_markers}</b></div>
         <div class="fact"><span>Recent life-event notes</span><b>${a.life_event_notes}</b></div></div>`
        + (a.borrower && a.borrower !== a.holder ? `<p class="flag">The agreement names ${esc(a.borrower)}.</p>` : "")
      : `<p class="flag">No account exists for ${esc(a.customer_id)}.</p>`));
  }

  steps.push(`<h4>Its verdict on each Consumer Duty outcome</h4>` + x.verdicts.map((v) => `<details class="verdict">
    <summary>${esc(v.outcome)} <span class="pill ${esc(v.status)}">${esc(v.plain)}</span></summary>
    ${v.overruled.length ? `<p class="flag">The code overruled the AI here: ${esc(v.overruled.join("; "))}. The AI had said “${esc(v.ai_said)}”.</p>` : ""}
    ${v.reasoning ? `<p><b>Why:</b> ${esc(v.reasoning)}</p>` : ""}
    ${v.claims.map((c) => `<p><b>Claim:</b> ${esc(c.claim)}</p><blockquote>“${esc(c.quote)}”</blockquote>
      ${c.passage ? `<p class="cap">From ${esc(c.source)}:</p><div class="passage">${esc(c.passage)}</div>` : ""}`).join("")}
    </details>`).join(""));

  const ch = x.checks;
  steps.push(`<h4>The code checks its work</h4><p><b>${ch.passed} of ${ch.total}</b> checks passed.</p>` +
    (ch.failed.length ? `<ul>${ch.failed.map((c) => `<li class="flag">Failed: ${esc(c)}</li>`).join("")}</ul>` : "<p>Every check passed.</p>"));

  const e = x.escalation;
  steps.push(`<h4>Should the customer go to the vulnerable-customer team?</h4><p><b>Decision:</b> ${esc(e.decision)}</p>
    ${e.rule ? `<p class="cap">Set by code: ${esc(e.rule)}.${e.ai_said ? ` The AI had said “${esc(e.ai_said)}”.` : ""}</p>` : ""}
    ${e.triggers.length ? `<ul>${e.triggers.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    ${e.reasoning ? `<p><b>Why:</b> ${esc(e.reasoning)}</p>` : ""}`);

  const mark = { right: "✓ right", wrong: "✗ wrong", unsure: "unsure, so sent to a person" };
  steps.push(`<h4>The answer key</h4><p class="cap">A test agreement with problems planted on purpose, so the right answers are known.</p>
    <ul>${x.answer_key.map((k) => `<li><b>${esc(k.outcome)}:</b> should be ${esc(k.should_be)}; the AI said ${esc(String(k.ai_said).toLowerCase())}.
    <span class="result-${k.result}">${mark[k.result]}</span></li>`).join("")}</ul>`);

  $("steps").innerHTML = steps.map((s) => `<li>${s}</li>`).join("");
}

async function main() {
  const [overview, samples] = await Promise.all([
    fetch("data/overview.json").then((r) => r.json()),
    fetch("data/samples.json").then((r) => r.json()),
  ]);
  const buttons = [...document.querySelectorAll(".toggle button")];
  const pick = (system) => {
    buttons.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.system === system)));
    renderOverview(overview, system);
  };
  buttons.forEach((b) => b.addEventListener("click", () => pick(b.dataset.system)));
  pick(buttons[0].dataset.system);
  renderHealth(overview.health);

  const select = $("pick");
  select.innerHTML = samples.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join("");
  const show = () => renderSample(samples.find((s) => s.id === select.value));
  select.addEventListener("change", show);
  show();
}

main().catch((err) => {
  document.querySelector("main").insertAdjacentHTML("afterbegin",
    `<p class="callout warn">The results could not be loaded (${esc(err.message)}). The code and reports are on GitHub.</p>`);
});
