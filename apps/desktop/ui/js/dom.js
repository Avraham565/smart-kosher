// DOM utilities: escaping, main-area rendering, and event delegation.
// All interactivity goes through data-action/data-change attributes and
// one delegated listener per root — no inline handlers, no globals.

export function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function setMain(html) {
  document.getElementById('app-main').innerHTML = html;
}

export function loadingView() {
  return '<div class="loading">טוען…</div>';
}

export function errorBanner(msg) {
  return `<div class="error-banner">${esc(msg)}</div>`;
}

export function val(id) {
  const el = document.getElementById(id);
  return el ? el.value : '';
}

export function show(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? '' : 'none';
}

export function pad2(n) {
  return String(n).padStart(2, '0');
}

// One registry for the whole app. Views register their handlers once at
// import time; the two delegated listeners below dispatch to them.
const actions = new Map();

export function registerActions(map) {
  for (const [name, fn] of Object.entries(map)) actions.set(name, fn);
}

export function bindDelegation(root) {
  root.addEventListener('click', event => {
    const el = event.target.closest('[data-action]');
    if (!el || el.disabled) return;
    const fn = actions.get(el.dataset.action);
    if (fn) fn(el, event);
  });
  root.addEventListener('change', event => {
    const el = event.target.closest('[data-change]');
    if (!el) return;
    const fn = actions.get(el.dataset.change);
    if (fn) fn(el, event);
  });
  root.addEventListener('submit', event => {
    const el = event.target.closest('[data-submit]');
    if (!el) return;
    event.preventDefault();
    const fn = actions.get(el.dataset.submit);
    if (fn) fn(el, event);
  });
}

// Disables a button for the duration of an async operation.
export function withButtonBusy(button, label) {
  if (!button) return () => {};
  const previousText = button.textContent;
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  if (label) button.textContent = label;
  return () => {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    if (label) button.textContent = previousText;
  };
}
