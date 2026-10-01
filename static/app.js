// The interface keeps the current assessment in memory, without browser storage.
const exampleHome = {
  postcode: "3056", dwelling: "house", occupants: "2", heated_area: "60",
  heating: "gas", cooling: "fan", cooking: "gas", hot_water: "gas",
  insulation: "unknown", comfort: "both", other_gas: "no", solar: "no",
  electricity_price: "30", gas_price: "3", gas_daily_charge: "100"
};

document.getElementById("example-button").addEventListener("click", () => {
  const form = document.getElementById("assessment-form");
  for (const [name, value] of Object.entries(exampleHome)) {
    form.elements[name].value = value;
  }
  const message = document.getElementById("app-message");
  message.textContent = "Example loaded: two renters in a Brunswick home with gas heating, cooking and hot water. You can change any answer.";
  message.hidden = false;
  invalidateAssessment();
});

const form = document.getElementById("assessment-form");
let homeAnswers = null;
let currentAssessment = null;
let selectedUpgrades = [];
let disconnectGas = false;
let assessmentRequest = 0;
let letterRevision = null;
let letterIsEdited = false;
let generationInProgress = false;

function invalidateLetter() {
  letterRevision = null;
  document.querySelector('[data-step="letter"]').disabled = true;
  for (const button of document.querySelectorAll(".letter-actions button")) button.disabled = true;
}

// Escape all inserted text, including anything returned from an endpoint.
function escapeText(value) {
  const element = document.createElement("span");
  element.textContent = String(value);
  return element.innerHTML;
}

function moneyRange(values) {
  if (!values) return "Not estimated";
  const sorted = [...values].sort((first, second) => first - second);
  const format = new Intl.NumberFormat("en-AU", {style: "currency", currency: "AUD", maximumFractionDigits: 0});
  if (Math.round(sorted[0]) === Math.round(sorted[1])) return format.format(sorted[0]);
  return `${format.format(sorted[0])}–${format.format(sorted[1])}`;
}

function describeChange(values, emissions = false) {
  if (!values) return "Not estimated";
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (Math.abs(low) < 0.5 && Math.abs(high) < 0.5) return "No estimated change";
  let amount;
  if (emissions) {
    const magnitudes = values.map(value => Math.abs(value));
    amount = `${Math.round(Math.min(...magnitudes)).toLocaleString()}–${Math.round(Math.max(...magnitudes)).toLocaleString()} kg CO₂e`;
  } else {
    amount = moneyRange(values.map(value => Math.abs(value)));
  }
  if (high <= 0) return `${amount} more / year`;
  if (low >= 0) return `${amount} less / year`;
  return `${emissions ? `${low.toFixed(0)} to ${high.toFixed(0)} kg CO₂e` : moneyRange(values)} change / year`;
}

function showMessage(text) {
  const message = document.getElementById("app-message");
  message.textContent = text;
  message.hidden = !text;
}

function showStep(step) {
  for (const panel of document.querySelectorAll(".step-panel")) {
    panel.hidden = panel.id !== `${step}-step`;
  }
  for (const button of document.querySelectorAll(".step-button")) {
    const active = button.dataset.step === step;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  }
  document.querySelector(".introduction").hidden = step !== "home";
  const heading = document.getElementById(`${step}-title`);
  heading.focus({preventScroll: true});
  document.querySelector(".journey").scrollIntoView({block: "start"});
}

function invalidateAssessment() {
  assessmentRequest += 1;
  currentAssessment = null;
  document.querySelector('[data-step="results"]').disabled = true;
  invalidateLetter();
}

form.addEventListener("input", invalidateAssessment);
form.addEventListener("change", invalidateAssessment);

function showFieldErrors(errors) {
  const summary = document.getElementById("form-errors");
  summary.replaceChildren();
  for (const field of form.elements) field.removeAttribute("aria-invalid");
  const introduction = document.createElement("p");
  introduction.textContent = "Please check these details:";
  summary.append(introduction);
  const list = document.createElement("ul");
  for (const [field, message] of Object.entries(errors)) {
    const item = document.createElement("li");
    const input = form.elements[field];
    if (input) {
      input.setAttribute("aria-invalid", "true");
      const link = document.createElement("a");
      link.href = `#${field}`;
      link.textContent = message;
      link.addEventListener("click", event => {
        event.preventDefault();
        const details = input.closest("details");
        if (details) details.open = true;
        input.focus();
      });
      item.append(link);
    } else item.textContent = message;
    list.append(item);
  }
  summary.append(list);
  summary.hidden = false;
  summary.tabIndex = -1;
  summary.focus();
}

