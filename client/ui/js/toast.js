// Transient notifications (bottom of the screen).

export function showToast(message, type = 'info') {
  const host = document.getElementById('toast-host');
  if (!host) return;
  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = message;
  host.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 20);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 180);
  }, 3200);
}
