(function(){
  const btn = document.getElementById("nearMeHomeBtn");
  if(!btn) return;

  async function getNearby(lat, lng, km){
    const url = `/api/sucursales/nearby/?lat=${lat}&lng=${lng}&km=${km}`;
    const res = await fetch(url, {headers: {"X-Requested-With":"fetch"}});
    if(!res.ok) throw new Error("Error al cargar sucursales cercanas");
    return (await res.json()).results || [];
  }

  function paint(list){
    const cont = document.getElementById("nearMeResults");
    const empty = document.getElementById("nearMeEmpty");
    cont.innerHTML = "";
    if(!list.length){
      empty.classList.remove("d-none");
      return;
    }
    empty.classList.add("d-none");
    list.forEach((suc, i)=>{
      const el = document.createElement("a");
      el.className = "list-group-item list-group-item-action";
      const badge = (i===0) ? `<span class="badge bg-success ms-2">Recomendada</span>` : "";
      const dist = typeof suc.dist_km === "number" ? `${suc.dist_km} km` : "";
      el.innerHTML = `
        <div class="d-flex w-100 justify-content-between">
          <h6 class="mb-1">${suc.nombre} ${badge}</h6>
          <small class="text-muted">${dist}</small>
        </div>
        <p class="mb-2 text-muted">${suc.direccion || ""}</p>
        <div class="d-flex gap-2">
          <a class="btn btn-sm btn-primary" href="${suc.reservar_url}">Reservar</a>
          <a class="btn btn-sm btn-outline-secondary" target="_blank"
             href="https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(suc.direccion || (suc.lat+','+suc.lng))}">
            Cómo llegar
          </a>
        </div>
      `;
      el.addEventListener("click", (ev)=> ev.preventDefault());
      cont.appendChild(el);
    });
  }

  function showModal(){
    const modal = new bootstrap.Modal(document.getElementById("nearMeModal"));
    modal.show();
  }

  btn.addEventListener("click", ()=>{
    const km = document.getElementById("nearKm")?.value || 25;
    if(!navigator.geolocation){
      alert("Tu navegador no soporta geolocalización.");
      return;
    }
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Buscando...';

    navigator.geolocation.getCurrentPosition(async (pos)=>{
      try{
        const { latitude, longitude } = pos.coords;
        const list = await getNearby(latitude, longitude, km);
        paint(list);
        showModal();
      }catch(err){
        console.error(err);
        alert("No se pudieron cargar las sucursales cercanas.");
      }finally{
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-geo"></i> Near me';
      }
    }, (err)=>{
      console.warn(err);
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-geo"></i> Near me';
      // Fallback: abrir el mapa general
      window.location.href = "/sucursales/";
    }, {enableHighAccuracy:true, timeout:8000});
  });
})();
