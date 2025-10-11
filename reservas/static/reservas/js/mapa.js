/* global document, window */

/**
 * Mapa de mesas (drag + popover de acciones)
 * - Bloqueo/desbloqueo del diseño (candado)
 * - Arrastrar mesas y recepción (guarda posición vía AJAX)
 * - Filtro por zona (interior/terraza/exterior)
 * - Popover de acciones: aparece al doble clic sobre la mesa
 */
(function () {
  const canvas = document.getElementById("mapCanvas");
  if (!canvas) return;

  // ============================================================
  //  Helpers generales
  // ============================================================
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(";").shift());
  }
  const csrftoken = getCookie("csrftoken");

  /** POST JSON cómodo con CSRF y manejo básico de errores */
  async function postJSON(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "fetch",
        "X-CSRFToken": csrftoken || "",
      },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${txt}`);
    }
    return res.json().catch(() => ({}));
  }

  // ============================================================
  //  Candado de diseño (editable ON/OFF) guardado en localStorage
  // ============================================================
  const lockBtn = document.getElementById("btnDesignLock");
  const sucursalId = lockBtn?.dataset.sucursalId || "0";
  const LS_KEY = `map_lock_${sucursalId}`;

  function setEditable(on) {
    canvas.setAttribute("data-editable", on ? "1" : "0");
    if (lockBtn) {
      lockBtn.innerHTML = on
        ? `<i class="bi bi-unlock"></i> <span data-lock-text>Diseño editable</span>`
        : `<i class="bi bi-lock"></i> <span data-lock-text>Diseño bloqueado</span>`;
    }
    localStorage.setItem(LS_KEY, on ? "1" : "0");
  }
  setEditable(localStorage.getItem(LS_KEY) !== "0"); // editable por defecto
  lockBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    const editable = canvas.getAttribute("data-editable") === "1";
    setEditable(!editable);
  });

  // ============================================================
  //  Popover de acciones por mesa (doble clic)
  //  - Cierra con click-fuera, tecla ESC o al iniciar drag
  // ============================================================
  let activeNode = null;

  function closePopover() {
    if (activeNode) {
      activeNode.classList.remove("active");
      activeNode = null;
    }
  }

  function togglePopoverFor(node) {
    if (!node) return;
    if (activeNode && activeNode !== node) activeNode.classList.remove("active");
    node.classList.toggle("active");
    activeNode = node.classList.contains("active") ? node : null;
  }

  canvas.addEventListener("dblclick", (e) => {
    const node = e.target.closest(".mesa-node");
    if (!node) return;
    e.preventDefault();
    togglePopoverFor(node);
  });

  document.addEventListener("click", (e) => {
    if (activeNode && !e.target.closest(".mesa-node")) closePopover();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePopover();
  });

  // ============================================================
  //  Drag & drop genérico (mesas y recepción)
  //  - Calcula posición en % relativo al canvas
  //  - Llama a onDrop({pos_x,pos_y}) al soltar
  //  - Cierra popover activo al iniciar drag
  //  - Añade/Quita clase .dragging para subir z-index en CSS
  // ============================================================
  function makeDraggable(el, { onDrop }) {
    let dragging = false, startX = 0, startY = 0, startLeft = 0, startTop = 0;

    const onDown = (e) => {
      if (canvas.getAttribute("data-editable") !== "1") return;
      dragging = true;

      closePopover();                 // si hay un popover abierto, ciérralo
      el.classList.add("dragging");   // <- eleva z-index mientras arrastras
      el.style.boxShadow = "0 6px 20px rgba(0,0,0,.12)";

      const pt = e.touches ? e.touches[0] : e;
      startX = pt.clientX; startY = pt.clientY;
      startLeft = parseFloat(el.style.left) || 0;
      startTop  = parseFloat(el.style.top)  || 0;
      e.preventDefault?.();
    };

    const onMove = (e) => {
      if (!dragging) return;
      const rect = canvas.getBoundingClientRect();
      const pt = e.touches ? e.touches[0] : e;
      const ddx = ((pt.clientX - startX) / rect.width) * 100;
      const ddy = ((pt.clientY - startY) / rect.height) * 100;
      const nx = Math.max(0, Math.min(100, startLeft + ddx));
      const ny = Math.max(0, Math.min(100, startTop + ddy));
      el.style.left = nx + "%";
      el.style.top  = ny + "%";
    };

    const onUp = async () => {
      if (!dragging) return;
      dragging = false;
      el.classList.remove("dragging");    // <- vuelve a z-index normal
      el.style.boxShadow = "0 2px 12px rgba(0,0,0,.06)";
      const pos_x = Math.round((parseFloat(el.style.left) || 0) * 100) / 100;
      const pos_y = Math.round((parseFloat(el.style.top)  || 0) * 100) / 100;
      try {
        await onDrop({ pos_x, pos_y });
        el.style.outline = "2px solid #22c55e"; // feedback OK
        setTimeout(() => (el.style.outline = "none"), 600);
      } catch (err) {
        console.error(err);
        el.style.outline = "2px solid #ef4444"; // feedback error
        setTimeout(() => (el.style.outline = "none"), 900);
      }
    };

    if ("onpointerdown" in window) {
      el.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    } else {
      el.addEventListener("mousedown", onDown);
      el.addEventListener("touchstart", onDown, { passive: false });
      window.addEventListener("mousemove", onMove);
      window.addEventListener("touchmove", onMove, { passive: false });
      window.addEventListener("mouseup", onUp);
      window.addEventListener("touchend", onUp);
    }
  }

  // ============================================================
  //  Mesas: inicializar posición + guardar al soltar
  // ============================================================
  const mesaNodes = Array.from(canvas.querySelectorAll(".mesa-node"));
  mesaNodes.forEach((node) => {
    const dx = parseFloat(node.dataset.x || "8");
    const dy = parseFloat(node.dataset.y || "8");
    node.style.left = dx + "%";
    node.style.top  = dy + "%";

    makeDraggable(node, {
      onDrop: async ({ pos_x, pos_y }) => {
        await postJSON(node.dataset.updateUrl, { pos_x, pos_y });
        node.dataset.x = String(pos_x);   // evita “rebotes”
        node.dataset.y = String(pos_y);
      },
    });
  });

  // ============================================================
  //  Recepción: inicializar posición + guardar al soltar
  // ============================================================
  const recepcion = document.getElementById("recepcionNode");
  if (recepcion) {
    const rx = parseFloat(recepcion.dataset.x || "3");
    const ry = parseFloat(recepcion.dataset.y || "3");
    recepcion.style.left = rx + "%";
    recepcion.style.top  = ry + "%";

    makeDraggable(recepcion, {
      onDrop: async ({ pos_x, pos_y }) => {
        await postJSON(recepcion.dataset.updateUrl, { pos_x, pos_y });
        recepcion.dataset.x = String(pos_x);
        recepcion.dataset.y = String(pos_y);
      },
    });
  }

  // ============================================================
  //  Auto-altura del canvas en función del número de mesas
  // ============================================================
  const mesasCount = mesaNodes.length;
  const base = 600;
  const extra = Math.ceil(mesasCount / 10) * 150;
  const max = 1600;
  canvas.style.minHeight = Math.min(base + extra, max) + "px";

  // ============================================================
  //  Filtro por zona (botones de la barra superior)
  // ============================================================
  const buttons = document.querySelectorAll("[data-zone-filter]");

  function applyZoneFilter(zona) {
    // estilos del botón activo
    buttons.forEach((b) => b.classList.remove("btn-secondary", "text-white"));
    const active = Array.from(buttons).find(
      (b) => (b.dataset.zoneFilter || "") === (zona || "")
    );
    if (active) active.classList.add("btn-secondary", "text-white");

    // mostrar/ocultar mesas
    mesaNodes.forEach((m) => {
      const mz = m.dataset.zona || "interior";
      m.style.display = !zona || zona === mz ? "flex" : "none";
    });

    closePopover(); // cierra popovers visibles al cambiar filtro
  }

  buttons.forEach((btn) =>
    btn.addEventListener("click", () => applyZoneFilter(btn.dataset.zoneFilter || ""))
  );
  applyZoneFilter(""); // “Todas” por defecto

  // ============================================================
  //  (Opcional) Modal de edición rápida vía AJAX
  // ============================================================
  const editButtons = document.querySelectorAll("[data-edit-mesa]");
  const editForm = document.getElementById("formEditMesa");
  if (editForm) {
    const fNumero    = editForm.querySelector("#editNumero");
    const fCapacidad = editForm.querySelector("#editCapacidad");
    const fUbicacion = editForm.querySelector("#editUbicacion");
    const fNotas     = editForm.querySelector("#editNotas");
    const fMesaId    = editForm.querySelector("#editMesaId");
    const fUrl       = editForm.querySelector("#editMesaUrl");
    const fZona      = editForm.querySelector("#editZona"); // <select> si existe

    editButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        fMesaId.value    = btn.dataset.mesaId || "";
        fUrl.value       = btn.dataset.editUrl || "";
        fNumero.value    = btn.dataset.numero || "";
        fCapacidad.value = btn.dataset.capacidad || "";
        fUbicacion.value = btn.dataset.ubicacion || "";
        fNotas.value     = btn.dataset.notas || "";
        if (fZona) fZona.value = btn.dataset.zona || "interior";
      });
    });

    editForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = fUrl.value;
      if (!url) return;

      const payload = new FormData(editForm);
      const body = {
        numero: Number(payload.get("numero") || 0),
        capacidad: Number(payload.get("capacidad") || 4),
        ubicacion: String(payload.get("ubicacion") || ""),
        notas: String(payload.get("notas") || ""),
        zona: String(payload.get("zona") || "interior"),
      };

      try {
        await postJSON(url, body);
        editForm.querySelector('[data-bs-dismiss="modal"]')?.click();
        window.location.reload();
      } catch (err) {
        console.error(err);
        alert("No se pudo guardar la mesa. Intenta de nuevo.");
      }
    });
  }
})();
