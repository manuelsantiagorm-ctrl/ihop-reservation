/**
 * exito.js
 * 
 * Script para la pantalla de confirmación de reservación (reserva_exito.html).
 * 
 * Funcionalidad:
 *  - Permite copiar el FOLIO de la reservación al portapapeles con un botón.
 *  - Muestra feedback visual ("¡Copiado!") para confirmar la acción al usuario.
 * 
 * Ubicación en templates:
 *  - templates/reservas/reserva_exito.html
 * 
 */

(function () {
  const btn = document.getElementById("copy-folio");
  const el  = document.getElementById("folio-text");
  if (!btn || !el) return;

  btn.addEventListener("click", async () => {
    const t = (el.innerText || el.textContent || "").trim();
    if (!t) return;
    try {
      await navigator.clipboard.writeText(t);
      const original = btn.innerText;
      btn.innerText = "¡Copiado!";
      btn.disabled = true;
      setTimeout(() => {
        btn.innerText = original;
        btn.disabled = false;
      }, 1200);
    } catch (e) {
      console.warn("No se pudo copiar al portapapeles:", e);
      // fallback visual mínimo
      prompt("Copia tu folio:", t);
    }
  });
})();
