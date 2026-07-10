// Modal dialog + promise-based confirmation.

import { esc, registerActions } from './dom.js';

let confirmResolve = null;

export function openModal(title, bodyHtml) {
  const overlay = document.getElementById('modal-overlay');
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  overlay.classList.remove('hidden');
  requestAnimationFrame(() => {
    const focusable = overlay.querySelector('input, select, textarea, button');
    if (focusable) focusable.focus();
  });
}

export function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  if (confirmResolve) {
    const resolve = confirmResolve;
    confirmResolve = null;
    resolve(false);
  }
}

export function modalError(msg) {
  const existing = document.getElementById('modal-error');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.id = 'modal-error';
  div.className = 'form-error';
  div.textContent = msg;
  document.getElementById('modal-body').prepend(div);
}

export function confirmAction(message) {
  return new Promise(resolve => {
    confirmResolve = resolve;
    openModal('אישור פעולה', [
      `<p class="confirm-text">${esc(message)}</p>`,
      '<div class="form-actions">',
      '<button class="btn-secondary" type="button" data-action="confirm-no">ביטול</button>',
      '<button class="btn-primary danger" type="button" data-action="confirm-yes">אישור</button>',
      '</div>',
    ].join(''));
  });
}

function resolveConfirm(value) {
  const resolve = confirmResolve;
  confirmResolve = null;
  document.getElementById('modal-overlay').classList.add('hidden');
  if (resolve) resolve(value);
}

export function initModal() {
  const overlay = document.getElementById('modal-overlay');
  overlay.addEventListener('click', event => {
    if (event.target === overlay) closeModal();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !overlay.classList.contains('hidden')) {
      closeModal();
    }
  });
}

registerActions({
  'modal-close': () => closeModal(),
  'confirm-no': () => resolveConfirm(false),
  'confirm-yes': () => resolveConfirm(true),
});
