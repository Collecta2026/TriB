(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const rtl = document.documentElement.dir === "rtl";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- Charts: every point or slice opens the report behind it ----------
  function charts() {
    if (!window.Chart) return;
    const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
    Chart.defaults.font.family = css("--f-body");
    Chart.defaults.font.size = 11;
    Chart.defaults.color = css("--muted");

    const flowEl = $("#flow-data");
    const cash = $("#cashChart");
    if (flowEl && cash) {
      const f = JSON.parse(flowEl.textContent);
      const labels = f.labels.map((d) => new Date(d + "T00:00:00").toLocaleDateString(document.documentElement.lang, { month: "short", year: "2-digit" }));
      const tick = { callback: (v) => compact.format(v), maxTicksLimit: 5 };
      const sets = {
        balance: [{ type: "line", label: cash.closest(".blk").querySelector("[data-flow=balance]").textContent, data: f.balance, borderColor: css("--brand"),
          backgroundColor: css("--brand-weak"), fill: true, tension: 0.3, borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 6 }],
        inout: [
          { type: "bar", label: "+", data: f.in, backgroundColor: css("--good"), borderRadius: 3, maxBarThickness: 18 },
          { type: "bar", label: "−", data: f.out.map((v) => -v), backgroundColor: css("--sun"), borderRadius: 3, maxBarThickness: 18 },
        ],
      };
      const chart = new Chart(cash, {
        data: { labels, datasets: sets.balance },
        options: {
          responsive: true, maintainAspectRatio: false, animation: reduce ? false : { duration: 300 },
          interaction: { mode: "index", intersect: false },
          onClick: (_e, items) => { if (items.length) window.location.href = f.urls[items[0].index]; },
          onHover: (e, items) => { e.native.target.style.cursor = items.length ? "pointer" : "default"; },
          plugins: { legend: { display: false }, tooltip: { rtl, callbacks: { label: (c) => " " + Math.abs(c.parsed.y).toLocaleString("en-US", { maximumFractionDigits: 0 }) } } },
          scales: {
            x: { reverse: rtl, stacked: true, grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 10 } },
            y: { position: rtl ? "right" : "left", stacked: true, grid: { color: css("--line") }, border: { display: false }, ticks: tick },
          },
        },
      });
      $$("[data-flow]").forEach((b) => b.addEventListener("click", () => {
        $$("[data-flow]").forEach((x) => x.classList.toggle("on", x === b));
        chart.data.datasets = sets[b.dataset.flow];
        chart.update();
      }));
    }

    const fcEl = $("#fc-data");
    const fc = $("#fcChart");
    if (fcEl && fc) {
      const f = JSON.parse(fcEl.textContent);
      const labels = f.labels.map((d) => new Date(d + "T00:00:00").toLocaleDateString(document.documentElement.lang, { day: "numeric", month: "short" }));
      const sets = [{ label: "", data: f.balance, borderColor: css("--brand"), backgroundColor: css("--brand-weak"), fill: true, tension: 0.25, borderWidth: 2.5, pointRadius: 3 }];
      if (f.minimum !== null) sets.push({ label: "min", data: f.balance.map(() => f.minimum), borderColor: css("--crit"), borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, fill: false });
      new Chart(fc, {
        type: "line", data: { labels, datasets: sets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: reduce ? false : { duration: 300 },
          plugins: { legend: { display: false }, tooltip: { rtl, callbacks: { label: (c) => " " + c.parsed.y.toLocaleString("en-US", { maximumFractionDigits: 0 }) } } },
          scales: { x: { reverse: rtl, grid: { display: false } }, y: { position: rtl ? "right" : "left", grid: { color: css("--line") }, border: { display: false }, ticks: { callback: (v) => compact.format(v), maxTicksLimit: 5 } } },
        },
      });
    }

    const expEl = $("#exp-data");
    const exp = $("#expChart");
    if (expEl && exp) {
      const values = JSON.parse(expEl.textContent);
      const urls = JSON.parse(($("#exp-urls") || { textContent: "[]" }).textContent);
      new Chart(exp, {
        type: "doughnut",
        data: { datasets: [{ data: values, backgroundColor: values.map((_, i) => css("--c" + (i + 1))), borderColor: css("--surface"), borderWidth: 2 }] },
        options: {
          responsive: true, maintainAspectRatio: false, cutout: "58%", animation: reduce ? false : { duration: 300 },
          onClick: (_e, items) => { if (items.length && urls[items[0].index]) window.location.href = urls[items[0].index]; },
          onHover: (e, items) => { e.native.target.style.cursor = items.length ? "pointer" : "default"; },
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
        },
      });
    }
  }
  charts();

  // Table rows inside widgets open their detail.
  $$("tr[data-href]").forEach((tr) => {
    tr.addEventListener("click", (e) => { if (!e.target.closest("a, button")) window.location.href = tr.dataset.href; });
  });

  // ---------- App pills: scroll arrows like QuickBooks ----------
  const row = $("#appsRow");
  if (row) {
    const prev = $(".apps-nav.prev"), next = $(".apps-nav.next");
    const dir = rtl ? -1 : 1;
    const sync = () => {
      const max = row.scrollWidth - row.clientWidth;
      const pos = Math.abs(row.scrollLeft);
      prev.hidden = pos < 4;
      next.hidden = pos > max - 4;
    };
    prev.addEventListener("click", () => row.scrollBy({ left: -dir * row.clientWidth * 0.7, behavior: reduce ? "auto" : "smooth" }));
    next.addEventListener("click", () => row.scrollBy({ left: dir * row.clientWidth * 0.7, behavior: reduce ? "auto" : "smooth" }));
    row.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    sync();
  }

  // ---------- Create actions: one line, then "Show all" ----------
  const acts = $("#acts");
  const more = $("[data-acts-more]");
  if (acts && more) {
    const label = more.textContent;
    if (!$(".act.x", acts)) more.hidden = true;
    more.addEventListener("click", () => {
      const open = acts.classList.toggle("all");
      more.textContent = open ? more.dataset.less : label;
      more.setAttribute("aria-expanded", String(open));
    });
  }

  // ---------- Customise dashboard ----------
  const grid = $("#glance");
  const bar = $("#dashBar");
  const help = $("#dashHelp");
  const btn = $("#custBtn");
  const L = ($("#dashLabels") || {}).dataset || {};
  if (!grid || !bar || !btn) return;
  let saved = null;

  const snapshot = () => $$(".blk", grid).map((b) => ({ key: b.dataset.widget, w: parseInt(b.dataset.w, 10) || 1, hidden: b.hidden }));
  const restore = (layout) => {
    layout.forEach((w) => {
      const b = $(`.blk[data-widget="${w.key}"]`, grid);
      if (!b) return;
      grid.appendChild(b);
      b.dataset.w = w.w;
      b.hidden = w.hidden;
    });
    syncPicker();
  };
  const syncPicker = () => $$("[data-wtoggle]").forEach((c) => { c.checked = !$(`.blk[data-widget="${c.dataset.wtoggle}"]`, grid).hidden; });
  const cols = () => getComputedStyle(grid).gridTemplateColumns.split(" ").length;

  function chrome(b) {
    if ($(".w-ctl", b)) return;
    const ctl = document.createElement("div");
    ctl.className = "w-ctl";
    ctl.innerHTML = `<button type="button" class="w-move" aria-label="${L.move || "Move"}" title="${L.move || "Move"}">⠿</button>` +
      `<button type="button" class="w-hide" aria-label="${L.hide || "Hide"}" title="${L.hide || "Hide"}">×</button>`;
    const rz = document.createElement("button");
    rz.type = "button";
    rz.className = "w-rz";
    rz.setAttribute("aria-label", L.resize || "Resize");
    rz.title = L.resize || "Resize";
    b.append(ctl, rz);

    $(".w-hide", ctl).addEventListener("click", () => { b.hidden = true; syncPicker(); });
    // Keyboard: arrows move the widget; with Shift they resize it.
    $(".w-move", ctl).addEventListener("keydown", (e) => {
      const fwd = rtl ? "ArrowLeft" : "ArrowRight", back = rtl ? "ArrowRight" : "ArrowLeft";
      if (e.key === fwd || e.key === "ArrowDown") { const n = b.nextElementSibling; if (n) n.after(b); }
      else if (e.key === back || e.key === "ArrowUp") { const p = b.previousElementSibling; if (p) p.before(b); }
      else return;
      e.preventDefault();
      $(".w-move", b).focus();
    });
    rz.addEventListener("keydown", (e) => {
      const grow = rtl ? "ArrowLeft" : "ArrowRight", shrink = rtl ? "ArrowRight" : "ArrowLeft";
      const w = parseInt(b.dataset.w, 10) || 1;
      if (e.key === grow) b.dataset.w = Math.min(4, w + 1);
      else if (e.key === shrink) b.dataset.w = Math.max(1, w - 1);
      else return;
      e.preventDefault();
    });
    // Drag the corner: snap the width to whole columns.
    rz.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      rz.setPointerCapture(e.pointerId);
      const start = b.getBoundingClientRect();
      const colW = (grid.clientWidth - 14 * (cols() - 1)) / cols();
      const move = (ev) => {
        const width = rtl ? start.right - ev.clientX : ev.clientX - start.left;
        b.dataset.w = Math.max(1, Math.min(4, Math.round(width / (colW + 14))));
      };
      const up = () => { rz.removeEventListener("pointermove", move); rz.removeEventListener("pointerup", up); };
      rz.addEventListener("pointermove", move);
      rz.addEventListener("pointerup", up);
    });
    // Drag the handle: move the widget to where the pointer is.
    const handle = $(".w-move", ctl);
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      b.classList.add("dragging");
      const move = (ev) => {
        const over = document.elementFromPoint(ev.clientX, ev.clientY);
        const target = over && over.closest(".blk");
        if (!target || target === b || target.parentElement !== grid) return;
        const r = target.getBoundingClientRect();
        const after = rtl ? ev.clientX < r.left + r.width / 2 : ev.clientX > r.left + r.width / 2;
        if (after) target.after(b); else target.before(b);
      };
      const up = () => {
        b.classList.remove("dragging");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
  }

  const enter = () => {
    saved = snapshot();
    document.body.classList.add("dash-edit");
    bar.hidden = false;
    help.hidden = false;
    $$(".blk", grid).forEach(chrome);
    bar.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  };
  const leave = () => {
    document.body.classList.remove("dash-edit");
    bar.hidden = true;
    help.hidden = true;
  };
  btn.addEventListener("click", () => (document.body.classList.contains("dash-edit") ? leave() : enter()));
  if (new URLSearchParams(location.search).get("customise") === "1") enter();
  $$("[data-help-close]").forEach((b) => b.addEventListener("click", () => { help.hidden = true; }));
  $$("[data-wtoggle]").forEach((c) => c.addEventListener("change", () => {
    const b = $(`.blk[data-widget="${c.dataset.wtoggle}"]`, grid);
    b.hidden = !c.checked;
    if (c.checked) { chrome(b); b.scrollIntoView({ block: "nearest" }); }
  }));
  $("[data-dash-cancel]", bar).addEventListener("click", () => { restore(saved); leave(); });

  const post = (body) => {
    const token = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";
    return fetch(grid.dataset.saveUrl, { method: "POST", body, headers: { "X-CSRFToken": token }, credentials: "same-origin" })
      .then((r) => { if (!r.ok) throw new Error(); });
  };
  const toast = (text) => {
    const t = document.createElement("div");
    t.className = "toast";
    t.setAttribute("role", "status");
    t.textContent = text;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  };
  $("[data-dash-save]", bar).addEventListener("click", () => {
    const body = new FormData();
    body.append("layout", JSON.stringify(snapshot()));
    post(body).then(() => { leave(); toast(L.saved); }).catch(() => toast(L.failed));
  });
  $("[data-dash-reset]", bar).addEventListener("click", () => {
    const body = new FormData();
    body.append("reset", "1");
    post(body).then(() => window.location.replace(window.location.pathname + "?customise=1")).catch(() => toast(L.failed));
  });
})();
