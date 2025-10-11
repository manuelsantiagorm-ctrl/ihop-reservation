// ======================================================
// Botones "Cerca de mí"
// - Home desktop:   #btnNearMeHome
// - Home móvil:     #btnNearMeHomeMobile
// - Seleccionar desktop: #btnNearMeSelect
// - Seleccionar móvil:   #btnNearMeSelectMobile
// Redirige a /seleccionar_sucursal/?lat=..&lng=..&km=10
// ======================================================
(function () {
  function goToNearest(lat, lng) {
    const km = 10; // radio de búsqueda
    const url = `/seleccionar_sucursal/?lat=${lat}&lng=${lng}&km=${km}`;
    window.location.href = url;
  }

  function askGeolocation(btn) {
    if (!navigator.geolocation) {
      alert("Tu navegador no soporta geolocalización.");
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.dataset._old = btn.innerHTML;
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2"></span>Localizando...';
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        goToNearest(latitude, longitude);
      },
      (err) => {
        console.error(err);
        alert("No se pudo obtener tu ubicación. Revisa permisos e inténtalo de nuevo.");
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = btn.dataset._old || btn.innerHTML;
        }
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }

  // Vincula todos los posibles botones (desktop y móvil)
  ["btnNearMeHome", "btnNearMeHomeMobile", "btnNearMeSelect", "btnNearMeSelectMobile"]
    .forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("click", () => askGeolocation(el));
    });
})();


// ---- Reintentar "Cerca de mí" desde el aviso ----
(function () {
  const again = document.getElementById('btnNearMeAgain');
  const againMobile = document.getElementById('btnNearMeAgainMobile');

  function triggerNearMe() {
    const btn = document.getElementById('btnNearMeSelect') || document.getElementById('btnNearMeSelectMobile');
    if (btn) btn.click();
  }

  if (again) again.addEventListener('click', triggerNearMe);
  if (againMobile) againMobile.addEventListener('click', triggerNearMe);
})();
