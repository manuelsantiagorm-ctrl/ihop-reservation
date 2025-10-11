/* Append Time
   - Toma la hora seleccionada en el input .hero [name="time"]
   - La agrega (si no existe) como ?time=HH:MM a todos los links .js-append-time
   - Útil para que los enlaces del carrusel o cards respeten la hora del filtro
*/
(function(){
  const timeInput = document.querySelector('.hero input[name="time"]');
  if (!timeInput) return;

  document.querySelectorAll('.js-append-time').forEach((link) => {
    link.addEventListener('click', () => {
      const t = (timeInput.value || '').trim();
      if (!t) return;

      const url = new URL(link.href, window.location.origin);
      if (!url.searchParams.get('time')) {
        url.searchParams.set('time', t);
        link.href = url.toString();
      }
    });
  });
})();
