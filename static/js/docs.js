(function () {
  "use strict";
  const form = document.querySelector("[data-doc-form]");
  const dataEl = document.getElementById("doc-picker");
  if (!form || !dataEl) return;
  const picker = JSON.parse(JSON.parse(dataEl.textContent));
  window.TRIB_PICKER = picker; // grid.js uses it to search products by SKU, barcode and both names
  const num = (v) => parseFloat(v) || 0;
  const r2 = (n) => Math.round(n * 100) / 100;
  const fmt = (n) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const field = (row, name) => row.querySelector(`[name$="-${name}"]`);
  const head = (name) => form.querySelector(`[name="${name}"]`);

  // Totals. "Amounts are: inclusive of VAT" means each rate already contains the VAT, so it is taken out.
  function recalc() {
    const vatMode = head("prices_include_tax");
    const inclusive = vatMode && vatMode.value === "True";
    let subtotal = 0, tax = 0;
    form.querySelectorAll(".doc-lines tbody tr").forEach((row) => {
      if (row.hidden || !field(row, "qty")) return;
      const qty = num(field(row, "qty").value);
      const price = num((field(row, "unit_price") || field(row, "unit_cost") || {}).value);
      const disc = num((field(row, "discount_pct") || {}).value);
      const amount = r2(qty * price * (1 - disc / 100));
      const taxSel = field(row, "tax_rate");
      const rate = taxSel && taxSel.value ? num(picker.taxes[taxSel.value]) : 0;
      const net = inclusive && rate ? r2(amount * 100 / (100 + rate)) : amount;
      const lineTax = inclusive && rate ? r2(amount - net) : r2(net * rate / 100);
      const out = row.querySelector("[data-line-amount]");
      if (out) out.textContent = fmt(amount);
      subtotal += net;
      tax += lineTax;
    });
    const set = (k, v) => form.querySelectorAll(`[data-doc-total="${k}"]`).forEach((el) => { el.textContent = fmt(v); });
    set("subtotal", subtotal); set("tax", tax); set("total", subtotal + tax);
    const note = form.querySelector("[data-vat-mode-note]");
    if (note) note.hidden = !inclusive;
  }

  // Fill a field from the chosen product or customer unless the user typed something of their own there.
  // A value we filled earlier (remembered in data-auto) is replaced when another one is chosen.
  function autofill(el, value, isEmpty) {
    if (!el) return;
    if (isEmpty(el) || (el.dataset.auto !== undefined && el.value === el.dataset.auto)) {
      el.value = value;
      el.dataset.auto = el.value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  const empty = (el) => !el.value;

  // Terms → due date (Net 30 = 30 days after the invoice date).
  const TERM_DAYS = { receipt: 0, net15: 15, net30: 30, net45: 45, net60: 60, net90: 90 };
  function dueFromTerms() {
    const terms = head("terms"), day = head("date"), due = head("due_date");
    if (!day || !due || !day.value) return;
    let days = null;
    if (terms) days = TERM_DAYS[terms.value] ?? null;
    else if (due.dataset.days !== undefined && (!due.value || due.value === due.dataset.auto)) days = num(due.dataset.days);
    if (days === null) return;
    const d = new Date(day.value + "T00:00:00");
    d.setDate(d.getDate() + days);
    due.value = d.toISOString().slice(0, 10);
    due.dataset.auto = due.value;
  }
  const termsFor = (days) => Object.keys(TERM_DAYS).find((k) => TERM_DAYS[k] === days) || "custom";

  // Price rules (inventory/pricing.py): the most specific rule for this customer, product and date sets the price.
  function rulePrice(itemId, base) {
    const rules = picker.rules || [];
    const cust = (head("customer") || {}).value;
    const day = (head("date") || {}).value || "";
    const id = Number(itemId), cid = cust ? Number(cust) : null;
    const r = rules.find((x) => (x.customers === null || (cid !== null && x.customers.includes(cid)))
      && (x.items === null || x.items.includes(id))
      && (!day || ((!x.start || day >= x.start) && (!x.end || day <= x.end))));
    if (!r) return { price: base, rule: "" };
    const price = num(base), amount = num(r.amount);
    const change = r.method === "percent" ? price * amount / 100 : amount;
    let p = Math.max(r.dir === "up" ? price + change : price - change, 0);
    if (r.rounding === "whole") p = Math.round(p);
    else if (r.rounding === "half") p = Math.round(p * 2) / 2;
    else if (r.rounding === "nickel") p = Math.round(p * 20) / 20;
    else if (r.rounding === "end99") p = Math.max(Math.round(p) - 0.01, 0);
    return { price: p.toFixed(2), rule: r.name };
  }

  // Customer / supplier chosen: email, bill to, ship to and terms come from its card.
  const partySel = head("customer") || head("supplier");
  const editLink = form.querySelector("[data-party-edit]");
  function partyChanged(initial) {
    const p = partySel && picker.parties ? picker.parties[partySel.value] : null;
    if (editLink) { editLink.hidden = !p; if (p) editLink.href = p.edit; }
    if (!p || initial) return;
    autofill(head("email_to"), p.email || "", empty);
    autofill(head("bill_to"), p.bill || "", empty);
    autofill(head("ship_to"), p.ship || "", empty);
    const terms = head("terms");
    if (terms) { terms.value = termsFor(p.days); }
    const due = head("due_date");
    if (due) due.dataset.days = p.days;
    dueFromTerms();
  }

  form.addEventListener("change", (e) => {
    const sel = e.target;
    if (sel.matches('select[name$="-item"]') && sel.value && picker.items[sel.value]) {
      const row = sel.closest("tr");
      const item = picker.items[sel.value];
      autofill(field(row, "description"), item.desc, empty);
      const priceEl = field(row, "unit_price") || field(row, "unit_cost");
      const ruled = rulePrice(sel.value, item.price);
      autofill(priceEl, ruled.price, (el) => !el.value || num(el.value) === 0);
      if (priceEl) priceEl.title = ruled.rule ? `${picker.ruleLabel || "Price rule"}: ${ruled.rule}` : "";
      const taxSel = field(row, "tax_rate");
      autofill(taxSel, item.tax || picker.defaultTax || "", empty);
      const qty = field(row, "qty");
      if (qty && !qty.value) qty.value = 1;
    }
    if (sel === partySel) partyChanged(false);
    if (sel.name === "terms" || sel.name === "date") dueFromTerms();
    if (sel.name === "due_date" && head("terms") && head("terms").value !== "custom") {
      head("terms").value = "custom"; // a typed due date overrides the terms
    }
    recalc();
  });
  form.addEventListener("input", recalc);
  form.addEventListener("click", (e) => { if (e.target.closest("[data-del-line],[data-add-line]")) setTimeout(recalc, 0); });
  partyChanged(true);
  recalc();

  // Cc / Bcc fields open on request.
  const ccBtn = form.querySelector("[data-ccbcc]"), ccBox = form.querySelector("[data-ccbcc-box]");
  if (ccBtn && ccBox) ccBtn.addEventListener("click", () => {
    ccBox.hidden = !ccBox.hidden;
    ccBtn.setAttribute("aria-expanded", String(!ccBox.hidden));
    if (!ccBox.hidden) { const i = ccBox.querySelector("input"); if (i) i.focus(); }
  });

  // Tags: typed as chips; the form still sends "a, b, c".
  form.querySelectorAll("input[data-tags]").forEach((input) => {
    const wrap = document.createElement("div");
    wrap.className = "tags-input";
    const typer = document.createElement("input");
    typer.type = "text";
    typer.placeholder = input.placeholder;
    typer.setAttribute("aria-label", input.closest(".field").querySelector("label").textContent);
    input.type = "hidden";
    input.after(wrap);
    wrap.appendChild(typer);
    let tags = input.value.split(",").map((t) => t.trim()).filter(Boolean);
    const sync = () => {
      wrap.querySelectorAll(".chip").forEach((c) => c.remove());
      tags.forEach((t, i) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = t;
        const x = document.createElement("button");
        x.type = "button";
        x.textContent = "×";
        x.setAttribute("aria-label", "× " + t);
        x.addEventListener("click", () => { tags.splice(i, 1); sync(); });
        chip.appendChild(x);
        wrap.insertBefore(chip, typer);
      });
      input.value = tags.join(", ");
    };
    const add = () => {
      const t = typer.value.replace(/,/g, " ").trim();
      if (t && !tags.some((x) => x.toLowerCase() === t.toLowerCase())) tags.push(t);
      typer.value = "";
      sync();
    };
    typer.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
      else if (e.key === "Backspace" && !typer.value && tags.length) { tags.pop(); sync(); }
    });
    typer.addEventListener("blur", add);
    wrap.addEventListener("click", (e) => { if (e.target === wrap) typer.focus(); });
    sync();
  });

  // Typing in the form header must not submit it with Enter.
  form.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches(".qb-head input:not([type=submit])")) e.preventDefault();
  });
})();
