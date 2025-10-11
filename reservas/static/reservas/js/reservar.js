document.addEventListener("DOMContentLoaded", function () {
    console.log("reservar.js cargado ✅");

    const slotsWrap = document.getElementById("slotsWrap");
    const fechaInput = document.getElementById("inputFecha");
    const btnCargar = document.getElementById("btnCargar");

    function cargarHorarios() {
        if (!fechaInput.value) return;

        const url = `${window.urlDisponibilidad}?fecha=${fechaInput.value}`;
        console.log("Consultando horarios en:", url);

        fetch(url)
            .then(response => response.json())
            .then(data => {
                slotsWrap.innerHTML = "";

                if (data.slots && data.slots.length > 0) {
                    data.slots.forEach(hora => {
                        const div = document.createElement("div");
                        div.className = "slot-pill";
                        div.textContent = hora;

                        div.addEventListener("click", () => {
                            document.querySelectorAll(".slot-pill").forEach(el => el.classList.remove("active"));
                            div.classList.add("active");

                            // Asigna la hora al campo oculto (form.fecha)
                            const fechaCampo = document.getElementById("id_fecha");
                            if (fechaCampo) {
                                fechaCampo.value = `${data.fecha}T${hora}`;
                            }
                        });

                        slotsWrap.appendChild(div);
                    });
                } else {
                    slotsWrap.innerHTML = `<div class="text-muted">No hay horarios disponibles</div>`;
                }
            })
            .catch(err => {
                console.error("Error cargando horarios:", err);
                slotsWrap.innerHTML = `<div class="text-danger">Error al cargar horarios</div>`;
            });
    }

    // Eventos
    btnCargar.addEventListener("click", cargarHorarios);
    fechaInput.addEventListener("change", cargarHorarios);

    // Cargar al inicio
    cargarHorarios();
});
