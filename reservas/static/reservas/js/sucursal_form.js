(function () {
  const addressInput = document.getElementById('id_direccion');
  const latInput = document.getElementById('id_lat');
  const lngInput = document.getElementById('id_lng');
  const placeIdInput = document.getElementById('id_place_id');
  const paisSelect = document.getElementById('id_pais');

  if (!addressInput || !latInput || !lngInput || !placeIdInput || !paisSelect) return;

  const start = {
    lat: parseFloat(latInput.value) || 19.4326,
    lng: parseFloat(lngInput.value) || -99.1332
  };

  const mapEl = document.getElementById('map');
  if (!mapEl || typeof google === 'undefined' || !google.maps) return;

  const map = new google.maps.Map(mapEl, {
    center: start,
    zoom: 13,
    mapTypeControl: false
  });

  const marker = new google.maps.Marker({
    map,
    position: start,
    draggable: true
  });

  marker.addListener('dragend', () => {
    const pos = marker.getPosition();
    latInput.value = pos.lat().toFixed(6);
    lngInput.value = pos.lng().toFixed(6);
  });

  const ac = new google.maps.places.Autocomplete(addressInput, {
    fields: ['geometry', 'place_id', 'address_components', 'formatted_address']
  });

  ac.addListener('place_changed', () => {
    const place = ac.getPlace();
    if (!place.geometry) return;

    map.panTo(place.geometry.location);
    marker.setPosition(place.geometry.location);

    latInput.value = place.geometry.location.lat().toFixed(6);
    lngInput.value = place.geometry.location.lng().toFixed(6);
    placeIdInput.value = place.place_id || '';

    const country = (place.address_components || []).find(c => c.types.includes('country'));
    if (country) {
      for (const opt of paisSelect.options) {
        if (opt.value === country.short_name || opt.text.toUpperCase() === country.long_name.toUpperCase()) {
          paisSelect.value = opt.value;
          break;
        }
      }
    }
  });

  const useLocBtn = document.getElementById('btnUseLocation');
  if (useLocBtn && navigator.geolocation) {
    useLocBtn.addEventListener('click', () => {
      navigator.geolocation.getCurrentPosition(({ coords }) => {
        const pos = { lat: coords.latitude, lng: coords.longitude };
        map.panTo(pos);
        marker.setPosition(pos);
        latInput.value = pos.lat.toFixed(6);
        lngInput.value = pos.lng.toFixed(6);
      });
    });
  }

  // Bootstrap validation
  const form = document.getElementById('sucursalForm');
  if (form) {
    form.addEventListener('submit', (event) => {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      form.classList.add('was-validated');
    }, false);
  }
})();
