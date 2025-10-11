// ================== helpers ==================
console.log("admin.js cargado (nuevo)");

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return null;
}

// POST JSON => { status, json? , html? }
async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCookie("csrftoken"),
      "X-Requested-With": "XMLHttpRequest",
    },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  try {
    return { status: res.status, json: JSON.parse(text) };
  } catch {
    return { status: res.status, html: text };
  }
}

async function getJSON(url) {
  const res = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: { "X-Requested-With": "XMLHttpRequest" },
  });
  const text = await res.text();
  try {
    return { status: res.status, json: JSON.parse(text) };
  } catch {
    return { status: res.status, html: text };
  }
}

// ================== EDITAR MESA ==================
document.addEventListener("DOMContentLoaded", () => {
  const modalEl = document.getElementById("modalEditMesa");
  const form = document.getElementById("formEditMesa");
  if (modalEl && form) {
    const modal = new bootstrap.Modal(modalEl);

    const $id  = document.getElementById("editMesaId");
    const $url = document.getElementById("editMesaUrl"); // hidden donde guardamos la URL del API
    const $num = document.getElementById("editNumero");
    const $cap = document.getElementById("editCapacidad");
    const $ubi = document.getElementById("editUbicacion");
    const $not = document.getElementById("editNotas");

    // Abrir y precargar desde el botón
    document.querySelectorAll("[data-edit-mesa]").forEach((btn) => {
      btn.addEventListener("click", () => {
        $id.value  = btn.dataset.mesaId || "";
        $url.value = btn.dataset.editUrl || ""; // viene del template

        $num.value = btn.dataset.numero || "";
        $cap.value = btn.dataset.capacidad || 1;
        $ubi.value = btn.dataset.ubicacion || "";
        $not.value = btn.dataset.notas || "";

        modal.show();
      });
    });

    // Guardar cambios
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const url = $url.value;
      if (!url) return alert("No se encontró la URL del API para editar.");

      const payload = {
        numero: ($num.value || "").trim(),
        capacidad: ($cap.value || "").trim(),
        ubicacion: ($ubi.value || "").trim() || null,
        notas: ($not.value || "").trim() || null,
      };

      try {
        const { status, json, html } = await postJSON(url, payload);
        if (status !== 200 || !json || json.ok === false) {
          const msg = (json && json.error) ? json.error : (html || "Error al actualizar la mesa.");
          throw new Error(msg);
        }
        modal.hide();
        // Refresca para que se actualicen las tarjetas/badges
        window.location.reload();
      } catch (err) {
        console.error(err);
        alert("No se pudo guardar: " + err.message);
      }
    });
  }
});

// ================== BLOQUEO (crear: sucursal/mesa) ==================
document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("modalBloqueo");
  const form  = document.getElementById("formBloqueo");
  if (!modal || !form) return;

  // Abrir modal desde botones con data-bloqueo
  document.querySelectorAll("[data-bloqueo]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sucId  = btn.getAttribute("data-sucursal-id");
      const mesaId = btn.getAttribute("data-mesa-id") || "";

      form.querySelector('[name="sucursal_id"]').value = sucId || "";
      form.querySelector('[name="mesa_id"]').value     = mesaId;

      bootstrap.Modal.getOrCreateInstance(modal).show();
    });
  });

  // Enviar bloqueo
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = form.dataset.url;

    const sucursal_id = Number(form.querySelector('[name="sucursal_id"]').value);
    const mesa_raw    = form.querySelector('[name="mesa_id"]').value;
    const mesa_id     = mesa_raw ? Number(mesa_raw) : null;

    const inicio = form.querySelector('[name="inicio"]').value; // YYYY-MM-DDTHH:MM
    const fin    = form.querySelector('[name="fin"]').value;    // YYYY-MM-DDTHH:MM
    const motivo = (form.querySelector('[name="motivo"]').value || "").trim();

    if (!inicio || !fin) { alert("Inicio y fin son obligatorios."); return; }

    try {
      const { status, json, html } = await postJSON(url, { sucursal_id, mesa_id, inicio, fin, motivo });
      if (status !== 200 || !json || json.ok === false) {
        throw new Error((json && json.error) ? json.error : (html || "Error al crear el bloqueo."));
      }
      alert("Bloqueo creado");
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      window.location.reload();
    } catch (err) {
      console.error(err);
      alert("No se pudo crear el bloqueo: " + err.message);
    }
  });
});

// ================== BLOQUEOS (listar / eliminar) ==================
function renderBloqueosList(container, items) {
  if (!items || !items.length) {
    container.innerHTML = `<div class="text-muted">No hay bloqueos activos desde hoy.</div>`;
    return;
  }
  container.innerHTML = items
    .map((it) => {
      const ini = new Date(it.inicio);
      const fin = new Date(it.fin);
      const rango = `${ini.toLocaleString()} — ${fin.toLocaleTimeString()}`;
      const scope = it.scope === "mesa" ? `Mesa ${it.mesa_id}` : "Sucursal completa";
      const mot = it.motivo ? ` · ${it.motivo}` : "";
      return `
        <div class="d-flex justify-content-between align-items-center border rounded p-2 mb-2">
          <div>
            <div><b>${scope}</b>${mot}</div>
            <div class="text-muted small">${rango}</div>
          </div>
          <button class="btn btn-sm btn-outline-danger" data-del-bloqueo="${it.id}">
            Eliminar
          </button>
        </div>
      `;
    })
    .join("");
}

function setupBloqueosList() {
  const modalEl = document.getElementById("modalBloqueosList");
  if (!modalEl) return;

  const listBox = modalEl.querySelector("[data-bloqueos-list]");
  const btns = document.querySelectorAll("[data-ver-bloqueos]");
  const urlList = modalEl.getAttribute("data-url-list");
  const urlDel  = modalEl.getAttribute("data-url-del");

  // Abrir modal con lista
  btns.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const sucursalId = btn.getAttribute("data-sucursal-id");
      const mesaId = btn.getAttribute("data-mesa-id") || "";
      const params = new URLSearchParams({
        sucursal_id: sucursalId,
        ...(mesaId ? { mesa_id: mesaId } : {}),
      });
      listBox.innerHTML = `<div class="text-muted">Cargando…</div>`;
      const { status, json } = await getJSON(`${urlList}?${params.toString()}`);
      if (status !== 200 || !json || json.ok === false) {
        listBox.innerHTML = `<div class="text-danger">Error al cargar bloqueos.</div>`;
      } else {
        renderBloqueosList(listBox, json.items);
      }
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    });
  });

  // Eliminar (delegación)
  modalEl.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-del-bloqueo]");
    if (!btn) return;

    if (!confirm("¿Eliminar este bloqueo?")) return;
    const id = Number(btn.getAttribute("data-del-bloqueo"));

    const { status, json } = await postJSON(urlDel, { id });
    if (status !== 200 || !json || json.ok === false) {
      alert(json?.error || "No se pudo eliminar el bloqueo.");
      return;
    }

    btn.closest(".d-flex").remove();
    if (!listBox.querySelector(".d-flex")) {
      listBox.innerHTML = `<div class="text-muted">No hay bloqueos activos desde hoy.</div>`;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupBloqueosList();
});


function extractHtmlError(html) {
  if (!html) return "Error del servidor";
  const m = String(html).match(/<title>([^<]+)<\/title>/i);
  return m ? m[1] : "Error del servidor";
}
