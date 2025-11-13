// static/reservas/js/ordenes.js
(function () {
  const modal = document.getElementById('modalOrden');
  if (!modal) return;

  const contenido = document.getElementById('ordenContenido');
  const cfg = window.ORDENES_CONFIG || {};
  const urlNueva = cfg.urlNuevaOrden;

  // abrir modal desde botón "Orden" de cada mesa
  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-orden-mesa]');
    if (!btn) return;

    const mesaId = btn.getAttribute('data-mesa-id');
    if (!mesaId || !urlNueva) return;

    contenido.innerHTML = `
      <div class="text-center py-4 text-muted">
        <div class="spinner-border"></div>
        <p class="mt-2">${(cfg.texto && cfg.texto.cargando) || 'Cargando...'}</p>
      </div>`;

    try {
      const res = await fetch(`${urlNueva}?mesa_id=${encodeURIComponent(mesaId)}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      const html = await res.text();
      contenido.innerHTML = html;
    } catch (e) {
      contenido.innerHTML = `<div class="alert alert-danger mb-0">${
        (cfg.texto && cfg.texto.error) || 'Error al cargar'
      }</div>`;
    }
  });

  // demo: agregar item y mover total
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('[data-orden-agregar-demo]')) return;
    const tbody = contenido.querySelector('[data-orden-items]');
    const totalEl = contenido.querySelector('[data-orden-total]');
    if (!tbody || !totalEl) return;

    const precio = 120; // demo
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>1</td>
      <td>Pancakes demo</td>
      <td class="text-end">$${precio.toFixed(2)}</td>
      <td class="text-center">1</td>
      <td class="text-end">$${precio.toFixed(2)}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-link text-danger" title="Quitar" data-orden-del>&times;</button>
      </td>`;
    tbody.appendChild(row);

    // actualizar total
    const cur = Number((totalEl.textContent || '0').replace(/[^0-9.]/g, '')) || 0;
    totalEl.textContent = `$${(cur + precio).toFixed(2)}`;

    // habilitar botones
    contenido.querySelector('[data-orden-enviar]')?.removeAttribute('disabled');
    contenido.querySelector('[data-orden-cobrar]')?.removeAttribute('disabled');
  });

  // demo: eliminar item
  document.addEventListener('click', (ev) => {
    const del = ev.target.closest('[data-orden-del]');
    if (!del) return;
    const tr = del.closest('tr');
    const totalEl = contenido.querySelector('[data-orden-total]');
    if (tr && totalEl) {
      const importe = Number((tr.querySelector('td:nth-child(5)')?.textContent || '0').replace(/[^0-9.]/g, '')) || 0;
      tr.remove();
      const cur = Number((totalEl.textContent || '0').replace(/[^0-9.]/g, '')) || 0;
      totalEl.textContent = `$${Math.max(0, cur - importe).toFixed(2)}`;
    }
  });
})();
