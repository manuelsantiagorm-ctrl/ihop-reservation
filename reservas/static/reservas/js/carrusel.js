// =======================================
// CARRUSEL SUCURSALES (con scroll-snap)
// - Flechas prev/next que avanzan 1 tarjeta exacta
// - Arrastre con mouse y gesto táctil
// =======================================
document.addEventListener("DOMContentLoaded", () => {
  const carousels = document.querySelectorAll(".js-carousel");
  if (!carousels.length) return;

  carousels.forEach((carousel) => {
    const strip   = carousel.querySelector(".strip");
    const btnPrev = carousel.querySelector(".carousel-btn.prev");
    const btnNext = carousel.querySelector(".carousel-btn.next");
    if (!strip) return;

    // Tamaño de un “paso” = ancho del primer ítem + gap
    const getStep = () => {
      const first = strip.querySelector(":scope > div");
      if (!first) return 320;
      const itemW = first.getBoundingClientRect().width;
      const styles = window.getComputedStyle(strip);
      const gap = parseFloat(styles.columnGap || styles.gap || "0") || 0;
      return Math.round(itemW + gap);
    };

    const scrollByStep = (dir = 1) => {
      strip.scrollBy({ left: dir * getStep(), behavior: "smooth" });
    };

    // Flechas
    btnPrev?.addEventListener("click", () => scrollByStep(-1));
    btnNext?.addEventListener("click", () => scrollByStep(1));

    // Arrastre con mouse
    let isDown = false, startX = 0, startLeft = 0;
    strip.addEventListener("mousedown", (e) => {
      isDown = true;
      startX = e.pageX;
      startLeft = strip.scrollLeft;
    });
    window.addEventListener("mouseup", () => { isDown = false; });
    strip.addEventListener("mousemove", (e) => {
      if (!isDown) return;
      e.preventDefault();
      const dx = e.pageX - startX;
      strip.scrollLeft = startLeft - dx;
    });

    // Gesto táctil
    let touchX = 0;
    strip.addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
    strip.addEventListener("touchmove",  (e) => {
      const x = e.touches[0].clientX;
      strip.scrollLeft += (touchX - x);
      touchX = x;
    }, { passive: true });
  });
});
