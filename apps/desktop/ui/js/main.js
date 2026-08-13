// Entry point: tab router, global delegation, header status polling.
//
// Architecture: each view module renders from the shared store and
// registers its data-action handlers at import time; this file only
// routes between tabs and owns the app-level chrome. Data is fetched
// once per collection and patched locally after every mutation — a tab
// with cached data renders instantly, and "loading" appears only on a
// genuinely first load.

import { isConnectionError } from './api.js';
import { bindDelegation, esc, errorBanner, loadingView, registerActions, setMain } from './dom.js';
import { initModal } from './modal.js';
import { refreshZigbee, state } from './store.js';
import {
  deleteEntity, loadDevices, refreshStateButtons, renderDevices,
} from './views/devices.js';
import { refreshDeviceLive } from './views/device.js';
import { loadSchedules, renderSchedules } from './views/schedules.js';
import { loadSettings } from './views/settings.js';
import { loadConnection, updateHeaderStatus } from './views/connection.js';

const TABS = {
  devices: loadDevices,
  schedules: loadSchedules,
  settings: loadSettings,
  connection: loadConnection,
};

function connectionRequiredView(message) {
  return [
    '<section class="notice-card" role="status">',
    '<div class="notice-icon" aria-hidden="true">!</div>',
    '<div class="notice-copy">',
    '<h2>צריך להתחבר למכשיר</h2>',
    `<p>${esc(message || 'המכשיר אינו מחובר')}</p>`,
    '</div>',
    '<button class="btn-primary" type="button" data-action="show-tab" data-tab="connection">למסך חיבור</button>',
    '</section>',
  ].join('');
}

async function showTab(name) {
  state.tab = name;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
  // Cached collections render instantly inside the loader; the spinner
  // shows only when the tab really has nothing to paint yet.
  const hasCache =
    (name === 'devices' && state.loaded.endpoints) ||
    (name === 'schedules' && state.loaded.schedules);
  if (!hasCache) setMain(loadingView());
  try {
    await TABS[name]();
  } catch (e) {
    setMain(isConnectionError(e)
      ? connectionRequiredView(e.message)
      : errorBanner('שגיאת תקשורת: ' + e.message));
  }
}

registerActions({
  'show-tab': el => showTab(el.dataset.tab),
  'delete-entity': el => deleteEntity(
    el, el.dataset.collection === 'schedules' ? renderSchedules : renderDevices),
  // Deleting from the device page navigates back to the list.
  'delete-device-page': el => deleteEntity(el, () => showTab('devices')),
});

// Live-state poll: the hub learns wall-switch presses by push; the UI
// polls the hub's registry only while a state-showing view is open.
async function pollLiveState() {
  if (state.tab === 'devices') {
    if (await refreshZigbee()) refreshStateButtons();
  } else if (state.tab === 'device') {
    await refreshDeviceLive();
  }
}

bindDelegation(document.body);
initModal();
showTab('devices');
updateHeaderStatus();
setInterval(updateHeaderStatus, 5000);
setInterval(pollLiveState, 4000);
