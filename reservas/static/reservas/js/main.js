// Auto-dismiss de alerts (5s)
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(el => {
      const inst = bootstrap.Alert.getOrCreateInstance(el);
      inst.close();
    });
  }, 5000);
});

// reservas/static/reservas/js/main.js

// Auto-cerrar mensajes de Django
(function () {
  const AUTO_CLOSE_MS = 4000;
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(el => {
      // Si usas Bootstrap, quitar 'show' aplica el fade
      el.classList.remove('show');
      setTimeout(() => el.remove(), 300);
    });
  }, AUTO_CLOSE_MS);
})();

// Si quieres evitar multi-submit en forms:
document.addEventListener('submit', (e) => {
  const btn = e.target.querySelector('[type="submit"]');
  if (btn) {
    btn.disabled = true;
    btn.dataset.originalText = btn.innerHTML;
    btn.innerHTML = btn.dataset.loadingText || 'Procesando...';
  }
});
