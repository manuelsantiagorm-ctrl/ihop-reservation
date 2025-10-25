// static/reservas/js/analytics.js
(function () {
  const $ = (s) => document.querySelector(s);
  const API = "/chainadmin/analytics/data/";

  // Paleta sobria (Bootstrap-ish)
  const colors = {
    primary: "rgba(13,110,253,0.9)",
    primaryFillTop: "rgba(13,110,253,0.25)",
    primaryFillBottom: "rgba(13,110,253,0.0)",
    grayGrid: "rgba(0,0,0,0.05)",
  };

  // Helpers fecha
  function todayISO() { return new Date().toISOString().slice(0, 10); }
  function addDays(date, n) { const d = new Date(date); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
  function firstDayOfMonth(dateISO) { const d = new Date(dateISO || todayISO()); d.setDate(1); return d.toISOString().slice(0, 10); }
  function firstDayOfYear(dateISO) { const d = new Date(dateISO || todayISO()); d.setMonth(0, 1); return d.toISOString().slice(0, 10); }

  // Charts
  let chartSeries, chartHours, chartParty, chartBranches;

  function lineGradient(ctx) {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
    g.addColorStop(0, colors.primaryFillTop);
    g.addColorStop(1, colors.primaryFillBottom);
    return g;
  }

  function buildLineChart(id, labels, values) {
    const el = $(id); if (!el) return;
    const ctx = el.getContext("2d");
    chartSeries && chartSeries.destroy();
    chartSeries = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "Reservas",
          data: values,
          borderColor: colors.primary,
          backgroundColor: lineGradient(ctx),
          borderWidth: 2,
          tension: 0.35,
          pointRadius: 0,
          fill: true
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
          y: { beginAtZero: true, grid: { color: colors.grayGrid }, ticks: { precision: 0 } }
        }
      }
    });
  }

  function buildBarHours(id, hours) {
    const el = $(id); if (!el) return;
    const labels = Array.from({ length: 24 }, (_, i) => i.toString().padStart(2, "0") + ":00");
    const ctx = el.getContext("2d");
    chartHours && chartHours.destroy();
    chartHours = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ data: hours, backgroundColor: colors.primary }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, grid: { color: colors.grayGrid }, ticks: { precision: 0 } }
        }
      }
    });
  }

  function buildDoughnutParty(id, bins) {
    const el = $(id); if (!el) return;
    const labels = Object.keys(bins || {"1":0,"2":0,"3":0,"4":0,"5+":0});
    const data = labels.map(k => (bins?.[k] ?? 0));
    const ctx = el.getContext("2d");
    chartParty && chartParty.destroy();
    chartParty = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data,
          backgroundColor: [
            "rgba(13,110,253,0.9)",
            "rgba(25,135,84,0.9)",
            "rgba(255,193,7,0.9)",
            "rgba(220,53,69,0.9)",
            "rgba(111,66,193,0.9)"
          ]
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
        cutout: "60%"
      }
    });
  }

  function buildBarBranches(id, top) {
    const el = $(id); if (!el) return;
    const labels = (top || []).map(x => x.name);
    const data = (top || []).map(x => x.count);
    const ctx = el.getContext("2d");
    chartBranches && chartBranches.destroy();
    chartBranches = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ data, backgroundColor: colors.primary }] },
      options: {
        indexAxis: "y",
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, grid: { color: colors.grayGrid }, ticks: { precision: 0 } },
          y: { grid: { display: false } }
        }
      }
    });
  }

  async function fetchData() {
    const params = new URLSearchParams();
    params.set("pais", $("#pais").value);
    params.set("from", $("#from").value || todayISO());
    params.set("to", $("#to").value || todayISO());
    params.set("g", $("#granularity").value);
    const res = await fetch(API + "?" + params.toString(), { credentials: "same-origin" });
    if (!res.ok) throw new Error("Error cargando datos");
    return res.json();
  }

  function updateKPIs(kpis) {
    $("#kpi-reservas").textContent = (kpis && kpis.total_reservas != null) ? kpis.total_reservas.toLocaleString() : "—";
    $("#kpi-suc").textContent = (kpis && kpis.sucursales != null) ? kpis.sucursales.toLocaleString() : "—";
    $("#kpi-badmins").textContent = (kpis && kpis.branch_admins != null) ? kpis.branch_admins.toLocaleString() : "—";
  }

  async function apply() {
    try {
      const data = await fetchData();
      updateKPIs(data.kpis || {});
      const ts = data.time_series || { labels: [], values: [] };
      buildLineChart("#chart-series", ts.labels || [], ts.values || []);
      buildBarHours("#chart-hours", data.peak_hours || Array(24).fill(0));
      buildDoughnutParty("#chart-party", data.party_size || { "1": 0, "2": 0, "3": 0, "4": 0, "5+": 0 });
      buildBarBranches("#chart-branches", data.top_branches || []);
    } catch (e) {
      console.error(e);
      updateKPIs({});
      buildLineChart("#chart-series", [], []);
      buildBarHours("#chart-hours", Array(24).fill(0));
      buildDoughnutParty("#chart-party", { "1": 0, "2": 0, "3": 0, "4": 0, "5+": 0 });
      buildBarBranches("#chart-branches", []);
    }
  }

  // Presets
  function applyPreset(code) {
    const today = todayISO();
    if (code === "today") {
      $("#from").value = today; $("#to").value = today; $("#granularity").value = "day";
    } else if (code === "7d") {
      $("#from").value = addDays(today, -6); $("#to").value = today; $("#granularity").value = "day";
    } else if (code === "30d") {
      $("#from").value = addDays(today, -29); $("#to").value = today; $("#granularity").value = "day";
    } else if (code === "mtd") {
      $("#from").value = firstDayOfMonth(today); $("#to").value = today; $("#granularity").value = "day";
    } else if (code === "ytd") {
      $("#from").value = firstDayOfYear(today); $("#to").value = today; $("#granularity").value = "month";
    }
    apply();
  }

  // Eventos
  $("#apply")?.addEventListener("click", apply);
  document.querySelectorAll('[data-preset]').forEach(b => {
    b.addEventListener("click", () => applyPreset(b.dataset.preset));
  });

  // Primer render: respeta defaults del servidor.
  (function firstRender() {
    const hasServerDefaults = $("#from").value && $("#to").value;
    if (hasServerDefaults) {
      apply();
    } else {
      $("#to").value = todayISO();
      applyPreset("today");
    }
  })();

  // Exponer para que el comparador pueda engancharse al botón "Aplicar"
  window.__analytics_apply__ = apply;
})();


