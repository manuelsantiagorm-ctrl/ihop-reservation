function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? m.pop() : '';
}
function csrfHeaders() {
  return {'X-CSRFToken': getCookie('csrftoken')};
}
