// reservas/static/reservas/js/bloqueos_page.js
(function(){
  function q(s, r){ return (r||document).querySelector(s); }
  const cfg = q("#bloqueosConfig");
  if (!cfg) return;

  const sucursalId = cfg.dataset.sucursalId;
  const URLS = { create: cfg.dataset.urlCreate, list: cfg.dataset.urlList, del: cfg.dataset.urlDelete };
  const csrf = (q("#csrfToken") && q("#csrfToken").value) || "";

  const filtroScope = q("#filtroScope");
  const filtroMesa  = q("#filtroMesa");
  const filtroDesde = q("#filtroDesde");
  const btnAplicar  = q("#btnAplicarFiltros");
  const btnReset    = q("#btnResetFiltros");
  const tablaBody   = q("#tablaBloqueos tbody");
  const lblVacio    = q("#lblVacio");
  const lblError    = q("#lblError");
  const chkAll      = q("#chkAll");
  const btnDelSel   = q("#btnEliminarSel");

  function setEmpty(show){ if(lblVacio) lblVacio.classList.toggle("d-none", !show); }
  function setErr(show){ if(lblError) lblError.classList.toggle("d-none", !show); }

  async function cargar(){
    setEmpty(false); setErr(false);
    tablaBody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Cargando…</td></tr>`;

    const params = new URLSearchParams({
      sucursal_id: sucursalId,
      desde: (filtroDesde && filtroDesde.value) || new Date().toISOString().slice(0,10),
    });
    const mid = filtroMesa && filtroMesa.value;
    if (mid) params.append("mesa_id", mid);

    try {
      const res = await fetch(`${URLS.list}?${params.toString()}`, { headers: { "X-Requested-With": "fetch" }});
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Error al listar.");

      const items = (data.items || []).filter(b => {
        if (!filtroScope || !filtroScope.value) return true;
        return filtroScope.value === b.scope;
      });

      if (!items.length){
        tablaBody.innerHTML = "";
        setEmpty(true);
        btnDelSel.disabled = true;
        chkAll.checked = false;
        return;
      }

      const rows = items.map((b, i) => {
        const d1 = new Date(b.inicio);
        const d2 = new Date(b.fin);
        return `
          <tr data-id="${b.id}">
            <td><input type="checkbox" class="chkRow"></td>
            <td>${i+1}</td>
            <td>${b.scope}</td>
            <td>${b.mesa_id || "-"}</td>
            <td>${d1.toLocaleString(undefined,{dateStyle:"short", timeStyle:"short"})}</td>
            <td>${d2.toLocaleString(undefined,{dateStyle:"short", timeStyle:"short"})}</td>
            <td>${(b.motivo||"").replace(/</g,"&lt;")}</td>
            <td class="text-end">
              <button class="btn btn-sm btn-outline-danger" data-del="${b.id}">Eliminar</button>
            </td>
          </tr>`;
      }).join("");
      tablaBody.innerHTML = rows;
      btnDelSel.disabled = true;
      chkAll.checked = false;

    } catch(e){
      console.error(e);
      tablaBody.innerHTML = "";
      setErr(true);
    }
  }

  // eventos filtros
  if (btnAplicar) btnAplicar.addEventListener("click", cargar);
  if (btnReset) btnReset.addEventListener("click", () => {
    if (filtroScope) filtroScope.value = "";
    if (filtroMesa)  filtroMesa.value  = "";
    if (filtroDesde) filtroDesde.value = new Date().toISOString().slice(0,10);
    cargar();
  });

  // checkboxes
  if (chkAll) chkAll.addEventListener("change", () => {
    document.querySelectorAll(".chkRow").forEach(cb => cb.checked = chkAll.checked);
    btnDelSel.disabled = !chkAll.checked;
  });
  document.addEventListener("change", (e) => {
    if (!e.target.classList.contains("chkRow")) return;
    const selected = [...document.querySelectorAll(".chkRow")].some(cb => cb.checked);
    btnDelSel.disabled = !selected;
  });

  // eliminar 1
  tablaBody.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-del]");
    if (!btn) return;
    if (!confirm("¿Eliminar este bloqueo?")) return;
    await eliminar([btn.getAttribute("data-del")]);
  });

  // eliminar seleccionados
  if (btnDelSel) btnDelSel.addEventListener("click", async () => {
    const ids = [...document.querySelectorAll("tr[data-id] .chkRow:checked")].map(cb => cb.closest("tr").dataset.id);
    if (!ids.length) return;
    if (!confirm(`¿Eliminar ${ids.length} bloqueo(s)?`)) return;
    await eliminar(ids);
  });

  async function eliminar(ids){
    try{
      for (const id of ids){
        const res = await fetch(URLS.del, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
            "X-Requested-With": "fetch",
          },
          credentials: "same-origin",
          body: JSON.stringify({ id: Number(id) })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Error al eliminar.");
      }
      cargar();
    } catch(e){
      alert(String(e.message || e));
    }
  }

  // carga inicial
  cargar();
})();
