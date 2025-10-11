/* =======================================================
   Carrusel de sucursales (Home)
   - Controla el scroll horizontal con botones prev/next
   - Accesible y sin dependencias
   ======================================================= */

(function () {
  // Obtenemos la tira de cards (por ID específico de este carrusel)
  const strip = document.getElementById("sucursales-strip");
  if (!strip) return; // Si el partial no está en la página, salimos sin errores.

  // Flechas de navegación
  const prev = document.querySelector(".carousel-btn.prev");
  const next = document.querySelector(".carousel-btn.next");

  // Tamaño del desplazamiento (px) por click
  const STEP = 300;

  // Handlers para avanzar/retroceder
  const scrollLeft = () => strip.scrollBy({ left: -STEP, behavior: "smooth" });
  const scrollRight = () => strip.scrollBy({ left: STEP, behavior: "smooth" });

  // Asignación de eventos (si existen los botones)
  prev && prev.addEventListener("click", scrollLeft);
  next && next.addEventListener("click", scrollRight);

  // Accesibilidad: teclas flecha izquierda/derecha cuando el strip tiene foco
  strip.setAttribute("tabindex", "0");
  strip.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") scrollLeft();
    if (e.key === "ArrowRight") scrollRight();
  });
})();
