(function () {
  // ----- helpers -----
  function todayISO() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function normYYYYMMDD(s) {
    if (/^\d{2}\/\d{2}\/\d{4}$/.test(s)) {
      const [dd, mm, yyyy] = s.split("/");
      return `${yyyy}-${mm}-${dd}`;
    }
    return s;
  }
  function hhmm(str) {
    const m = String(str || "").match(/^(\d{2}):(\d{2})/);
    return m ? `${m[1]}:${m[2]}` : "";
  }
  function setDateTimeLocal(inputEl, day, timeHHMM) {
    if (!inputEl) return;
    const t = hhmm(timeHHMM);
    if (!day || !t) return;
    inputEl.value = `${day}T${t}`;
  }

  function readConfig() {
    const el = document.getElementById("walkin-config");
    try {
      return JSON.parse(el?.textContent || "{}");
    } catch {
      return {};
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const cfg = readConfig();
    const I18N = cfg.i18n || {};
    const URLS = cfg.urls || {};

    // refs
    const sucField = document.querySelector('select[name="sucursal"]') || document.querySelector('input[name="sucursal"]');
    const mesaField = document.querySelector('select[name="mesa"]');
    const fechaField = document.querySelector('input[name="fecha"]');
    const persField = document.querySelector('input[name="num_personas"]');

    const fFecha = document.getElementById("dispFecha");
    const fDesde = document.getElementById("dispDesde");
    const fPers = document.getElementById("dispPersonas");
    const btnBuscar = document.getElementById("btnBuscarDisp");
    const contRes = document.getElementById("dispResultados");

    if (!btnBuscar || !fFecha || !contRes) return;

    fFecha.value = todayISO();
    if (fDesde && !fDesde.hasAttribute("step")) fDesde.setAttribute("step", "60");

    btnBuscar.addEventListener("click", async () => {
      const fecha = normYYYYMMDD(fFecha.value);
      const desde = hhmm(fDesde ? fDesde.value : "");
      const party = Math.max(1, parseInt(fPers ? fPers.value : (persField ? persField.value : 1), 10) || 1);

      const sucId = sucField && (sucField.value || sucField.getAttribute("value"));
      if (!sucId) {
        contRes.innerHTML = `<div class="col-12"><div class="alert alert-warning">Selecciona una sucursal.</div></div>`;
        return;
      }

      let base = URLS.api_slots_base || "/api/sucursal/0/slots/";
      base = base.replace("/0/", `/${sucId}/`);
      const url = `${base}?fecha=${encodeURIComponent(fecha)}&party=${encodeURIComponent(party)}&limit=500`;

      if (mesaField) while (mesaField.options.length) mesaField.remove(0);

      contRes.innerHTML =
        `<div class="col-12"><div class="alert alert-info d-flex align-items-center gap-2">
          <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
          <span>${I18N.searching || "Buscando…"}</span>
        </div></div>`;

      try {
        const r = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json();
        renderResultados(data, { desde, I18N });
      } catch (e) {
        contRes.innerHTML = `<div class="col-12"><div class="alert alert-danger">${I18N.error || "Error consultando disponibilidad."}</div></div>`;
      }
    });

    function renderResultados(data, opts) {
      const desde = opts.desde || "";
      const I18N = opts.I18N || {};
      contRes.innerHTML = "";

      // ----- formato por mesas -----
      if (Array.isArray(data.mesas)) {
        const mesas = data.mesas.map((m) => ({
          ...m,
          slots: (m.slots || []).map(hhmm).filter((t) => t && (!desde || t >= desde)),
        }));
        const total = mesas.reduce((a, m) => a + m.slots.length, 0);
        if (!total) {
          contRes.insertAdjacentHTML("beforeend", `<div class="col-12"><div class="alert alert-warning">${I18N.no_slots || "No hay mesas con horarios disponibles."}</div></div>`);
          return;
        }

        if (mesaField) {
          mesas.forEach((m) => {
            if (m.slots.length)
              mesaField.add(new Option(`Mesa ${m.numero}${m.capacidad ? ` (${I18N.cap || "Cap."} ${m.capacidad})` : ""}`, m.id));
          });
        }

        mesas.forEach((m) => {
          if (!m.slots.length) return;
          const col = document.createElement("div");
          col.className = "col-12";
          col.innerHTML = `
            <div class="card card-soft">
              <div class="card-body">
                <div class="d-flex justify-content-between align-items-center mb-2">
                  <h6 class="mb-0">Mesa ${m.numero}</h6>
                  ${m.capacidad ? `<span class="badge text-bg-light">${I18N.cap || "Cap."} ${m.capacidad}</span>` : ""}
                </div>
                <div class="slot-grid" data-mesa="${m.id}">
                  ${m.slots.map((t) => `<button type="button" class="btn btn-sm btn-outline-primary slot-btn" data-hora="${t}">${t}</button>`).join("")}
                </div>
              </div>
            </div>`;
          contRes.appendChild(col);
        });

        wireSlotClicks();
        return;
      }

      // ----- formato plano (slots) -----
      if (Array.isArray(data.slots)) {
        const slots = data.slots
          .map((s) => ({ label: s.label || hhmm(s.value), value: hhmm(s.value) }))
          .filter((s) => s.value && (!desde || s.value >= desde));

        if (!slots.length) {
          contRes.insertAdjacentHTML("beforeend", `<div class="col-12"><div class="alert alert-warning">${I18N.no_slots || "No hay mesas con horarios disponibles."}</div></div>`);
          return;
        }

        if (mesaField && mesaField.options.length === 1) mesaField.selectedIndex = 0;

        const col = document.createElement("div");
        col.className = "col-12";
        col.innerHTML = `
          <div class="card card-soft">
            <div class="card-body">
              <h6 class="mb-3">${I18N.list_title || "Horarios disponibles"}</h6>
              <div class="slot-grid" data-mesa="">
                ${slots.map((s) => `<button type="button" class="btn btn-sm btn-outline-primary slot-btn" data-hora="${s.value}">${s.label || s.value}</button>`).join("")}
              </div>
              ${!mesaField ? `<div class="mt-2 text-muted small">${I18N.select_table_hint || "Seleccione la mesa en el formulario antes de guardar."}</div>` : ""}
            </div>
          </div>`;
        contRes.appendChild(col);

        wireSlotClicks();
        return;
      }

      // sin datos
      contRes.insertAdjacentHTML("beforeend", `<div class="col-12"><div class="alert alert-warning">El servidor no devolvió datos de disponibilidad.</div></div>`);
    }

    function wireSlotClicks() {
      contRes.querySelectorAll(".slot-btn").forEach((btn) => {
        btn.addEventListener("click", (ev) => {
          const hora = ev.currentTarget.dataset.hora;
          const mesaContainer = ev.currentTarget.closest("[data-mesa]");
          const mesaId = mesaContainer ? mesaContainer.dataset.mesa || "" : "";
          const day = fFecha.value || todayISO();

          if (mesaField && mesaId) mesaField.value = mesaId; // si vino por mesa
          setDateTimeLocal(fechaField, day, hora);
          if (persField) persField.value = Math.max(1, parseInt((document.getElementById("dispPersonas")?.value) || persField.value || 1, 10) || 1);

          contRes.querySelectorAll(".slot-btn.active").forEach((b) => b.classList.remove("active"));
          ev.currentTarget.classList.add("active");
        });
      });
    }
  });
})();
