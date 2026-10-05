(function () {
  "use strict";
  if (!window.Chart) return;
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const rtl = document.documentElement.dir === "rtl";
  const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
  Chart.defaults.font.family = css("--f-body");
  Chart.defaults.color = css("--muted");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const trendEl = document.getElementById("trend-data");
  const cash = document.getElementById("cashChart");
  if (trendEl && cash) {
    const t = JSON.parse(trendEl.textContent);
    const labels = t.labels.map((d) => new Date(d).toLocaleDateString(document.documentElement.lang, { day: "numeric", month: "short" }));
    new Chart(cash, {
      type: "line",
      data: { labels, datasets: [{ data: t.values, borderColor: css("--brand"), backgroundColor: css("--brand-weak"), fill: true, tension: 0.3, borderWidth: 2.5, pointRadius: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: reduce ? false : { duration: 400 },
        plugins: { legend: { display: false }, tooltip: { rtl, callbacks: { label: (c) => " " + c.parsed.y.toLocaleString("en-US", { maximumFractionDigits: 0 }) } } },
        scales: {
          x: { reverse: rtl, grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 14 } },
          y: { position: rtl ? "right" : "left", grid: { color: css("--line") }, border: { display: false }, ticks: { callback: (v) => compact.format(v), maxTicksLimit: 5 } },
        },
      },
    });
  }

  const expEl = document.getElementById("exp-data");
  const exp = document.getElementById("expChart");
  if (expEl && exp) {
    const values = JSON.parse(expEl.textContent);
    new Chart(exp, {
      type: "doughnut",
      data: { datasets: [{ data: values, backgroundColor: values.map((_, i) => css("--c" + (i + 1))), borderColor: css("--surface"), borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "58%", animation: reduce ? false : { duration: 400 }, plugins: { legend: { display: false }, tooltip: { enabled: false } } },
    });
  }
})();
