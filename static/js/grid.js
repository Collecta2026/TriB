/* Entry grids (QuickBooks-style) for tables with class "grid":
 *  - compact rows; text boxes marked data-autogrow grow and shrink with their text
 *  - drag a column edge to resize it, double-click the edge to reset; widths are remembered on this PC
 *  - Columns menu to show or hide optional columns (a column with values is always shown)
 *  - keyboard: Tab moves along the line, Enter goes to the next line (adding one at the end), Ctrl+Delete removes a line
 *  - product / account / party pickers: a drop-down list to choose from, and type-ahead that selects the best match
 *    from the first letter typed (SKU, barcode, English or Arabic name), changing as you type
 */
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const rtl = () => document.documentElement.dir === "rtl";
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(key) { try { return JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch (err) { return {}; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (err) { /* storage unavailable */ } },
  };
  const toolsEl = $("[data-grid-tools]");
  const label = (name, fallback) => (toolsEl && toolsEl.dataset[name]) || fallback;
  const ALWAYS = new Set(["rn", "del", "item", "qty", "amount", "unit_price", "unit_cost", "debit", "credit", "qty_change"]);
  const FIELD = 'input:not([type=hidden]):not([type=checkbox]), select:not(.cb-native), textarea';

  // ---------- Text boxes that grow with their text ----------
  function grow(el) {
    el.style.height = "auto";
    el.style.height = el.scrollHeight + 2 + "px";
  }
  document.addEventListener("input", (e) => { if (e.target.matches("textarea[data-autogrow]")) grow(e.target); });

  // ---------- Combobox: drop-down list + type-ahead ----------
  function enhance(select) {
    if (select.dataset.cb) return;
    select.dataset.cb = "1";
    const wrap = document.createElement("div");
    wrap.className = "cb";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("cb-native");
    select.tabIndex = -1;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "cb-input";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.placeholder = label("lSearch", "Type or choose…");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    if (select.id) { input.id = select.id + "_cb"; const lab = $(`label[for="${select.id}"]`); if (lab) lab.htmlFor = input.id; }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cb-btn";
    btn.tabIndex = -1;
    btn.setAttribute("aria-label", label("lList", "Show list"));
    btn.textContent = "▾";
    wrap.append(input, btn);

    let list = null, shown = [], active = -1;
    const current = () => { const o = select.options[select.selectedIndex]; return o && o.value ? o.text : ""; };
    const options = () => {
      const items = (window.TRIB_PICKER && window.TRIB_PICKER.items) || {};
      return Array.from(select.options).filter((o) => o.value).map((o) => {
        const p = select.name.endsWith("-item") ? items[o.value] : null;
        return { value: o.value, text: o.text, search: ((p && p.search) || o.text).toLowerCase(),
                 sku: ((p && p.sku) || "").toLowerCase(), barcode: ((p && p.barcode) || "").toLowerCase() };
      });
    };
    function rank(q) {
      const all = options();
      if (!q) return all;
      const exact = [], starts = [], contains = [];
      all.forEach((o) => {
        if (o.sku === q || o.barcode === q) exact.push(o);
        else if (o.sku.startsWith(q) || o.text.toLowerCase().startsWith(q) || o.search.split(/[\s·,/-]+/).some((w) => w.startsWith(q))) starts.push(o);
        else if (o.search.includes(q) || o.text.toLowerCase().includes(q)) contains.push(o);
      });
      return exact.concat(starts, contains);
    }
    function choose(o) {
      const before = select.value;
      select.value = o ? o.value : "";
      if (select.value !== before) select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    function place() {
      const r = input.getBoundingClientRect();
      const width = Math.max(r.width + 24, 280);
      list.style.minWidth = width + "px";
      const lh = Math.min(list.scrollHeight, 300);
      const below = window.innerHeight - r.bottom;
      list.style.top = (below < lh + 8 && r.top > lh + 8 ? r.top - lh - 2 : r.bottom + 2) + "px";
      const lw = list.offsetWidth || width;
      let left = rtl() ? r.right + 24 - lw : r.left;
      left = Math.max(8, Math.min(left, document.documentElement.clientWidth - lw - 8));
      list.style.left = left + "px";
    }
    function highlight(i) {
      active = i;
      $$("li[data-i]", list).forEach((li) => li.classList.toggle("on", +li.dataset.i === i));
      const on = $("li.on", list);
      if (on) on.scrollIntoView({ block: "nearest" });
    }
    function open(q) {
      shown = rank(q);
      if (!list) {
        list = document.createElement("ul");
        list.className = "cb-list";
        list.setAttribute("role", "listbox");
        document.body.appendChild(list);
        list.addEventListener("mousedown", (e) => {
          e.preventDefault();
          const li = e.target.closest("li[data-i]");
          if (li) pick(+li.dataset.i);
        });
      }
      list.innerHTML = shown.length
        ? shown.slice(0, 300).map((o, i) => `<li role="option" data-i="${i}">${esc(o.text)}</li>`).join("")
        : `<li class="none">${esc(label("lNone", "No match"))}</li>`;
      list.hidden = false;
      wrap.dataset.open = "1";
      input.setAttribute("aria-expanded", "true");
      place();
      highlight(shown.findIndex((o) => o.value === select.value));
    }
    function close() {
      if (list) list.hidden = true;
      delete wrap.dataset.open;
      input.setAttribute("aria-expanded", "false");
    }
    function pick(i) {
      const o = shown[i];
      if (!o) return;
      choose(o);
      input.value = o.text;
      close();
    }

    input.value = current();
    input.addEventListener("focus", () => input.select());
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      open(q);
      if (q && shown.length) { choose(shown[0]); highlight(0); } // select from the first letter, update as you type
      else if (!q) choose(null);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || (e.key === "F4")) {
        e.preventDefault();
        if (!wrap.dataset.open) { open(""); return; }
        if (e.key === "F4") { close(); return; }
        const i = Math.max(0, Math.min(shown.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
        highlight(i);
        choose(shown[i]);
      } else if (e.key === "Enter" && wrap.dataset.open) {
        e.preventDefault();
        e.stopPropagation();
        if (active >= 0) pick(active); else { close(); input.value = current(); }
      } else if (e.key === "Escape" && wrap.dataset.open) {
        e.preventDefault();
        e.stopPropagation();
        close();
        input.value = current();
      } else if (e.key === "Tab") {
        close();
        input.value = current();
      }
    });
    input.addEventListener("blur", () => setTimeout(() => { close(); input.value = current(); }, 120));
    btn.addEventListener("mousedown", (e) => e.preventDefault());
    btn.addEventListener("click", () => {
      if (wrap.dataset.open) { close(); return; }
      input.focus();
      open("");
    });
    select.addEventListener("change", () => { if (document.activeElement !== input) input.value = current(); });
    const reposition = () => { if (wrap.dataset.open) place(); };
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
  }

  function enhanceRow(root) {
    $$('select[name$="-item"], select[name$="-account"], select[name$="-cost_center"], select[name$="-project"]', root).forEach(enhance);
    $$("textarea[data-autogrow]", root).forEach(grow);
  }

  // ---------- Grids ----------
  function setupGrid(table) {
    const key = "trib.grid." + (table.dataset.grid || "default");
    const state = Object.assign({ w: {}, show: [], hide: [] }, store.get(key));
    const save = () => store.set(key, state);
    const gid = "g" + Math.random().toString(36).slice(2, 9);
    table.dataset.gid = gid;
    const styleEl = document.createElement("style");
    document.head.appendChild(styleEl);
    const heads = Array.from(table.tHead.rows[0].cells);
    const defaults = (table.dataset.defaultHidden || "").split(/\s+/).filter(Boolean);
    const body = table.tBodies[0];

    const hasValues = (col) => $$(`td[data-field="${col}"]`, body).some((td) => {
      if (td.closest("tr").hidden) return false;
      const el = $("input:not([type=hidden]):not([type=checkbox]), select, textarea", td);
      return el && el.value && !/^0*(\.0*)?$/.test(el.value);
    });
    function hidden() {
      const set = new Set(defaults.filter((c) => !state.show.includes(c)));
      state.hide.forEach((c) => set.add(c));
      return Array.from(set).filter((c) => !ALWAYS.has(c) && !hasValues(c));
    }
    function applyColumns() {
      styleEl.textContent = hidden().map((c) =>
        `table[data-gid="${gid}"] th[data-col="${c}"], table[data-gid="${gid}"] td[data-field="${c}"] { display: none; }`).join("\n");
      syncMenu();
    }
    function applyWidths() {
      heads.forEach((th) => { const c = th.dataset.col; th.style.width = state.w[c] ? state.w[c] + "px" : ""; });
    }

    // Resize handles
    heads.forEach((th) => {
      const col = th.dataset.col;
      if (!col || col === "rn" || col === "del") return;
      const handle = document.createElement("span");
      handle.className = "col-rz";
      handle.title = label("lResize", "Drag to resize · double-click to reset");
      th.appendChild(handle);
      handle.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        handle.setPointerCapture(e.pointerId);
        handle.classList.add("on");
        const startX = e.clientX, startW = th.getBoundingClientRect().width;
        const move = (ev) => {
          const w = Math.max(48, Math.round(startW + (ev.clientX - startX) * (rtl() ? -1 : 1)));
          th.style.width = w + "px";
          state.w[col] = w;
        };
        const up = () => {
          handle.classList.remove("on");
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", up);
          save();
        };
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", up);
      });
      handle.addEventListener("dblclick", () => { delete state.w[col]; save(); applyWidths(); });
    });

    // Columns menu + reset
    const tools = $("[data-grid-tools]", table.closest("[data-formset]") || document);
    let menu = null;
    function syncMenu() {
      if (!menu) return;
      const off = new Set(hidden());
      $$("input[data-col]", menu).forEach((box) => {
        box.checked = !off.has(box.dataset.col);
        box.disabled = hasValues(box.dataset.col);
      });
    }
    if (tools) {
      const optional = heads.filter((th) => th.dataset.col && !ALWAYS.has(th.dataset.col));
      const details = document.createElement("details");
      details.className = "grid-cols";
      details.innerHTML = `<summary class="btn sm">${esc(label("lColumns", "Columns"))}</summary><div class="col-menu"></div>`;
      menu = $(".col-menu", details);
      menu.innerHTML = optional.map((th) =>
        `<label class="check"><input type="checkbox" data-col="${esc(th.dataset.col)}"> ${esc(th.textContent.trim())}</label>`).join("") +
        `<button type="button" class="btn sm" data-grid-reset>${esc(label("lReset", "Reset columns"))}</button>`;
      menu.addEventListener("change", (e) => {
        const col = e.target.dataset.col;
        if (!col) return;
        state.show = state.show.filter((c) => c !== col);
        state.hide = state.hide.filter((c) => c !== col);
        (e.target.checked ? state.show : state.hide).push(col);
        save();
        applyColumns();
      });
      $("[data-grid-reset]", menu).addEventListener("click", () => {
        state.w = {}; state.show = []; state.hide = [];
        save(); applyWidths(); applyColumns();
        details.open = false;
      });
      document.addEventListener("click", (e) => { if (!details.contains(e.target)) details.open = false; });
      tools.appendChild(details);
    }

    // Keyboard
    const rows = () => Array.from(body.rows).filter((r) => !r.hidden && !r.classList.contains("err-row"));
    const colOf = (el) => (el.closest("td[data-field]") || {}).dataset ? el.closest("td[data-field]").dataset.field : null;
    function focusRow(row, col) {
      if (!row) return;
      const td = (col && $(`td[data-field="${col}"]`, row)) || $("td[data-field]", row);
      const el = td && ($(".cb-input", td) || $(FIELD, td));
      if (el) el.focus();
    }
    const rowHasContent = (row) => $$('[name$="-item"], [name$="-description"], [name$="-account"]', row).some((el) => el.value);
    const addBtn = $("[data-add-line]", table.closest("[data-formset]") || document);
    table.addEventListener("keydown", (e) => {
      const el = e.target;
      const row = el.closest("tbody tr");
      if (!row) return;
      if (e.key === "Delete" && e.ctrlKey) {
        const del = $("[data-del-line]", row);
        if (!del) return;
        e.preventDefault();
        const list = rows();
        const next = list[list.indexOf(row) + 1] || list[list.indexOf(row) - 1];
        const col = colOf(el);
        del.click();
        focusRow(next, col);
        return;
      }
      if (e.key !== "Enter" || e.shiftKey || el.tagName === "TEXTAREA" || el.tagName === "BUTTON") return;
      e.preventDefault();
      const list = rows();
      const next = list[list.indexOf(row) + 1];
      if (next) { focusRow(next, colOf(el)); return; }
      if (addBtn && rowHasContent(row)) {
        addBtn.click();
        setTimeout(() => { const all = rows(); focusRow(all[all.length - 1], "item"); }, 0);
      }
    });

    new MutationObserver((changes) => {
      changes.forEach((c) => c.addedNodes.forEach((n) => { if (n.nodeType === 1) enhanceRow(n); }));
      applyColumns();
    }).observe(body, { childList: true });
    body.addEventListener("change", () => syncMenu());

    applyWidths();
    applyColumns();
  }

  $$("table.grid").forEach((table) => { enhanceRow(table); setupGrid(table); });
  // Searchable pickers for the party in the document header.
  $$('.doc-entry select[name="supplier"], .doc-entry select[name="customer"]').forEach(enhance);

  // In entry forms Enter moves to the next field instead of submitting half-finished work.
  $$(".doc-entry").forEach((form) => form.addEventListener("keydown", (e) => {
    const el = e.target;
    if (e.key !== "Enter" || e.defaultPrevented || el.tagName === "TEXTAREA" || el.tagName === "BUTTON" || el.type === "submit") return;
    if (el.closest("table.grid")) return;
    e.preventDefault();
    const fields = $$(FIELD.split(", ").map((s) => ".doc-head " + s).join(", ") + ", .doc-head .cb-input", form)
      .filter((f) => f.offsetParent !== null && !f.classList.contains("cb-native"));
    const next = fields[fields.indexOf(el) + 1];
    if (next) next.focus();
  }));
})();
