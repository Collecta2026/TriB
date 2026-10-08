(function () {
  "use strict";
  const form = document.querySelector("[data-doc-form]");
  const dataEl = document.getElementById("doc-picker");
  if (!form || !dataEl) return;
  const picker = JSON.parse(JSON.parse(dataEl.textContent));
  const num = (v) => parseFloat(v) || 0;
  const fmt = (n) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const field = (row, name) => row.querySelector(`[name$="-${name}"]`);

  function recalc() {
    let subtotal = 0, tax = 0;
    form.querySelectorAll(".doc-lines tbody tr").forEach((row) => {
      if (row.hidden || !field(row, "qty")) return;
      const qty = num(field(row, "qty").value);
      const price = num((field(row, "unit_price") || field(row, "unit_cost") || {}).value);
      const disc = num((field(row, "discount_pct") || {}).value);
      const net = Math.round(qty * price * (1 - disc / 100) * 100) / 100;
      const taxSel = field(row, "tax_rate");
      const rate = taxSel && taxSel.value ? num(picker.taxes[taxSel.value]) : 0;
      const lineTax = Math.round(net * rate) / 100;
      const out = row.querySelector("[data-line-amount]");
      if (out) out.textContent = fmt(net);
      subtotal += net;
      tax += lineTax;
    });
    const set = (k, v) => { const el = form.querySelector(`[data-doc-total="${k}"]`); if (el) el.textContent = fmt(v); };
    set("subtotal", subtotal); set("tax", tax); set("total", subtotal + tax);
  }

  form.addEventListener("change", (e) => {
    const sel = e.target;
    if (sel.matches('select[name$="-item"]') && sel.value && picker.items[sel.value]) {
      const row = sel.closest("tr");
      const item = picker.items[sel.value];
      const desc = field(row, "description");
      if (desc && !desc.value) desc.value = item.desc;
      const price = field(row, "unit_price") || field(row, "unit_cost");
      if (price && (!price.value || num(price.value) === 0)) price.value = item.price;
      const taxSel = field(row, "tax_rate");
      if (taxSel && !taxSel.value) taxSel.value = item.tax || picker.defaultTax || "";
      const qty = field(row, "qty");
      if (qty && !qty.value) qty.value = 1;
    }
    recalc();
  });
  form.addEventListener("input", recalc);
  form.addEventListener("click", (e) => { if (e.target.closest("[data-del-line],[data-add-line]")) setTimeout(recalc, 0); });
  recalc();
})();