async function requestAssessment(firstAssessment = false) {
  const requestNumber = ++assessmentRequest;
  invalidateLetter();
  const payload = {home: homeAnswers, disconnect_gas: disconnectGas};
  if (!firstAssessment) payload.selected_upgrades = selectedUpgrades;
  const submit = document.getElementById("assess-button");
  submit.disabled = true;
  submit.textContent = "Comparing your options…";
  document.getElementById("prepare-letter").disabled = true;
  document.getElementById("results-content").setAttribute("aria-busy", "true");
  try {
    const response = await fetch("/api/assessment", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
    });
    const report = await response.json();
    if (requestNumber !== assessmentRequest) return;
    if (!response.ok) {
      showStep("home");
      showFieldErrors(report.errors || {form: report.error || "Please check your answers."});
      return;
    }
    currentAssessment = report;
    selectedUpgrades = report.selected_upgrades;
    disconnectGas = report.gas_supply.selected;
    document.getElementById("form-errors").hidden = true;
    document.querySelector('[data-step="results"]').disabled = false;
    document.querySelector('[data-step="letter"]').disabled = true;
    document.getElementById("prepare-letter").disabled = selectedUpgrades.length === 0;
    renderResults(report);
    showMessage("");
    if (firstAssessment) showStep("results");
  } catch (error) {
    if (requestNumber === assessmentRequest) showMessage("The local server could not complete the comparison. Your answers are still here; please try again.");
  } finally {
    submit.disabled = false;
    submit.textContent = "See my options";
    document.getElementById("results-content").removeAttribute("aria-busy");
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  homeAnswers = Object.fromEntries(new FormData(form));
  disconnectGas = false;
  requestAssessment(true);
});

function renderUpgrade(component) {
  const checkbox = component.can_upgrade
    ? `<input type="checkbox" id="upgrade-${component.id}" data-upgrade="${component.id}" ${component.selected ? "checked" : ""} aria-label="Include ${escapeText(component.title)} in my request">`
    : '<span aria-hidden="true" class="field-number">—</span>';
  let tag = "Not estimated";
  let comparison = component.reason || "";
  let cost = "Not estimated";
  if (component.supported) {
    tag = component.can_upgrade ? "An option to consider" : "Already an efficient electric type";
    comparison = `${escapeText(component.current_label)}${component.can_upgrade ? ` to ${escapeText(component.target_label)}` : ""}`;
    cost = component.can_upgrade ? describeChange(component.savings) : "No change proposed";
  }
  const title = component.can_upgrade
    ? `<label for="upgrade-${component.id}">${escapeText(component.title)}</label>`
    : escapeText(component.title);
  const costComparison = component.supported
    ? `<p>Current: ${moneyRange(component.current.cost)} / year<br>Selected scenario: ${moneyRange(component.proposed.cost)} / year</p>`
    : "";
  return `<article class="upgrade-row">
    <div>${checkbox}</div>
    <div><p class="upgrade-tag">${tag}</p><h3>${title}</h3><p>${comparison}</p>
      <p>${escapeText(component.benefit)}</p>${costComparison}
      <details id="details-${component.id}"><summary>Installation & possible assistance</summary><p>${escapeText(component.installation)}</p><p><a href="${escapeText(component.rebate_url)}" target="_blank" rel="noopener noreferrer">Check Victorian Energy Upgrades</a>. Eligibility and the actual discount must be confirmed by an accredited provider.</p></details>
    </div>
    <div class="upgrade-cost"><strong>${escapeText(cost)}</strong><span class="small-text">${component.supported ? "Selected running-cost change" : "Excluded from the subtotal"}</span></div>
  </article>`;
}

