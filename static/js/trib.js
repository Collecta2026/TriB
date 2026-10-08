(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // Popovers: [data-toggle="#id"] opens/closes the element; clicking elsewhere closes it.
  document.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-toggle]");
    $$("[data-popover]").forEach((pop) => {
      if (toggle && toggle.dataset.toggle === "#" + pop.id) return;
      if (!pop.contains(e.target)) pop.hidden = true;
    });
    if (toggle) {
      const pop = $(toggle.dataset.toggle);
      if (pop) { pop.hidden = !pop.hidden; e.preventDefault(); }
    }
    if (e.target.closest("#hambBtn")) { $("#app").classList.add("navopen"); $("#scrim").hidden = false; }
    if (e.target.closest("#scrim")) { $("#app").classList.remove("navopen"); $("#scrim").hidden = true; }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $$("[data-popover]").forEach((p) => { p.hidden = true; });
  });

  // Rail submenus: open level with their item, but never below the bottom of the window.
  $$(".rail .ri-wrap").forEach((wrap) => {
    const fly = $(".fly", wrap);
    if (!fly) return;
    const place = () => {
      const top = wrap.getBoundingClientRect().top;
      fly.style.top = "0px";
      fly.style.display = "block";
      const height = fly.offsetHeight;
      fly.style.display = "";
      fly.style.top = Math.max(8, Math.min(top, window.innerHeight - height - 8)) + "px";
    };
    wrap.addEventListener("mouseenter", place);
    wrap.addEventListener("focusin", place);
  });

  // Bookmark star: name the bookmark after the page title.
  const bmTitle = $("[data-bookmark-title]");
  if (bmTitle && !bmTitle.value) bmTitle.value = document.title.split(" · ")[0];

  // Privacy: blur amounts on screen.
  const priv = $("#privBtn");
  if (priv) {
    let on = false;
    try { on = localStorage.getItem("trib.priv") === "1"; } catch (err) { /* storage unavailable */ }
    const apply = () => { document.body.classList.toggle("priv", on); priv.setAttribute("aria-pressed", String(on)); };
    apply();
    priv.addEventListener("click", () => {
      on = !on; apply();
      try { localStorage.setItem("trib.priv", on ? "1" : "0"); } catch (err) { /* ignore */ }
    });
  }

  // Line formsets: add/remove rows and keep totals live.
  $$("[data-formset]").forEach((wrap) => {
    const prefix = wrap.dataset.formset;
    const total = $(`#id_${prefix}-TOTAL_FORMS`);
    const body = $("tbody", wrap);
    const tpl = $("template", wrap);
    const fmt = (n) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const sum = (name) => $$(`input[name$="-${name}"]`, body)
      .filter((i) => !i.closest("tr").hidden)
      .reduce((a, i) => a + (parseFloat(i.value) || 0), 0);
    const recalc = () => {
      ["amount", "debit", "credit"].forEach((name) => {
        const out = $(`[data-total="${name}"]`, wrap);
        if (out) out.textContent = fmt(sum(name));
      });
      const diff = $("[data-total=diff]", wrap);
      if (diff) {
        const d = Math.round((sum("debit") - sum("credit")) * 100) / 100;
        diff.textContent = fmt(Math.abs(d));
        diff.closest("[data-diff-row]").hidden = d === 0;
      }
    };
    $("[data-add-line]", wrap).addEventListener("click", () => {
      const index = parseInt(total.value, 10);
      body.insertAdjacentHTML("beforeend", tpl.innerHTML.replace(/__prefix__/g, index));
      total.value = index + 1;
    });
    wrap.addEventListener("click", (e) => {
      const del = e.target.closest("[data-del-line]");
      if (!del) return;
      const row = del.closest("tr");
      const box = $('input[name$="-DELETE"]', row);
      if (box) { box.checked = true; row.hidden = true; } else { row.remove(); }
      recalc();
    });
    wrap.addEventListener("input", recalc);
    recalc();
  });

  // Payment method: show only the fields that apply.
  const method = $("#id_method");
  if (method) {
    const sync = () => {
      $$("[data-method]").forEach((el) => {
        el.hidden = !el.dataset.method.split(" ").includes(method.value);
      });
    };
    method.addEventListener("change", sync);
    sync();
  }
})();
