(function(){
  // Copiar folio con Toast
  const toastEl = document.getElementById('toast-copiado');
  const toast = toastEl ? new bootstrap.Toast(toastEl) : null;

  function copyFromSelector(sel){
    const el = document.querySelector(sel);
    if(!el) return;
    const text = (el.innerText || el.textContent || '').trim();
    if(!text) return;

    navigator.clipboard?.writeText(text).then(()=>{
      toast && toast.show();
    }).catch(()=>{
      // fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select(); document.execCommand('copy'); ta.remove();
      toast && toast.show();
    });
  }

  document.querySelectorAll('.myr-copy').forEach(btn=>{
    btn.addEventListener('click', (e)=>{
      const target = btn.getAttribute('data-copy-target');
      if(target){ copyFromSelector(target); }
    });
  });

  // Buscador simple en tabla de pasadas
  const input = document.getElementById('myr-search');
  const rows = document.querySelectorAll('#tabla-pasadas tbody tr');
  if(input && rows.length){
    input.addEventListener('input', ()=>{
      const q = input.value.toLowerCase();
      rows.forEach(tr=>{
        const txt = tr.innerText.toLowerCase();
        tr.style.display = txt.includes(q) ? '' : 'none';
      });
    });
  }
})();
