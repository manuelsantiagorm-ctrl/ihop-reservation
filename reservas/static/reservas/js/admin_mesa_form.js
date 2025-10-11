(function () {
  const form = document.getElementById("mesaEditForm");
  if (!form) return;

  // Autofocus al primer input visible
  const first = form.querySelector("input, select, textarea");
  if (first) first.focus();

  // Confirmación si hay cambios sin guardar
  let dirty = false;
  form.addEventListener("input", () => { dirty = true; });
  window.addEventListener("beforeunload", (e) => {
    if (!dirty) return;
    e.preventDefault();
    e.returnValue = "";
  });

  // Si guarda, desactiva el warning y bloquea doble submit
  const saveBtn = document.getElementById("saveBtn");
  form.addEventListener("submit", (e) => {
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "Guardando…";
    }
    dirty = false;
  });
})();
