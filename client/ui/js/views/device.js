// Device page: one big round power button reflecting the live state,
// device details, its schedules, and the next planned action.

import { api } from '../api.js';
import { esc, registerActions, setMain } from '../dom.js';
import { ACTION_LABELS, RECURRENCE_LABELS } from '../labels.js';
import {
  byId, ensureLoaded, radioOf, refreshZigbee, schedulesFor, state, upsert,
} from '../store.js';
import { showToast } from '../toast.js';

export async function openDevicePage(id) {
  state.tab = 'device';
  state.deviceId = id;
  await ensureLoaded(['zones', 'endpoints', 'groups', 'schedules']);
  renderDevicePage();
  refreshZigbee().then(ok => { if (ok && state.tab === 'device') renderDevicePage(); });
  loadNextAction(id);
}

export function renderDevicePage() {
  const ep = byId('endpoints', state.deviceId);
  if (!ep) {
    setMain('<div class="empty">המכשיר לא נמצא</div>');
    return;
  }
  const radio = radioOf(ep);
  const known = radio && typeof radio.on_off === 'boolean';
  const powerCls = !radio ? 'unknown' : radio.unreachable ? 'unreachable'
    : known ? (radio.on_off ? 'is-on' : 'is-off') : 'unknown';
  const stateText = !radio ? 'מצב לא ידוע'
    : radio.unreachable ? 'המכשיר לא מגיב'
    : known ? (radio.on_off ? 'דולק' : 'כבוי') : 'מצב לא ידוע';

  const zone = ep.zone_id ? byId('zones', ep.zone_id) : null;
  const schedules = schedulesFor(ep.id);

  setMain(`
    <div class="page-head">
      <button class="btn-icon back" data-action="show-tab" data-tab="devices" aria-label="חזרה">→</button>
      <h2 class="page-title">${esc(ep.name || ep.id)}</h2>
      <div class="card-actions">
        <button class="btn-icon" data-action="edit-endpoint" data-id="${esc(ep.id)}" aria-label="ערוך מכשיר" title="ערוך מכשיר">✎</button>
        <button class="btn-icon danger" data-action="delete-device-page" data-collection="endpoints" data-id="${esc(ep.id)}" aria-label="מחק מכשיר" title="מחק מכשיר">🗑</button>
      </div>
    </div>

    <div class="power-wrap">
      <button class="power-btn ${powerCls}" data-action="power-flip" data-id="${esc(ep.id)}" aria-label="הדלק/כבה">⏻</button>
      <div class="power-state">${stateText}</div>
    </div>

    <div id="next-action" class="settings-card next-action">
      <h3>הפעולה הבאה</h3>
      <div class="card-sub" id="next-action-body">טוען…</div>
    </div>

    <div class="settings-card">
      <h3>פרטי המכשיר</h3>
      <div class="settings-row"><span class="settings-key">אזור</span><span class="settings-val">${esc(zone ? zone.name : 'ללא אזור')}</span></div>
      <div class="settings-row"><span class="settings-key">כתובת רדיו</span><span class="settings-val" dir="ltr">${esc(ep.ieee_address || 'לא מצומד')}</span></div>
      ${radio ? `
        <div class="settings-row"><span class="settings-key">חיבור</span><span class="settings-val">${radio.unreachable ? '⚠ לא מגיב' : 'מחובר'}</span></div>
        <div class="settings-row"><span class="settings-key">דיווח מצב</span><span class="settings-val">${radio.reporting ? 'פעיל' : 'לא פעיל'}</span></div>
        ${typeof radio.state_age_ms === 'number' ? `<div class="settings-row"><span class="settings-key">עדכון אחרון</span><span class="settings-val">${formatAge(radio.state_age_ms)}</span></div>` : ''}
      ` : ep.ieee_address ? `
        <div class="settings-row"><span class="settings-key">חיבור</span><span class="settings-val">לא נמצא ברשת</span></div>
      ` : ''}
    </div>

    <div class="settings-card">
      <div class="section-row">
        <h3>תזמונים (${schedules.length})</h3>
        <button class="btn-add" data-action="device-toggle-schedules">הצג תזמונים</button>
      </div>
      <div id="device-schedules" class="hidden">
        ${schedules.length ? schedules.map(deviceScheduleRow).join('') : '<div class="empty">אין תזמונים למכשיר זה</div>'}
      </div>
    </div>`);
}

