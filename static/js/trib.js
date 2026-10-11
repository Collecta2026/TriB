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

  // ---------- Menus open on hover (click and keyboard still work, for touch screens) ----------
  const canHover = window.matchMedia("(hover: hover)").matches;
  const csrf = () => ($("[name=csrfmiddlewaretoken]") || {}).value || "";
  const closeHovs = (except) => $$(".hov.open").forEach((h) => { if (h !== except) h.classList.remove("open"); });
  $$(".hov").forEach((h) => {
    let timer;
    const open = () => { clearTimeout(timer); closeHovs(h); $$("[data-popover]").forEach((p) => { p.hidden = true; }); h.classList.add("open"); h.dispatchEvent(new Event("hov:open")); };
    const close = () => { timer = setTimeout(() => h.classList.remove("open"), 220); };
    if (canHover) {
      h.addEventListener("mouseenter", open);
      h.addEventListener("mouseleave", close);
    }
    const trigger = h.firstElementChild;
    trigger.addEventListener("click", (e) => {
      if (trigger.tagName === "A" && canHover) return; // a hover-opened icon link still goes to its page
      e.preventDefault();
      if (h.classList.contains("open")) h.classList.remove("open"); else open();
    });
    h.addEventListener("focusin", open);
    h.addEventListener("focusout", (e) => { if (!h.contains(e.relatedTarget)) close(); });
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".hov")) closeHovs(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeHovs(); });

  // Create (rail): opens on hover like QuickBooks.
  $$("[data-hover-pop]").forEach((btn) => {
    const pop = $(btn.dataset.hoverPop);
    if (!pop || !canHover) return;
    let timer;
    const open = () => { clearTimeout(timer); closeHovs(); pop.hidden = false; };
    const close = () => { timer = setTimeout(() => { pop.hidden = true; }, 260); };
    [btn, pop].forEach((el) => { el.addEventListener("mouseenter", open); el.addEventListener("mouseleave", close); });
  });

  // Bell: load the alerts the first time it opens.
  $$("[data-alerts]").forEach((h) => {
    let loaded = false;
    h.addEventListener("hov:open", () => {
      if (loaded) return;
      loaded = true;
      fetch(h.dataset.alerts, { credentials: "same-origin" }).then((r) => r.text())
        .then((html) => { $("[data-alerts-body]", h).innerHTML = html; }).catch(() => { loaded = false; });
    });
  });

  // Bookmark icon beside each menu item: add or remove it in one click.
  const bmUrl = ($("#navUrls") || { dataset: {} }).dataset.bmUrl;
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-bm]");
    if (!b || !bmUrl) return;
    e.preventDefault();
    const body = new FormData();
    body.append("url", b.dataset.bm);
    body.append("title", b.dataset.title || "");
    fetch(bmUrl, { method: "POST", body, headers: { "X-CSRFToken": csrf() }, credentials: "same-origin" })
      .then((r) => r.json()).then((d) => {
        $$(`[data-bm="${b.dataset.bm}"]`).forEach((x) => { x.classList.toggle("on", d.on); x.setAttribute("aria-pressed", String(d.on)); });
      });
  });

  // "/" jumps to the search box.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.target.closest("input, textarea, select, [contenteditable]")) return;
    const s = $(".search input");
    if (s) { e.preventDefault(); s.focus(); }
  });

  // Reports: period picker, print, search and favourites.
  $$("[data-report-form]").forEach((f) => {
    const sel = $("[data-period]", f);
    if (!sel) return;
    sel.addEventListener("change", () => { if (sel.value !== "custom") f.submit(); });
    $$("[data-custom-date]", f).forEach((d) => d.addEventListener("change", () => { sel.value = "custom"; }));
  });
  $$("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));
  if (location.hash === "#print") setTimeout(() => window.print(), 500);
  const repSearch = $("#repSearch");
  if (repSearch) {
    repSearch.addEventListener("input", () => {
      const q = repSearch.value.trim().toLowerCase();
      let any = false;
      $$(".rep-sec").forEach((sec) => {
        let shown = 0;
        $$(".rep-row", sec).forEach((r) => { const hit = !q || r.dataset.name.includes(q); r.hidden = !hit; shown += hit; });
        sec.hidden = q && !shown;
        if (q && shown) sec.open = true;
        any = any || shown > 0;
      });
      $("#repNone").hidden = any || !q;
    });
  }
  const repLabels = $("#repLabels");
  if (repLabels) {
    const L = repLabels.dataset;
    const favList = $("[data-fav-list]");
    document.addEventListener("click", (e) => {
      const star = e.target.closest("[data-fav]");
      if (!star) return;
      const key = star.dataset.fav;
      const body = new FormData();
      body.append("key", key);
      fetch(L.favUrl, { method: "POST", body, headers: { "X-CSRFToken": csrf() }, credentials: "same-origin" })
        .then((r) => r.json()).then((d) => {
          $$(`[data-fav="${key}"]`).forEach((s) => {
            s.classList.toggle("on", d.on);
            s.setAttribute("aria-pressed", String(d.on));
            s.title = d.on ? L.favOn : L.favOff;
            s.setAttribute("aria-label", s.title);
          });
          const inFav = $(`.rep-row[data-key="${key}"]`, favList);
          if (d.on && !inFav) {
            const src = $$(`.rep-row[data-key="${key}"]`).find((r) => !favList.contains(r));
            if (src) favList.appendChild(src.cloneNode(true));
          } else if (!d.on && inFav) inFav.remove();
          $("[data-fav-empty]").hidden = !!$(".rep-row", favList);
        });
    });
  }

  // Cookies page: forget what this computer remembers.
  const clear = $("[data-clear-local]");
  if (clear) clear.addEventListener("click", () => {
    try { Object.keys(localStorage).filter((k) => k.startsWith("trib.")).forEach((k) => localStorage.removeItem(k)); } catch (err) { /* ignore */ }
    $("[data-clear-msg]").textContent = clear.dataset.done;
  });

  // ---------- Action bar (bottom of every document) ----------
  // "Save and share link / WhatsApp / review to send": remember what to do after saving.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-then]");
    if (!b) return;
    const f = b.form && b.form.querySelector("[data-then-field]");
    if (f) f.value = b.dataset.then;
  });
  // Destructive actions ask first.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-confirm]");
    if (b && !b.matches("[data-revoke]") && !window.confirm(b.dataset.confirm)) e.preventDefault();
  });
  // Share link dialog: creates (or reuses) the private link, copy, WhatsApp, switch off.
  const dlg = $("#shareDlg");
  if (dlg) {
    let shareUrl = "";
    const err = $("[data-share-error]", dlg);
    const open = (url, whatsapp) => {
      shareUrl = url;
      const body = new FormData();
      fetch(url, { method: "POST", body, headers: { "X-CSRFToken": csrf() }, credentials: "same-origin" })
        .then((r) => r.json()).then((d) => {
          err.hidden = !d.error;
          if (d.error) { err.textContent = d.error; } else {
            $("[data-share-link]", dlg).value = d.url;
            $("[data-wa]", dlg).href = d.whatsapp;
            $("[data-wa]", dlg).classList.toggle("primary", !!whatsapp);
          }
          if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
        });
    };
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-share]");
      if (b) { closeHovs(); open(b.dataset.share, b.hasAttribute("data-whatsapp")); }
    });
    $("[data-dlg-close]", dlg).addEventListener("click", () => dlg.close());
    $("[data-copy]", dlg).addEventListener("click", (e) => {
      const input = $("[data-share-link]", dlg);
      input.select();
      (navigator.clipboard ? navigator.clipboard.writeText(input.value) : Promise.resolve(document.execCommand("copy")))
        .then(() => { e.target.textContent = e.target.dataset.done; });
    });
    $("[data-revoke]", dlg).addEventListener("click", (e) => {
      if (!window.confirm(e.target.dataset.confirm)) return;
      const body = new FormData();
      body.append("revoke", "1");
      fetch(shareUrl, { method: "POST", body, headers: { "X-CSRFToken": csrf() }, credentials: "same-origin" }).then(() => dlg.close());
    });
    const q = new URLSearchParams(location.search);
    const shareBtn = $("[data-share]");
    if (shareBtn && (q.get("share") === "1" || q.get("whatsapp") === "1")) open(shareBtn.dataset.share, q.get("whatsapp") === "1");
  }
  const sendLink = $("[data-send-url]");
  if (sendLink && new URLSearchParams(location.search).get("send") === "1") location.replace(sendLink.href);
  if (location.hash === "#pdf") setTimeout(() => window.print(), 500);

  // ---------- Customer / supplier page: tabs, selection, batch actions, columns ----------
  const hub = $("#hubData");
  if (hub) {
    const show = (key) => {
      $$(".tabs [data-tab]").forEach((t) => { const on = t.dataset.tab === key; t.classList.toggle("on", on); t.setAttribute("aria-selected", String(on)); });
      $$(".tabpanel").forEach((p) => { p.hidden = p.dataset.panel !== key; });
    };
    $$(".tabs [data-tab]").forEach((t) => t.addEventListener("click", () => {
      show(t.dataset.tab);
      const u = new URL(location.href);
      u.searchParams.set("tab", t.dataset.tab);
      history.replaceState(null, "", u);
    }));
    show($(`.tabs [data-tab="${hub.dataset.tab}"]`) ? hub.dataset.tab : "transactions");
    const boxes = () => $$("[data-sel]");
    const picked = () => boxes().filter((b) => b.checked);
    const batchBtn = $("[data-batch-btn]");
    const sync = () => { batchBtn.disabled = picked().length === 0; };
    const all = $("[data-select-all]");
    if (all) all.addEventListener("change", () => { boxes().forEach((b) => { b.checked = all.checked; }); sync(); });
    document.addEventListener("change", (e) => { if (e.target.matches("[data-sel]")) sync(); });
    $$("[data-batch]").forEach((b) => b.addEventListener("click", () => {
      const rows = picked();
      if (!rows.length) return;
      if (b.dataset.batch === "print") {
        window.location.href = hub.dataset.batchUrl + "?items=" + encodeURIComponent(rows.map((r) => r.dataset.sel).join(","));
        return;
      }
      const lines = [["Date", "Type", "No.", "Memo", "Amount", "Status"]];
      rows.forEach((r) => {
        const cells = r.closest("tr").querySelectorAll("td");
        lines.push([1, 2, 3, 4, 5, 6].map((i) => cells[i].textContent.trim().replace(/\s+/g, " ")));
      });
      const csv = "﻿" + lines.map((l) => l.map((c) => `"${c.replace(/"/g, '""')}"`).join(",")).join("\r\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      a.download = "transactions.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
    }));
    // Column choices are remembered on this computer.
    let hidden = [];
    try { hidden = JSON.parse(localStorage.getItem("trib.hub.cols") || "[]"); } catch (err) { hidden = []; }
    const applyCols = () => {
      $$("[data-col-toggle]").forEach((c) => {
        c.checked = !hidden.includes(c.dataset.colToggle);
        $$(`#hubList [data-col="${c.dataset.colToggle}"]`).forEach((cell) => { cell.hidden = !c.checked; });
      });
    };
    $$("[data-col-toggle]").forEach((c) => c.addEventListener("change", () => {
      hidden = $$("[data-col-toggle]").filter((x) => !x.checked).map((x) => x.dataset.colToggle);
      try { localStorage.setItem("trib.hub.cols", JSON.stringify(hidden)); } catch (err) { /* ignore */ }
      applyCols();
    }));
    applyCols();
  }

  // Bookmark star: name the bookmark after the page title.
  const bmTitle = $("[data-bookmark-title]");
  if (bmTitle && !bmTitle.value) bmTitle.value = document.title.split(" · ")[0];

  // Privacy: blur amounts on screen (Settings → Privacy can switch it on by default).
  const priv = $("#privBtn");
  if (priv) {
    let on = document.body.dataset.privDefault === "1";
    try { const v = localStorage.getItem("trib.priv"); if (v !== null) on = v === "1"; } catch (err) { /* storage unavailable */ }
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