function renderResults(report) {
  const focusId = document.activeElement?.id;
  const openDetails = [...document.querySelectorAll("#results-content details[open]")].map(element => element.id);
  const homeType = report.home.dwelling === "apartment" ? "Apartment or unit" : "House or townhouse";
  document.getElementById("home-summary").textContent = `${homeType} · ${report.home.postcode} · ${report.home.occupants} ${report.home.occupants === 1 ? "person" : "people"}`;
  const totals = report.totals;
  const alerts = report.notes.filter(note => note.startsWith("Only") || note.startsWith("This is a grid-priced"));
  const insulationInput = report.insulation.available
    ? `<input type="checkbox" id="upgrade-insulation" data-upgrade="insulation" ${report.insulation.selected ? "checked" : ""} aria-label="Include insulation assessment in my request">`
    : '<span aria-hidden="true" class="field-number">—</span>';
  const insulationTitle = report.insulation.available ? '<label for="upgrade-insulation">Insulation & comfort</label>' : "Insulation & comfort";
  const gasNote = report.gas_supply.eligible
    ? "All identified gas uses are replaced in this scenario. The connection/account must actually end before this charge disappears. Disconnection fees need a separate quote."
    : "To include this saving, replace every gas appliance and confirm that no other or unidentified gas uses remain. Shared or solar-boosted hot water needs an individual check.";

  document.getElementById("results-content").innerHTML = `
    <div class="cost-overview" aria-label="Annual running cost comparison">
      <div><p class="eyebrow">Your current appliances</p><div class="cost-range">${moneyRange(totals.current_cost)}</div><p class="cost-label">per year · ${report.estimated_count} of 3 categories estimated</p></div>
      <div><p class="eyebrow">With your selected changes</p><div class="cost-range">${moneyRange(totals.proposed_cost)}</div><p class="cost-label">per year · same usage scenarios</p></div>
      <div class="saving-strip"><p><strong>${escapeText(describeChange(totals.cost_savings))}</strong><br>Appliance running costs</p><p>${escapeText(describeChange(totals.emissions_savings, true))}<br>Operational emissions · 2025 factors</p></div>
    </div>
    <p class="report-caption">Estimated running costs for assessed appliances. These are illustrative low/high usage scenarios, not your whole energy bill. Fixed gas charges are considered separately below.</p>
    ${alerts.map(note => `<div class="report-alert">${escapeText(note)}</div>`).join("")}
    <div class="section-heading"><div><h2>Choose what’s worth discussing.</h2><p class="muted">Your selection shapes the comparison and the landlord request.</p></div></div>
    <div class="upgrade-list">
      ${report.components.map(renderUpgrade).join("")}
      <article class="upgrade-row"><div>${insulationInput}</div><div><p class="upgrade-tag">Comfort comes first</p><h3>${insulationTitle}</h3><p>${escapeText(report.insulation.guidance)}</p><details id="details-insulation"><summary>What this assessment can tell you</summary><p>We do not infer an insulation R-value or a personal heat-health score. A qualified assessment should consider insulation, shading, draughts and the building together.</p><a href="https://www.yourhome.gov.au/passive-design/insulation" target="_blank" rel="noopener noreferrer">Read the Your Home insulation guide</a></details></div><div class="upgrade-cost"><strong>Assessment first</strong><span class="small-text">Guidance only · no dollar estimate</span></div></article>
    </div>
    <div class="supply-option"><label for="disconnect-gas"><input type="checkbox" id="disconnect-gas" ${report.gas_supply.eligible ? "" : "disabled"} ${report.gas_supply.selected ? "checked" : ""}> Include ending the gas connection</label><p>${gasNote}</p><p>${report.gas_supply.selected ? `Additional supply-charge saving: <strong>${moneyRange([report.gas_supply.annual_saving, report.gas_supply.annual_saving])} / year</strong>. Combined running-cost and supply-charge change: <strong>${escapeText(describeChange(totals.total_savings))}</strong>.` : `At your selected tariff, the gas supply charge is ${moneyRange([report.gas_supply.possible_annual_saving, report.gas_supply.possible_annual_saving])} / year. It is not included in the appliance totals.`}</p></div>
    <section class="tenant-actions"><p class="eyebrow">For you · Practical next steps</p><h2>A few things you can do now.</h2><ul>${report.tenant_actions.map(action => `<li>${escapeText(action)}</li>`).join("")}</ul></section>
    <details class="report-details" id="report-assumptions"><summary>See the assumptions behind these numbers</summary><ul>${report.assumptions.map(assumption => `<li>${escapeText(assumption)}</li>`).join("")}</ul></details>
    <details class="report-details" id="report-limitations"><summary>What is outside this estimate?</summary><ul>${report.notes.map(note => `<li>${escapeText(note)}</li>`).join("")}</ul></details>
    <p class="field-help">Sources reviewed ${escapeText(report.reviewed_on)}. <a href="/methodology" target="_blank" rel="noopener noreferrer">Read the full methodology and sources</a>.</p>`;

  for (const input of document.querySelectorAll("[data-upgrade]")) {
    input.addEventListener("change", () => {
      selectedUpgrades = [...document.querySelectorAll("[data-upgrade]:checked")].map(checkbox => checkbox.dataset.upgrade);
      requestAssessment();
    });
  }
  document.getElementById("disconnect-gas").addEventListener("change", event => {
    disconnectGas = event.target.checked;
    requestAssessment();
  });
  for (const id of openDetails) {
    const details = document.getElementById(id);
    if (details) details.open = true;
  }
  if (focusId) document.getElementById(focusId)?.focus({preventScroll: true});
}

