/* Line grids, QuickBooks style: ⊕ at the start of each line (Add product or service / Add subtotal), a ⠿ handle to
 * drag lines into a new order, and subtotal lines that add up the lines above them. Positions and subtotals are
 * written into the form just before it is sent. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const fmt = (n) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (t) => parseFloat(String(t || "").replace(/,/g, "")) || 0;

  $$("[data-formset]").forEach((wrap) => {
    const table = $("table.grid", wrap);
    if (!table) return;
    const body = table.tBodies[0];
    const form = table.closest("form");
    const L = table.dataset;
    const subField = form && $("[data-subtotals-field]", form);
    const canSub = !!subField;
    const addBtn = $("[data-add-line]", wrap);
    const lineRows = () => Array.from(body.rows).filter((r) => !r.classList.contains("err-row"));

    // ---- the ⊕ menu and the drag handle in the first cell of each line ----
    let menu = null;
    const closeMenu = () => { if (menu) { menu.remove(); menu = null; } };
    function decorate(row) {
      if (row.classList.contains("err-row") || row.dataset.decorated) return;
      row.dataset.decorated = "1";
      const cell = row.cells[0];
      if (!cell) return;
      const tools = document.createElement("span");
      tools.className = "ln-tools";
      tools.innerHTML = (row.classList.contains("sub-row") ? "" : `<button type="button" class="ln-add" aria-label="${L.lAdd || "Add"}" title="${L.lAdd || "Add"}" tabindex="-1">+</button>`) +
        `<span class="ln-drag" aria-hidden="true" title="${L.lMove || "Drag"}">⠿</span>`;
      cell.prepend(tools);
    }
    function insertLineAfter(row) {
      if (!addBtn) return;
      addBtn.click();
      const added = lineRows().filter((r) => !r.classList.contains("sub-row")).pop();
      if (added && row && row.nextSibling !== added) row.after(added);
      decorate(added);
      const first = added && (added.querySelector(".cb-input") || added.querySelector("input:not([type=hidden]), select, textarea"));
      if (first) first.focus();
    }
    function subtotalRow(label) {
      const tr = document.createElement("tr");
      tr.className = "sub-row";
      tr.dataset.label = label || "";
      tr.innerHTML = `<td class="rn"></td><td colspan="1"></td>` +
        `<td class="num sub-total-label">${L.lSubtotal || "Subtotal"}</td><td class="num" data-sub-amount>0.00</td>` +
        `<td class="del"><button class="btn sm danger" type="button" data-del-sub tabindex="-1" aria-label="${L.lDel || "Remove"}" title="${L.lDel || "Remove"}">${trash}</button></td>`;
      decorate(tr);
      return tr;
    }
    const trash = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';

    table.addEventListener("click", (e) => {
      const plus = e.target.closest(".ln-add");
      if (plus) {
        e.preventDefault();
        closeMenu();
        const row = plus.closest("tr");
        menu = document.createElement("div");
        menu.className = "ln-menu";
        menu.innerHTML = `<button type="button" data-ln="line">${L.lAdd || "Add product or service"}</button>` +
          (canSub ? `<button type="button" data-ln="sub">${L.lSub || "Add subtotal"}</button>` : "");
        document.body.appendChild(menu);
        const r = plus.getBoundingClientRect();
        menu.style.top = `${r.bottom + 4}px`;
        menu.style[document.documentElement.dir === "rtl" ? "right" : "left"] =
          document.documentElement.dir === "rtl" ? `${window.innerWidth - r.right}px` : `${r.left}px`;
        menu.addEventListener("click", (ev) => {
          const b = ev.target.closest("[data-ln]");
          if (!b) return;
          if (b.dataset.ln === "line") insertLineAfter(row);
          else { const s = subtotalRow(""); row.after(s); recalcSubs(); }
          closeMenu();
        });
        return;
      }
      const delSub = e.target.closest("[data-del-sub]");
      if (delSub) { delSub.closest("tr").remove(); recalcSubs(); }
    });
    document.addEventListener("click", (e) => { if (menu && !e.target.closest(".ln-menu, .ln-add")) closeMenu(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

    // ---- drag ⠿ to reorder ----
    table.addEventListener("pointerdown", (e) => {
      const handle = e.target.closest(".ln-drag");
      if (!handle) return;
      e.preventDefault();
      const row = handle.closest("tr");
      row.classList.add("ln-dragging");
      handle.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const over = document.elementFromPoint(ev.clientX, ev.clientY);
        const target = over && over.closest("tbody tr");
        if (!target || target === row || target.parentElement !== body || target.classList.contains("err-row")) return;
        const box = target.getBoundingClientRect();
        if (ev.clientY > box.top + box.height / 2) target.after(row); else target.before(row);
      };
      const up = () => {
        row.classList.remove("ln-dragging");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        recalcSubs();
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });

    // ---- subtotal amounts: sum of the line amounts since the previous subtotal ----
    // Columns hidden with the Columns menu don't count, so the subtotal stays under the Amount column.
    // On narrow screens the Description column keeps at least 240px; the grid scrolls sideways instead.
    function fitSubs() {
      const shown = Array.from(table.tHead.rows[0].cells).filter((c) => getComputedStyle(c).display !== "none");
      $$("tr.sub-row > td[colspan]", body).forEach((td) => { td.colSpan = Math.max(shown.length - 4, 1); });
      if (shown.some((c) => c.dataset.col === "description")) {
        const others = shown.filter((c) => c.dataset.col !== "description").reduce((n, c) => n + c.offsetWidth, 0);
        table.style.minWidth = (others + 240) + "px";
      }
    }
    function recalcSubs() {
      fitSubs();
      let running = 0;
      lineRows().forEach((r) => {
        if (r.hidden) return;
        if (r.classList.contains("sub-row")) {
          const out = $("[data-sub-amount]", r);
          if (out) out.textContent = fmt(running);
          running = 0;
        } else {
          const amt = $("[data-line-amount]", r);
          if (amt) running += num(amt.textContent);
        }
      });
    }
    form && form.addEventListener("input", () => setTimeout(recalcSubs, 0));
    form && form.addEventListener("change", () => setTimeout(recalcSubs, 0));

    // ---- existing subtotals, placed by their saved position ----
    let marks = [];
    try { marks = JSON.parse(table.dataset.subtotals || "[]"); } catch (err) { marks = []; }
    lineRows().forEach(decorate);
    if (canSub && marks.length) {
      const withPos = lineRows().map((r) => ({ r, pos: num(($("[data-position]", r) || {}).value) || Infinity }));
      marks.sort((a, b) => a.pos - b.pos).forEach((m) => {
        const before = withPos.find((x) => x.pos > m.pos);
        const s = subtotalRow(m.label);
        if (before) before.r.before(s); else body.appendChild(s);
      });
    }
    new MutationObserver((changes) => changes.forEach((c) => c.addedNodes.forEach((n) => {
      if (n.nodeType === 1 && n.tagName === "TR") decorate(n);
    }))).observe(body, { childList: true });
    setTimeout(recalcSubs, 0);

    // ---- before sending: number the lines and collect the subtotals ----
    form && form.addEventListener("submit", () => {
      const subs = [];
      lineRows().forEach((r, i) => {
        const seq = i + 1;
        if (r.classList.contains("sub-row")) subs.push({ pos: seq, label: r.dataset.label || "" });
        else { const p = $("[data-position]", r); if (p) p.value = seq; }
      });
      if (subField) subField.value = JSON.stringify(subs);
    });
  });
})();
