// Mostrar/ocultar contraseña
(function () {
  const btn = document.getElementById("togglePwd");
  if (!btn) return;
  const input = btn.parentElement.querySelector("input[type='password'], input[type='text']");
  btn.addEventListener("click", () => {
    const isPwd = input.getAttribute("type") === "password";
    input.setAttribute("type", isPwd ? "text" : "password");
    btn.setAttribute("aria-pressed", String(isPwd));
  });
})();
