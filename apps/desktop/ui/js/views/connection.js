// Connection tab: bridge status, USB/network connect, WiFi provisioning,
// clock sync, and reboot — all desktop-bridge endpoints (/bridge/*).

import { api, ensureOk } from '../api.js';
import { errorBanner, esc, registerActions, setMain, val, withButtonBusy } from '../dom.js';
import { closeModal, confirmAction, modalError, openModal } from '../modal.js';
import { invalidate } from '../store.js';
import { showToast } from '../toast.js';

export async function loadConnection() {
  const [statusRes, portsRes] = await Promise.all([
    api.get('/bridge/status'),
    api.get('/bridge/ports'),
  ]);
  const st = ensureOk(statusRes).data || {};
  const ports = ensureOk(portsRes).data || [];

  const stateLine = st.connected
    ? (st.mode === 'serial'
        ? `מחובר בכבל USB (${esc(st.port)})`
        : `מחובר דרך הרשת (${esc(st.host)})`)
    : 'המכשיר אינו מחובר';

  setMain(`
    <div class="settings-card">
      <h3>מצב חיבור</h3>
      <div class="settings-row"><span class="settings-key">מצב</span><span class="settings-val">${stateLine}</span></div>
      <div class="settings-row"><span class="settings-key">USB זמין</span><span class="settings-val">${ports.length ? esc(ports.join(', ')) : 'לא נמצא'}</span></div>
      <div class="form-actions">
        <button class="btn-secondary" data-action="connect-serial">התחבר ב-USB</button>
        <button class="btn-secondary" data-action="open-connect-network">התחבר דרך הרשת…</button>
      </div>
    </div>

    <div class="settings-card">
      <h3>הגדרת רשת ביתית (בחיבור USB)</h3>
      <div class="form-group">
        <label class="form-label">שם הרשת (SSID)</label>
        <input class="form-control" id="f-wifi-ssid" dir="ltr">
      </div>
      <div class="form-group">
        <label class="form-label">סיסמה</label>
        <input class="form-control" id="f-wifi-pass" type="password" dir="ltr">
      </div>
      <div class="form-actions">
        <button class="btn-primary" data-action="submit-provision">שמור ואתחל</button>
      </div>
      <div id="provision-msg"></div>
    </div>

    <div class="settings-card">
      <h3>שעון המכשיר</h3>
      <p class="card-sub">מסנכרן את שעון המכשיר לפי שעון המחשב (נשלח כ-UTC).</p>
      <div class="form-actions">
        <button class="btn-primary" data-action="sync-time">סנכרן שעון</button>
        <button class="btn-secondary" data-action="reboot-device">אתחול המכשיר</button>
      </div>
      <div id="time-msg"></div>
    </div>`);
}

export async function updateHeaderStatus() {
  const el = document.getElementById('header-status');
  try {
    const res = await api.get('/bridge/status');
    if (!res.ok) {
      el.textContent = 'לא מחובר';
      el.classList.remove('connected');
      el.classList.add('disconnected');
      return;
    }
    const st = res.data || {};
    el.classList.toggle('connected', !!st.connected);
    el.classList.toggle('disconnected', !st.connected);
    if (!st.connected) { el.textContent = '⚠ לא מחובר'; return; }
    el.textContent = st.mode === 'serial' ? '🔌 USB' : '📶 רשת';
  } catch (e) {
    el.textContent = '';
  }
}

function afterLinkChange() {
  // A different hub may answer on the new link — cached lists are stale.
  invalidate('zones', 'endpoints', 'groups', 'schedules');
  loadConnection();
  updateHeaderStatus();
}

async function connectSerial(button) {
  const done = withButtonBusy(button);
  try {
    const res = await api.post('/bridge/connect', { mode: 'serial' });
    if (!res.ok) return showToast('שגיאה: ' + res.error, 'error');
    showToast('חיבור USB פעיל', 'success');
    afterLinkChange();
  } finally {
    done();
  }
}

function openConnectNetwork() {
  openModal('חיבור דרך הרשת', `
    <form data-submit="submit-connect-network">
      <div class="form-group">
        <label class="form-label">כתובת המכשיר ברשת (IP)</label>
        <input class="form-control" id="f-net-host" dir="ltr" placeholder="192.168.1.50">
      </div>
      <div class="form-actions">
        <button class="btn-secondary" type="button" data-action="modal-close">ביטול</button>
        <button class="btn-primary" type="submit">התחבר</button>
      </div>
    </form>`);
}

async function submitConnectNetwork() {
  const host = val('f-net-host').trim();
  if (!host) return modalError('נא להזין כתובת');
  const res = await api.post('/bridge/connect', { mode: 'network', host });
  if (!res.ok) return modalError(res.error);
  closeModal();
  afterLinkChange();
}

async function submitProvision(button) {
  const msg = document.getElementById('provision-msg');
  const done = withButtonBusy(button);
  try {
    const res = await api.post('/bridge/provision', {
      ssid: val('f-wifi-ssid').trim(),
      password: val('f-wifi-pass'),
    });
    if (!res.ok) { msg.innerHTML = errorBanner(res.error); return; }
    msg.innerHTML = '<div class="card-sub">נשמר. המכשיר מאותחל ומצטרף לרשת...</div>';
    showToast('הגדרות Wi-Fi נשלחו', 'success');
    await api.post('/bridge/reboot', {});
    setTimeout(afterLinkChange, 8000);
  } finally {
    done();
  }
}

async function syncTime(button) {
  const msg = document.getElementById('time-msg');
  const done = withButtonBusy(button);
  try {
    const res = await api.post('/bridge/time_sync', {});
    msg.innerHTML = res.ok
      ? `<div class="card-sub">השעון כוון: ${esc(res.data.device_time)} (UTC)</div>`
      : errorBanner(res.error);
    if (res.ok) showToast('השעון סונכרן', 'success');
  } finally {
    done();
  }
}

async function rebootDevice(button) {
  if (!(await confirmAction('לאתחל את המכשיר?'))) return;
  const done = withButtonBusy(button);
  try {
    const res = await api.post('/bridge/reboot', {});
    if (!res.ok) return showToast('שגיאה: ' + res.error, 'error');
    showToast('המכשיר מתאתחל', 'success');
    setTimeout(afterLinkChange, 8000);
  } finally {
    done();
  }
}

registerActions({
  'connect-serial': connectSerial,
  'open-connect-network': openConnectNetwork,
  'submit-connect-network': submitConnectNetwork,
  'submit-provision': submitProvision,
  'sync-time': syncTime,
  'reboot-device': rebootDevice,
});
