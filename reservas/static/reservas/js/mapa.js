/* global document, window */
(function () {
  const canvas = document.getElementById("mapCanvas");
  if (!canvas) return;

  // ============================================================
  //  URLs absolutas + CSRF
  // ============================================================
  const ORIGIN = window.location.origin; // ej: http://127.0.0.1:8000
  function absUrl(u) {
    try { return new URL(u, ORIGIN).toString(); } catch { return u; }
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(";").shift());
  }
  const csrftoken = getCookie("csrftoken");

  async function postJSON(url, payload) {
    const res = await fetch(absUrl(url), {
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

  // Cerrar con click fuera y con ESC
  document.addEventListener("click", (e) => {
    if (activeNode && !e.target.closest(".mesa-node")) closePopover();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePopover();
  });

  // ============================================================
  //  Drag & drop genérico (mesas y recepción) con umbral
  // ============================================================
  function makeDraggable(el, { onDrop }) {
    let dragging = false, maybeDrag = false;
    let startX = 0, startY = 0, startLeft = 0, startTop = 0;

    const THRESHOLD = 3; // px para no matar el dblclick

    const onDown = (e) => {
      if (canvas.getAttribute("data-editable") !== "1") return;
      if (e.target.closest(".mesa-toolbar")) return; // no drag desde la toolbar
      // NO preventDefault aquí: permite que el navegador dispare dblclick
      maybeDrag = true;
      dragging  = false;

      const pt = e.touches ? e.touches[0] : e;
      startX = pt.clientX; startY = pt.clientY;
      startLeft = parseFloat(el.style.left) || 0;
      startTop  = parseFloat(el.style.top)  || 0;
    };

    const onMove = (e) => {
      if (!maybeDrag) return;

      const pt = e.touches ? e.touches[0] : e;
      const dx = pt.clientX - startX;
      const dy = pt.clientY - startY;
      const dist = Math.hypot(dx, dy);

      if (!dragging && dist < THRESHOLD) return;

      // activar drag al superar el umbral
      if (!dragging) {
        closePopover();               // cierra popover si estaba abierto
        el.classList.add("dragging"); // sube z-index
        el.style.boxShadow = "0 6px 20px rgba(0,0,0,.12)";
        dragging = true;
      }

      const rect = canvas.getBoundingClientRect();
      const ddx = (dx / rect.width)  * 100;
      const ddy = (dy / rect.height) * 100;
      const nx = Math.max(0, Math.min(100, startLeft + ddx));
      const ny = Math.max(0, Math.min(100, startTop  + ddy));
      el.style.left = nx + "%";
      el.style.top  = ny + "%";
    };

    const onUp = async () => {
      if (!maybeDrag) return;
      const endedDragging = dragging;
      maybeDrag = false;
      dragging  = false;

      if (endedDragging) {
        el.classList.remove("dragging");
        el.style.boxShadow = "0 2px 12px rgba(0,0,0,.06)";
        const pos_x = Math.round((parseFloat(el.style.left) || 0) * 100) / 100;
        const pos_y = Math.round((parseFloat(el.style.top)  || 0) * 100) / 100;
        try {
          await onDrop({ pos_x, pos_y });
          el.style.outline = "2px solid #22c55e";
          setTimeout(() => (el.style.outline = "none"), 600);
        } catch (err) {
          console.error(err);
          el.style.outline = "2px solid #ef4444";
          setTimeout(() => (el.style.outline = "none"), 900);
        }
      }
      // Si no hubo drag, dejamos que el navegador maneje el dblclick normal
    };

    if ("onpointerdown" in window) {
      el.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    } else {
      el.addEventListener("mousedown", onDown);
      el.addEventListener("touchstart", onDown, { passive: true });
      window.addEventListener("mousemove", onMove);
      window.addEventListener("touchmove", onMove, { passive: true });
      window.addEventListener("mouseup", onUp);
      window.addEventListener("touchend", onUp);
    }
  }

  // ============================================================
  //  Mesas: inicializar, drag y dblclick de popover
  // ============================================================
  const mesaNodes = Array.from(canvas.querySelectorAll(".mesa-node"));
  mesaNodes.forEach((node) => {
    const dx = parseFloat(node.dataset.x || "8");
    const dy = parseFloat(node.dataset.y || "8");
    node.style.left = dx + "%";
    node.style.top  = dy + "%";

    // Doble clic confiable en cada mesa
    node.addEventListener("dblclick", (e) => {
      if (e.target.closest(".mesa-toolbar")) return; // si fue sobre toolbar, no togglear
      togglePopoverFor(node);
    });

    makeDraggable(node, {
      onDrop: async ({ pos_x, pos_y }) => {
        await postJSON(node.dataset.updateUrl, { pos_x, pos_y });
        node.dataset.x = String(pos_x);
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
  //  Auto-altura del canvas en función de #mesas
  // ============================================================
  const base = 600;
  const extra = Math.ceil(mesaNodes.length / 10) * 150;
  const max = 1600;
  canvas.style.minHeight = Math.min(base + extra, max) + "px";

  // ============================================================
  //  Filtro por zona (botones superiores)
  // ============================================================
  const buttons = document.querySelectorAll("[data-zone-filter]");

  function applyZoneFilter(zona) {
    buttons.forEach((b) => b.classList.remove("btn-secondary", "text-white"));
    const active = Array.from(buttons).find(
      (b) => (b.dataset.zoneFilter || "") === (zona || "")
    );
    if (active) active.classList.add("btn-secondary", "text-white");

    mesaNodes.forEach((m) => {
      const mz = m.dataset.zona || "interior";
      m.style.display = !zona || zona === mz ? "flex" : "none";
    });
    closePopover();
  }

  buttons.forEach((btn) =>
    btn.addEventListener("click", () => applyZoneFilter(btn.dataset.zoneFilter || ""))
  );
  applyZoneFilter("");

  // ============================================================
  //  (Opcional) Modal de edición rápida vía AJAX (si existe)
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


// ===============================
//  AUTOCOMPLETE DE PRODUCTOS
// ===============================
(function () {
  const CFG = window.ORDENES_CONFIG || {};
  if (!CFG.searchUrl) return; // sin URL no activamos el autocomplete

  // Helpers
  const ORIGIN = window.location.origin;
  const absUrl = (u) => { try { return new URL(u, ORIGIN).toString(); } catch { return u; } };
  const debounce = (fn, ms=250) => {
    let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  };

  // Campos del modal (con fallback por name)
  const $modal     = document.getElementById('modalOrden');
  if (!$modal) return;

  const $buscar    = $modal.querySelector('[data-orden-buscar]') 
                  || $modal.querySelector('input[name="buscar"]')
                  || $modal.querySelector('input[placeholder*="2-3 letras"]');
  const $codigo    = $modal.querySelector('[data-orden-codigo]') 
                  || $modal.querySelector('input[name="codigo"]');
  const $nombre    = $modal.querySelector('[data-orden-nombre]') 
                  || $modal.querySelector('input[name="nombre"]');
  const $cantidad  = $modal.querySelector('[data-orden-cantidad]') 
                  || $modal.querySelector('input[name="cantidad"]');

  if (!$buscar || !$codigo || !$nombre) return;

  // Contenedor de sugerencias (se crea si no existe)
  let $drop = $modal.querySelector('#orden-sugerencias');
  if (!$drop) {
    $drop = document.createElement('div');
    $drop.id = 'orden-sugerencias';
    $drop.style.position = 'absolute';
    $drop.style.zIndex = '2000';
    $drop.style.minWidth = '260px';
    $drop.style.maxHeight = '240px';
    $drop.style.overflowY = 'auto';
    $drop.style.border = '1px solid rgba(0,0,0,.1)';
    $drop.style.borderRadius = '10px';
    $drop.style.background = '#fff';
    $drop.style.boxShadow = '0 12px 28px rgba(0,0,0,.15)';
    $drop.style.display = 'none';
    $modal.appendChild($drop);
  }

  function placeDropdown() {
    const r = $buscar.getBoundingClientRect();
    const m = $modal.getBoundingClientRect();
    // posición relativa al modal
    $drop.style.left = (r.left - m.left) + 'px';
    $drop.style.top  = (r.bottom - m.top + 6) + 'px';
    $drop.style.width = r.width + 'px';
  }

  function hide() { $drop.style.display = 'none'; $drop.innerHTML = ''; }
  function show() { placeDropdown(); $drop.style.display = 'block'; }

  function render(items) {
    if (!items || !items.length) { hide(); return; }
    const html = items.map((p, idx) => `
      <button type="button" class="list-group-item list-group-item-action" 
              style="display:block;text-align:left;border:0;border-bottom:1px solid rgba(0,0,0,.06);padding:.5rem .75rem;"
              data-codigo="${p.codigo}" data-nombre="${p.nombre}">
        <div style="font-weight:600">${p.nombre}</div>
        <small class="text-muted">${p.codigo}${p.precio ? " · $" + p.precio : ""}</small>
      </button>
    `).join('');
    $drop.innerHTML = html;
    show();
  }

  async function buscar(term) {
    term = (term || '').trim();
    if (term.length < 2) { hide(); return; }
    try {
      const res = await fetch(absUrl(CFG.searchUrl) + '?q=' + encodeURIComponent(term), {
        headers: { 'X-Requested-With': 'fetch' },
        credentials: 'same-origin'
      });
      if (!res.ok) throw new Error('HTTP '+res.status);
      const data = await res.json();
      // espera un array de objetos: [{codigo, nombre, precio}, ...]
      render(Array.isArray(data) ? data : (data.results || []));
    } catch (e) {
      console.error('buscar productos:', e);
      hide();
    }
  }

  const doBuscar = debounce(() => buscar($buscar.value), 250);

  // Eventos
  $buscar.addEventListener('input', doBuscar);
  $buscar.addEventListener('focus', () => { if ($drop.innerHTML) show(); placeDropdown(); });
  window.addEventListener('resize', placeDropdown);
  $modal.addEventListener('scroll', placeDropdown, true);

  // Click en sugerencia
  $drop.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-codigo]');
    if (!btn) return;
    $codigo.value = btn.dataset.codigo || '';
    $nombre.value = btn.dataset.nombre || '';
    hide();
    $cantidad?.focus();
  });

  // Teclado básico: Esc cierra
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });

  // Click fuera cierra
  document.addEventListener('click', (e) => {
    if ($drop.contains(e.target) || e.target === $buscar) return;
    hide();
  });
})();