async function generateLetter() {
  if (!currentAssessment || selectedUpgrades.length === 0 || generationInProgress) return;
  if (letterIsEdited && !window.confirm("Replace your edited letter with a new draft? Copy or download your changes first if you want to keep them.")) return;
  generationInProgress = true;
  const requestRevision = assessmentRequest;
  document.querySelector('[data-step="letter"]').disabled = false;
  showMessage("");
  showStep("letter");
  const textarea = document.getElementById("letter-text");
  textarea.readOnly = true;
  textarea.setAttribute("aria-busy", "true");
  document.getElementById("letter-status").textContent = "Preparing your draft from the selected improvements…";
  document.getElementById("letter-mode").textContent = "Preparing your request";
  const controls = document.querySelectorAll(".letter-actions button, #regenerate-letter");
  for (const button of controls) button.disabled = true;
  try {
    const response = await fetch("/api/letter", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({home: homeAnswers, selected_upgrades: selectedUpgrades, disconnect_gas: disconnectGas})
    });
    const draft = await response.json();
    if (requestRevision !== assessmentRequest) return;
    if (!response.ok) throw new Error(draft.error || "Could not prepare this request.");
    textarea.value = draft.letter;
    letterRevision = requestRevision;
    letterIsEdited = false;
    document.getElementById("letter-mode").textContent = draft.mode === "ai" ? "AI-assisted draft · Review before sending" : "Personalised template · Ready to edit";
    document.getElementById("letter-status").textContent = draft.message;
    const names = {heating: "Heating & cooling", cooking: "Induction cooking", hot_water: "Heat-pump hot water", insulation: "Insulation assessment"};
    document.getElementById("letter-selection").innerHTML = `<div class="request-summary"><p class="eyebrow">In this request</p><ul>${draft.selected_upgrades.map(id => `<li>${escapeText(names[id])}</li>`).join("")}</ul></div>`;
  } catch (error) {
    if (requestRevision !== assessmentRequest) return;
    document.getElementById("letter-status").textContent = "The request could not be prepared. Any previous draft has been kept below, but may not match your current choices. Check the local server and try again before exporting.";
    document.getElementById("letter-mode").textContent = "Draft unavailable";
  } finally {
    generationInProgress = false;
    textarea.readOnly = false;
    textarea.removeAttribute("aria-busy");
    for (const button of controls) {
      button.disabled = button.id === "regenerate-letter"
        ? requestRevision !== assessmentRequest
        : letterRevision !== assessmentRequest || !textarea.value;
    }
  }
}

document.getElementById("prepare-letter").addEventListener("click", generateLetter);
document.getElementById("regenerate-letter").addEventListener("click", generateLetter);
document.getElementById("letter-text").addEventListener("input", () => { letterIsEdited = true; });
document.getElementById("back-to-options").addEventListener("click", () => showStep("results"));
for (const button of document.querySelectorAll("[data-go-home]")) button.addEventListener("click", () => showStep("home"));
for (const button of document.querySelectorAll(".step-button")) button.addEventListener("click", () => showStep(button.dataset.step));

document.getElementById("copy-letter").addEventListener("click", async () => {
  const textarea = document.getElementById("letter-text");
  try {
    await navigator.clipboard.writeText(textarea.value);
    document.getElementById("letter-status").textContent = "Letter copied. Paste it into your own email or document when you’re ready.";
  } catch (error) {
    textarea.focus();
    textarea.select();
    document.getElementById("letter-status").textContent = "Your browser could not copy automatically. The text is selected; use Command+C or Ctrl+C.";
  }
});

document.getElementById("download-letter").addEventListener("click", () => {
  const content = document.getElementById("letter-text").value;
  const file = new Blob([content], {type: "text/plain;charset=utf-8"});
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = "my-home-upgrade-request.txt";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.getElementById("letter-status").textContent = "Your edited letter has been prepared as a text download.";
});

function preparePrint() {
  document.getElementById("print-document").textContent = document.getElementById("letter-text").value;
}
document.getElementById("print-letter").addEventListener("click", () => {
  preparePrint();
  window.print();
});
window.addEventListener("beforeprint", preparePrint);