function deviceScheduleRow(sch) {
  const viaGroup = sch.target_type === 'group';
  const groupName = viaGroup ? (byId('groups', sch.target_id) || {}).name : null;
  return `
    <div class="schedule-mini">
      <label class="toggle" title="${sch.enabled ? 'כבה תזמון' : 'הפעל תזמון'}">
        <input type="checkbox" ${sch.enabled ? 'checked' : ''} data-change="toggle-schedule" data-id="${esc(sch.id)}">
        <span class="toggle-slider"></span>
      </label>
      <div class="schedule-mini-copy">
        <span class="card-name">${esc(sch.name || sch.id)}</span>
        <span class="card-sub">
          ${esc(ACTION_LABELS[sch.action_type] || sch.action_type)}
          · ${esc(RECURRENCE_LABELS[sch.recurrence_type] || sch.recurrence_type)}
          ${viaGroup && groupName ? ' · דרך קבוצת ' + esc(groupName) : ''}
        </span>
      </div>
    </div>`;
}

function formatAge(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return 'לפני ' + s + ' שניות';
  const m = Math.round(s / 60);
  if (m < 60) return 'לפני ' + m + ' דקות';
  return 'לפני ' + Math.round(m / 60) + ' שעות';
}

// ── next planned action ────────────────────────────────────────────────

async function loadNextAction(endpointId) {
  const body = document.getElementById('next-action-body');
  if (!body) return;
  const res = await api.get('/api/schedules/upcoming?days=7');
  if (state.deviceId !== endpointId || state.tab !== 'device') return;
  const target = document.getElementById('next-action-body');
  if (!target) return;
  if (!res.ok) {
    target.textContent = res.status === 501
      ? 'תצוגה מקדימה זמינה רק עם אחסון קבוע'
      : 'לא ניתן לחשב: ' + res.error;
    return;
  }
  const groupIds = state.groups
    .filter(g => (g.member_ids || []).includes(endpointId))
    .map(g => g.id);
  const events = (res.data && res.data.events) || [];
  const next = events.find(ev =>
    (ev.target_type === 'endpoint' && ev.target_id === endpointId) ||
    (ev.target_type === 'group' && groupIds.includes(ev.target_id)));
  if (!next) {
    target.textContent = 'אין פעולות מתוכננות בשבוע הקרוב';
    return;
  }
  const sch = byId('schedules', next.schedule_id);
  target.innerHTML = `
    <span class="next-action-line">
      <strong>${esc(ACTION_LABELS[next.action_type] || next.action_type)}</strong>
      ב-${esc(formatEventDay(next.local_date))} בשעה ${esc(next.local_time)}
      ${sch ? '(' + esc(sch.name || sch.id) + ')' : ''}
    </span>`;
}

function formatEventDay(isoDate) {
  const [y, m, d] = isoDate.split('-').map(Number);
  const today = new Date();
  const date = new Date(y, m - 1, d);
  const diffDays = Math.round((date - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000);
  if (diffDays === 0) return 'היום';
  if (diffDays === 1) return 'מחר';
  const days = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'];
  return 'יום ' + days[date.getDay()];
}

// ── actions ────────────────────────────────────────────────────────────

// Repaint only the live parts (button + state line) — a poll must not
// tear down the page (open schedules panel, scroll) under the user.
export async function refreshDeviceLive() {
  if (state.tab !== 'device') return;
  if (!(await refreshZigbee())) return;
  const ep = byId('endpoints', state.deviceId);
  const btn = document.querySelector('.power-btn');
  const stateLine = document.querySelector('.power-state');
  if (!ep || !btn || !stateLine) return;
  const radio = radioOf(ep);
  const known = radio && typeof radio.on_off === 'boolean';
  btn.classList.remove('is-on', 'is-off', 'unknown', 'unreachable');
  btn.classList.add(!radio ? 'unknown' : radio.unreachable ? 'unreachable'
    : known ? (radio.on_off ? 'is-on' : 'is-off') : 'unknown');
  stateLine.textContent = !radio ? 'מצב לא ידוע'
    : radio.unreachable ? 'המכשיר לא מגיב'
    : known ? (radio.on_off ? 'דולק' : 'כבוי') : 'מצב לא ידוע';
}

async function powerFlip(el) {
  // Reuse the list logic (explicit opposite / hub toggle) then repaint.
  const { flipDevice } = await import('./devices.js');
  await flipDevice(el);
  setTimeout(() => {
    refreshDeviceLive();
    loadNextAction(state.deviceId);
  }, 2600);
}

registerActions({
  'open-device': el => openDevicePage(el.dataset.id),
  'power-flip': powerFlip,
  'device-toggle-schedules': el => {
    const panel = document.getElementById('device-schedules');
    panel.classList.toggle('hidden');
    el.textContent = panel.classList.contains('hidden') ? 'הצג תזמונים' : 'הסתר תזמונים';
  },
});