// ====== COMPARADOR DE SUCURSALES (multi-select "ID — Nombre") ======
(function () {
  const $ = (s) => document.querySelector(s);
  const API_COMPARE   = "/chainadmin/analytics/compare/";
  const API_BRANCHES  = "/chainadmin/analytics/sucursales/"; // debe devolver [{id, nombre, slug}...]

  // Helpers de formato
  const num = (x) => (x ?? 0).toLocaleString();
  const pct = (x) => `${(x ?? 0).toFixed(1)}%`;

  // Cargar sucursales del país seleccionado y poblar <select multiple>
  async function loadBranchesForCountry() {
    const countryId = $("#pais")?.value;
    const sel = $("#cmp-branches");
    if (!countryId || !sel) return;

    sel.innerHTML = '<option disabled>Cargando…</option>';
    try {
      const res = await fetch(`${API_BRANCHES}?pais=${countryId}`, { credentials: "same-origin" });
      if (!res.ok) throw new Error("No se pudieron cargar sucursales");
      const data = await res.json(); // se espera { branches: [{id, nombre, slug}] }
      const branches = data.branches || data || [];
      sel.innerHTML = "";
      branches.forEach(b => {
        const opt = document.createElement("option");
        opt.value = String(b.id);
        opt.textContent = `${b.id} — ${b.nombre || b.slug || "Sucursal"}`;
        sel.appendChild(opt);
      });
    } catch (e) {
      console.error(e);
      sel.innerHTML = '<option disabled>Error cargando sucursales</option>';
    }
  }

  // Recolectar parámetros del comparador
  function gatherCompareParams() {
    const params = new URLSearchParams();
    params.set("pais", $("#pais").value);
    params.set("from", $("#from").value);
    params.set("to", $("#to").value);

    // sucursales seleccionadas (multi-select)
    const sel = $("#cmp-branches");
    if (sel && sel.selectedOptions.length > 0) {
      const ids = Array.from(sel.selectedOptions).map(o => o.value).join(",");
      params.set("sucursales", ids);
    }

    const hFrom = $("#cmp-hour-from")?.value;
    const hTo   = $("#cmp-hour-to")?.value;
    if (hFrom) params.set("h_from", hFrom);
    if (hTo)   params.set("h_to", hTo);

    const cMin = $("#cmp-cap-min")?.value;
    const cMax = $("#cmp-cap-max")?.value;
    if (cMin) params.set("cap_min", cMin);
    if (cMax) params.set("cap_max", cMax);

    // estados (checkboxes individuales)
    const est = [];
    if ($("#cmp-st-conf")?.checked) est.push("CONF");
    if ($("#cmp-st-pend")?.checked) est.push("PEND");
    if ($("#cmp-st-canc")?.checked) est.push("CANC");
    if ($("#cmp-st-nosh")?.checked) est.push("NOSH");
    if (est.length) params.set("estados", est.join(","));

    return params;
  }

  async function fetchCompare() {
    const params = gatherCompareParams();
    const res = await fetch(API_COMPARE + "?" + params.toString(), { credentials: "same-origin" });
    if (!res.ok) throw new Error("Error comparando sucursales");
    return res.json(); // { rows: [...] }
  }

  function renderCompare(rows) {
    const tbody = $("#cmp-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    (rows || []).forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="text-truncate" title="${r.sucursal}">${r.sucursal}</td>
        <td class="text-end fw-semibold">${num(r.total)}</td>
        <td class="text-end">${num(r.conf)} <small class="text-muted">(${pct(r.conf_pct)})</small></td>
        <td class="text-end">${num(r.canc)} <small class="text-muted">(${pct(r.canc_pct)})</small></td>
        <td class="text-end">${num(r.nosh)} <small class="text-muted">(${pct(r.nosh_pct)})</small></td>
        <td class="text-end">${num(r.pend)}</td>
        <td class="text-end">${(r.avg_pax ?? 0).toFixed(1)}</td>
        <td class="text-end">${num(r.mesas)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  async function applyCompare() {
    const loader = $("#cmp-loader");
    loader?.classList.remove("d-none");
    try {
      const { rows } = await fetchCompare();
      renderCompare(rows || []);
    } catch (e) {
      console.error(e);
      renderCompare([]);
    } finally {
      loader?.classList.add("d-none");
    }
  }

  // Eventos
  $("#cmp-run")?.addEventListener("click", applyCompare);
  $("#pais")?.addEventListener("change", async () => {
    await loadBranchesForCountry();
    applyCompare();
  });

  // Cuando se aplique el dashboard arriba, re-ejecuta comparador
  $("#apply")?.addEventListener("click", () => setTimeout(applyCompare, 100));

  // Primer render si existe el bloque
  (async function firstCompareRender() {
    if (!document.querySelector("#cmp-card")) return;
    // Defaults
    $("#cmp-hour-from") && ($("#cmp-hour-from").value = "8");
    $("#cmp-hour-to") && ($("#cmp-hour-to").value = "22");
    // estados: por defecto marcamos CONF y PEND (como en el HTML), aquí no forzamos cambios
    await loadBranchesForCountry();
    applyCompare();
  })();

  // Exponer por si se requiere enganchar desde otros scripts
  window.__analytics_compare__ = applyCompare;
})();
