(function () {
  const mapDiv = document.getElementById("admin-branch-map");
  if (!mapDiv) return;

  const inputAuto = document.getElementById("gmaps-autocomplete");
  const inputLat = document.getElementById("id_lat");
  const inputLng = document.getElementById("id_lng");
  const inputPID = document.getElementById("id_place_id");
  const inputDireccion = document.getElementById("id_direccion");
  const inputCP = document.getElementById("id_codigo_postal");

  let center = { lat: 19.432608, lng: -99.133209 }; // CDMX
  if (inputLat?.value && inputLng?.value) {
    center = { lat: parseFloat(inputLat.value), lng: parseFloat(inputLng.value) };
  }

  const map = new google.maps.Map(mapDiv, { center, zoom: 15, mapTypeControl: false, streetViewControl: false });
  const marker = new google.maps.Marker({ position: center, map, draggable: true });
  const geocoder = new google.maps.Geocoder();

  function setFormFromPlace(place) {
    if (!place.geometry?.location) return;
    const loc = place.geometry.location;
    const lat = loc.lat(), lng = loc.lng();
    inputLat.value = lat.toFixed(6);
    inputLng.value = lng.toFixed(6);
    inputPID.value = place.place_id || "";
    inputDireccion.value = place.formatted_address || place.name || inputDireccion.value;

    if (place.address_components) {
      const cpComp = place.address_components.find(c => c.types.includes("postal_code"));
      if (cpComp) inputCP.value = cpComp.long_name;
    }

    map.panTo({ lat, lng });
    marker.setPosition({ lat, lng });
  }

  function reverseGeocode(lat, lng) {
    geocoder.geocode({ location: { lat, lng } }, (results, status) => {
      if (status === "OK" && results?.[0]) {
        inputDireccion.value = results[0].formatted_address;
        const cpComp = results[0].address_components.find(c => c.types.includes("postal_code"));
        if (cpComp) inputCP.value = cpComp.long_name;
      }
    });
  }

  if (inputAuto) {
    const ac = new google.maps.places.Autocomplete(inputAuto, {
      fields: ["place_id", "geometry", "formatted_address", "name", "address_components"]
    });
    ac.addListener("place_changed", () => setFormFromPlace(ac.getPlace()));
  }

  marker.addListener("dragend", (e) => {
    const lat = e.latLng.lat(), lng = e.latLng.lng();
    inputLat.value = lat.toFixed(6);
    inputLng.value = lng.toFixed(6);
    reverseGeocode(lat, lng);
  });

  const btnLoc = document.getElementById("btnUseMyLocation");
  if (btnLoc && navigator.geolocation) {
    btnLoc.addEventListener("click", () => {
      navigator.geolocation.getCurrentPosition((pos) => {
        const lat = pos.coords.latitude, lng = pos.coords.longitude;
        map.setCenter({ lat, lng });
        marker.setPosition({ lat, lng });
        inputLat.value = lat.toFixed(6);
        inputLng.value = lng.toFixed(6);
        reverseGeocode(lat, lng);
      });
    });
  }
})();
