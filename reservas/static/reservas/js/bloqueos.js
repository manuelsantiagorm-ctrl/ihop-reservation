// reservas/static/reservas/js/bloqueos.js
(function () {
  // --- helpers ---
  function q(sel, root)  { return (root || document).querySelector(sel); }
  function qa(sel, root) { return (root || document).querySelectorAll(sel); }
  function getCookie(name){
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(";").shift());
  }
  function toISO(dtLocalValue){
    if (!dtLocalValue) return null;
    // datetime-local -> ISO (UTC). Backend hará aware si viene naive.
    return new Date(dtLocalValue).toISOString();
  }

  // --- config desde el DOM ---
  const cfg = q("#bloqueosConfig");
  if (!cfg) return; // página sin bloqueos

  const sucursalId = cfg.dataset.sucursalId;
  const URLS = {
    create: cfg.dataset.urlCreate,
    list:   cfg.dataset.urlList,
    del:    cfg.dataset.urlDelete,
  };

  // CSRF preferente desde <input id="csrfToken">, luego cookie
  const hiddenCsrf = q("#csrfToken");
  const csrfToken  = (hiddenCsrf && hiddenCsrf.value) || getCookie("csrftoken") || "";

  // --- Modal CREAR ---
  const modalCrear   = q("#modalBloqueo");
  const formCrear    = q("#formBloqueo");
  const scopeSel     = q('[data-scope]', formCrear);
  const mesaWrap     = q('[data-mesa-wrap]', formCrear);
  const mesaSel      = q('[data-mesa-id]', formCrear);
  const inicioInp    = q('input[name="inicio"]', formCrear);
  const finInp       = q('input[name="fin"]', formCrear);
  const motivoInp    = q('input[name="motivo"]', formCrear);
  const alertErr     = q('[data-error]', formCrear);
  const alertOk      = q('[data-success]', formCrear);
  const btnCrear     = q('[data-action="crear-bloqueo"]', modalCrear);

  function showMesaWrap(show){
    if (mesaWrap) mesaWrap.style.display = show ? "" : "none";
  }

  if (scopeSel) {
    scopeSel.addEventListener("change", () => {
      showMesaWrap(scopeSel.value === "mesa");
    });
  }

  // Abrir modales con presets
  document.addEventListener("click", (e) => {
    const btnMesa  = e.target.closest("[data-bloquear-mesa]");
    const btnSuc   = e.target.closest("[data-bloqueo-sucursal]");
    const btnLista = e.target.closest("[data-ver-bloqueos]");

    // Bloquear una mesa específica
    if (btnMesa && modalCrear && scopeSel) {
      const mesaId = btnMesa.getAttribute("data-mesa-id");
      scopeSel.value = "mesa";
      showMesaWrap(true);
      if (mesaSel && mesaId) mesaSel.value = String(mesaId);
      if (alertErr) { alertErr.classList.add("d-none"); alertErr.textContent = ""; }
      if (alertOk)  { alertOk.classList.add("d-none"); }

      // 👇 abrir modal de bloqueo
      const modal = bootstrap.Modal.getOrCreateInstance(modalCrear);
      modal.show();
    }

    // Bloquear toda la sucursal
    if (btnSuc && modalCrear && scopeSel) {
      scopeSel.value = "sucursal";
      showMesaWrap(false);
      if (alertErr) { alertErr.classList.add("d-none"); alertErr.textContent = ""; }
      if (alertOk)  { alertOk.classList.add("d-none"); }

      const modal = bootstrap.Modal.getOrCreateInstance(modalCrear);
      modal.show();
    }

    // Ver lista de bloqueos (sucursal)
    if (btnLista && modalLista) {
      const modal = bootstrap.Modal.getOrCreateInstance(modalLista);
      modal.show();
    }
  });

  async function crearBloqueo(){
    if (!formCrear || !btnCrear) return;

    // UI: reset + loading
    if (alertErr) { alertErr.classList.add("d-none"); alertErr.textContent = ""; }
    if (alertOk)  { alertOk.classList.add("d-none"); }
    const originalHTML = btnCrear.innerHTML;
    btnCrear.disabled = true;
    btnCrear.innerHTML = "Enviando…";

    try {
      const scope = scopeSel ? scopeSel.value : "sucursal";
      const inicioISO = toISO(inicioInp && inicioInp.value);
      const finISO    = toISO(finInp && finInp.value);

      if (!inicioISO || !finISO) throw new Error("Indica inicio y fin.");
      if (new Date(finISO) <= new Date(inicioISO)) throw new Error("El fin debe ser mayor al inicio.");

      const payload = {
        sucursal_id: Number(sucursalId),
        inicio: inicioISO,
        fin: finISO,
        motivo: (motivoInp && motivoInp.value || "").trim(),
      };
      if (scope === "mesa") {
        const mid = mesaSel && mesaSel.value;
        if (!mid) throw new Error("Selecciona la mesa.");
        payload.mesa_id = Number(mid);
      }

      const res = await fetch(URLS.create, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status} ${res.statusText}\n${txt.slice(0,300)}`);
      }

      let data;
      try { data = await res.json(); }
      catch(e){
        const txt = await res.text();
        throw new Error("La respuesta no es JSON:\n" + txt.slice(0,300));
      }

      if (!data.ok) throw new Error(data.error || "No se pudo crear el bloqueo.");

      // Éxito: feedback fuerte + cerrar modal
      if (alertOk) alertOk.classList.remove("d-none");
      if (motivoInp) motivoInp.value = "";
      btnCrear.innerHTML = "✅ Creado";

      // refrescar lista si está abierta
      fetchBloqueos && fetchBloqueos();

      setTimeout(() => {
        try {
          const modal = bootstrap.Modal.getInstance(modalCrear) || new bootstrap.Modal(modalCrear);
          modal.hide();
        } catch(_) {}
        btnCrear.disabled = false;
        btnCrear.innerHTML = originalHTML;
      }, 700);

    } catch (err) {
      if (alertErr){
        alertErr.textContent = String(err.message || err);
        alertErr.classList.remove("d-none");
      }
      console.error(err);
      btnCrear.disabled = false;
      btnCrear.innerHTML = originalHTML;
    }
  }

  if (btnCrear) btnCrear.addEventListener("click", crearBloqueo);

  // --- Modal LISTA ---
  const modalLista = q("#modalBloqueosLista");
  const filtroMesa = q('[data-filtro-mesa]', modalLista);
  const tableBody  = q('[data-tabla-bloqueos] tbody', modalLista);
  const alertEmpty = q('[data-empty]', modalLista);
  const alertListErr = q('[data-error-list]', modalLista);

  function renderRows(items){
    if (!tableBody) return;
    tableBody.innerHTML = "";
    if (!items.length){
      if (alertEmpty) alertEmpty.classList.remove("d-none");
      return;
    }
    if (alertEmpty) alertEmpty.classList.add("d-none");
    items.forEach((b, idx) => {
      const tr = document.createElement("tr");
      const d1 = new Date(b.inicio);
      const d2 = new Date(b.fin);
      tr.innerHTML = `
        <td>${idx+1}</td>
        <td>${b.scope}</td>
        <td>${b.mesa_id || "-"}</td>
        <td>${d1.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}</td>
        <td>${d2.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}</td>
        <td>${(b.motivo || "").replace(/</g,"&lt;")}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-danger" data-del="${b.id}">Eliminar</button>
        </td>
      `;
      tableBody.appendChild(tr);
    });
  }

  async function fetchBloqueos(){
    if (!modalLista) return;
    try {
      const params = new URLSearchParams({
        sucursal_id: sucursalId,
        desde: new Date().toISOString().slice(0,10)
      });
      const mid = filtroMesa && filtroMesa.value;
      if (mid) params.append("mesa_id", mid);
      const res = await fetch(`${URLS.list}?${params.toString()}`, {
        headers: { "X-Requested-With": "fetch" }
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Error al listar bloqueos.");
      renderRows(data.items || []);
    } catch (err) {
      if (alertListErr) alertListErr.classList.remove("d-none");
    }
  }

  if (modalLista) {
    modalLista.addEventListener("shown.bs.modal", fetchBloqueos);
    if (filtroMesa) filtroMesa.addEventListener("change", fetchBloqueos);

    // eliminar
    modalLista.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-del]");
      if (!btn) return;
      const id = btn.getAttribute("data-del");
      if (!confirm("¿Eliminar este bloqueo?")) return;
      try {
        const res = await fetch(URLS.del, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
            "X-Requested-With": "fetch",
          },
          body: JSON.stringify({ id: Number(id) })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "No se pudo eliminar.");
        fetchBloqueos();
      } catch (err) {
        alert(String(err.message || err));
      }
    });
  }
})();
