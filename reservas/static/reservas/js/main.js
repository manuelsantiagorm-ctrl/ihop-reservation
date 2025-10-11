// Auto-dismiss de alerts (5s)
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(el => {
      const inst = bootstrap.Alert.getOrCreateInstance(el);
      inst.close();
    });
  }, 5000);
});
