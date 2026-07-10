// Devices tab: a clean list — each device is a row with ONE state button
// that shows and flips its live state; tapping the row opens the device
// page. Zones/groups show aggregate live counts.

import { api } from '../api.js';
import { esc, registerActions, setMain, val, withButtonBusy } from '../dom.js';
import { closeModal, confirmAction, modalError, openModal } from '../modal.js';
import {
  byId, ensureLoaded, radioOf, refreshZigbee, remove, state, upsert,
} from '../store.js';
import { showToast } from '../toast.js';
import { openDevicePage } from './device.js';

export async function loadDevices() {
  await ensureLoaded(['zones', 'endpoints', 'groups']);
  refreshZigbee().then(ok => { if (ok) refreshStateButtons(); });
  renderDevices();
}

export function renderDevices() {
  const subTabs = `
    <div class="sub-tabs">
      <button class="sub-tab-btn ${state.subTab === 'endpoints' ? 'active' : ''}" data-action="sub-tab" data-sub="endpoints">מכשירים</button>
      <button class="sub-tab-btn ${state.subTab === 'groups' ? 'active' : ''}" data-action="sub-tab" data-sub="groups">קבוצות</button>
      <button class="sub-tab-btn ${state.subTab === 'zones' ? 'active' : ''}" data-action="sub-tab" data-sub="zones">אזורים</button>
    </div>`;

  let content;
  if (state.subTab === 'groups') content = groupList();
  else if (state.subTab === 'zones') content = zoneList();
  else content = endpointList();

  setMain(subTabs + content);
}

// ── live-state helpers ─────────────────────────────────────────────────

export function stateButtonHtml(ep, { size = '' } = {}) {
  const radio = radioOf(ep);
  const known = radio && typeof radio.on_off === 'boolean';
  const cls = !radio ? 'unknown' : radio.unreachable ? 'unreachable'
    : known ? (radio.on_off ? 'is-on' : 'is-off') : 'unknown';
  const title = !radio ? 'מצב לא ידוע'
    : radio.unreachable ? 'המכשיר לא מגיב'
    : known ? (radio.on_off ? 'דולק — לחץ לכיבוי' : 'כבוי — לחץ להדלקה')
    : 'מצב לא ידוע — לחץ להחלפה';
  return `<button class="state-btn ${cls} ${size}" data-action="flip-device"
    data-id="${esc(ep.id)}" title="${title}" aria-label="${title}">⏻</button>`;
}

// Patch state buttons in place — no full re-render, so nothing the user
// is interacting with (scroll, open modal) gets torn down by the poll.
export function refreshStateButtons() {
  document.querySelectorAll('.state-btn[data-id]').forEach(btn => {
    const ep = byId('endpoints', btn.dataset.id);
    if (!ep) return;
    const wrap = document.createElement('div');
    wrap.innerHTML = stateButtonHtml(ep, { size: btn.classList.contains('state-btn-big') ? 'state-btn-big' : '' });
    btn.replaceWith(wrap.firstElementChild);
  });
  document.querySelectorAll('[data-live-counts]').forEach(el => {
    const ids = el.dataset.liveCounts.split(',').filter(Boolean);
    el.textContent = liveCountText(ids);
  });
}

function liveCountText(endpointIds) {
  let known = 0, on = 0;
  for (const id of endpointIds) {
    const radio = radioOf(byId('endpoints', id));
    if (radio && typeof radio.on_off === 'boolean') {
      known++;
      if (radio.on_off) on++;
    }
  }
  if (!known) return '';
  return on + ' דולקים מתוך ' + endpointIds.length;
}

// Flip = explicit opposite when the live state is known (deterministic),
// hub-side toggle (read+flip) when it is not.
export async function flipDevice(el) {
  const ep = byId('endpoints', el.dataset.id);
  if (!ep) return;
  const radio = radioOf(ep);
  const action = radio && typeof radio.on_off === 'boolean'
    ? (radio.on_off ? 'off' : 'on')
    : 'toggle';
  const done = withButtonBusy(el);
  try {
    const res = await api.post('/api/control', {
      target_type: 'endpoint', target_id: ep.id, action_type: action,
    });
    if (!res.ok) return showToast('שגיאה: ' + res.error, 'error');
    // The device reports its new state a moment later; refresh then.
    setTimeout(async () => {
      if (await refreshZigbee()) refreshStateButtons();
    }, 2500);
  } finally {
    done();
  }
}

// ── endpoints list ─────────────────────────────────────────────────────

function endpointRow(ep) {
  const radio = radioOf(ep);
  const sub = [];
  if (ep.zone_id) {
    const zone = byId('zones', ep.zone_id);
    if (zone) sub.push(zone.name);
  }
  if (radio && radio.unreachable) sub.push('לא מגיב');
  return `
    <div class="card device-row" id="ep-${esc(ep.id)}">
      <div class="card-row">
        <button class="device-open" data-action="open-device" data-id="${esc(ep.id)}">
          <span class="card-name">${esc(ep.name || ep.id)}</span>
          ${sub.length ? `<span class="card-sub">${esc(sub.join(' · '))}</span>` : ''}
        </button>
        ${stateButtonHtml(ep)}
      </div>
    </div>`;
}

function endpointList() {
  const addBtn = `<div class="section-row"><span class="section-title">מכשירים</span><button class="btn-add" data-action="add-endpoint">+ הוסף</button></div>`;
  if (!state.endpoints.length) return addBtn + '<div class="empty">אין מכשירים רשומים</div>';

  const byZone = {};
  state.endpoints.forEach(ep => {
    const zid = ep.zone_id || '';
    (byZone[zid] = byZone[zid] || []).push(ep);
  });

  let html = addBtn;
  const section = (title, eps) => {
    const ids = eps.map(e => e.id).join(',');
    return `<div class="zone-header">${esc(title)}
        <span class="zone-live" data-live-counts="${ids}">${liveCountText(eps.map(e => e.id))}</span>
      </div>` + eps.map(endpointRow).join('');
  };
  state.zones.forEach(zone => {
    const eps = byZone[zone.id] || [];
    if (eps.length) html += section(zone.name, eps);
  });
  if (byZone['']) html += section('ללא אזור', byZone['']);
  return html;
}

// ── groups ─────────────────────────────────────────────────────────────

function groupList() {
  const addBtn = `<div class="section-row"><span class="section-title">קבוצות</span><button class="btn-add" data-action="add-group">+ הוסף</button></div>`;
  if (!state.groups.length) return addBtn + '<div class="empty">אין קבוצות</div>';

  return addBtn + state.groups.map(grp => {
    const members = grp.member_ids || [];
    const memberNames = members.map(id => {
      const ep = byId('endpoints', id);
      return ep ? (ep.name || ep.id) : id;
    }).join(', ');
    return `
      <div class="card">
        <div class="card-row">
          <span class="card-name">${esc(grp.name || grp.id)}</span>
          <div class="card-actions">
            <button class="btn-ctrl on"  data-action="group-control" data-id="${esc(grp.id)}" data-cmd="on">הדלק</button>
            <button class="btn-ctrl off" data-action="group-control" data-id="${esc(grp.id)}" data-cmd="off">כבה</button>
            <button class="btn-icon" type="button" aria-label="ערוך קבוצה" title="ערוך קבוצה" data-action="edit-group" data-id="${esc(grp.id)}">✎</button>
            <button class="btn-icon danger" type="button" aria-label="מחק קבוצה" title="מחק קבוצה" data-action="delete-entity" data-collection="groups" data-id="${esc(grp.id)}">🗑</button>
          </div>
        </div>
        <div class="card-sub">
          ${members.length} מכשירים${memberNames ? ': ' + esc(memberNames) : ''}
          <span class="zone-live" data-live-counts="${members.join(',')}">${liveCountText(members)}</span>
        </div>
      </div>`;
  }).join('');
}

async function groupControl(el) {
  const done = withButtonBusy(el);
  try {
    const res = await api.post('/api/control', {
      target_type: 'group', target_id: el.dataset.id,
      action_type: el.dataset.cmd,
    });
    if (!res.ok) return showToast('שגיאה: ' + res.error, 'error');
    showToast(el.dataset.cmd === 'on' ? 'הקבוצה הודלקה' : 'הקבוצה כובתה', 'success');
    setTimeout(async () => {
      if (await refreshZigbee()) refreshStateButtons();
    }, 2500);
  } finally {
    done();
  }
}

// ── zones ──────────────────────────────────────────────────────────────

function zoneList() {
  const addBtn = `<div class="section-row"><span class="section-title">אזורים</span><button class="btn-add" data-action="add-zone">+ הוסף</button></div>`;
  if (!state.zones.length) return addBtn + '<div class="empty">אין אזורים</div>';

  return addBtn + state.zones.map(z => {
    const eps = state.endpoints.filter(ep => ep.zone_id === z.id);
    const ids = eps.map(e => e.id);
    return `
    <div class="card">
      <div class="card-row">
        <span class="card-name">${esc(z.name || z.id)}</span>
        <div class="card-actions">
          <button class="btn-icon" type="button" aria-label="ערוך אזור" title="ערוך אזור" data-action="edit-zone" data-id="${esc(z.id)}">✎</button>
          <button class="btn-icon danger" type="button" aria-label="מחק אזור" title="מחק אזור" data-action="delete-entity" data-collection="zones" data-id="${esc(z.id)}">🗑</button>
        </div>
      </div>
      <div class="card-sub">
        ${eps.length} מכשירים
        <span class="zone-live" data-live-counts="${ids.join(',')}">${liveCountText(ids)}</span>
      </div>
    </div>`;
  }).join('');
}

// ── forms (shared with the device page) ────────────────────────────────

function zoneFormHtml(zone) {
  return `
    <form data-submit="submit-zone" data-id="${zone ? esc(zone.id) : ''}">
      <div class="form-group">
        <label class="form-label">שם האזור</label>
        <input class="form-control" id="f-zone-name" value="${esc(zone ? zone.name || '' : '')}" placeholder="למשל: סלון">
      </div>
      <div class="form-actions">
        <button class="btn-secondary" type="button" data-action="modal-close">ביטול</button>
        <button class="btn-primary" type="submit">שמור</button>
      </div>
    </form>`;
}

export function endpointFormHtml(ep) {
  const zoneOpts = state.zones.map(z =>
    `<option value="${esc(z.id)}" ${ep && ep.zone_id === z.id ? 'selected' : ''}>${esc(z.name || z.id)}</option>`
  ).join('');
  return `
    <form data-submit="submit-endpoint" data-id="${ep ? esc(ep.id) : ''}">
      <div class="form-group">
        <label class="form-label">שם המכשיר</label>
        <input class="form-control" id="f-ep-name" value="${esc(ep ? ep.name || '' : '')}" placeholder="למשל: אור תקרה">
      </div>
      <div class="form-group">
        <label class="form-label">אזור</label>
        <select class="form-control" id="f-ep-zone">
          <option value="">ללא אזור</option>
          ${zoneOpts}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">כתובת IEEE (אופציונלי)</label>
        <input class="form-control" id="f-ep-ieee" dir="ltr" value="${esc(ep ? ep.ieee_address || '' : '')}" placeholder="a4:c1:38:...">
      </div>
      <div class="form-group">
        <label class="form-label">Zigbee Endpoint (אופציונלי)</label>
        <input class="form-control" id="f-ep-zigbee" type="number" min="1" max="254" value="${ep && ep.zigbee_endpoint ? ep.zigbee_endpoint : ''}">
      </div>
      <div class="form-actions">
        <button class="btn-secondary" type="button" data-action="modal-close">ביטול</button>
        <button class="btn-primary" type="submit">שמור</button>
      </div>
    </form>`;
}

function groupFormHtml(grp) {
  const memberSet = new Set(grp ? (grp.member_ids || []) : []);
  const checkboxes = state.endpoints.map(ep => `
    <label class="member-row">
      <input type="checkbox" value="${esc(ep.id)}" ${memberSet.has(ep.id) ? 'checked' : ''} class="grp-member">
      ${esc(ep.name || ep.id)}
    </label>`).join('');
  return `
    <form data-submit="submit-group" data-id="${grp ? esc(grp.id) : ''}">
      <div class="form-group">
        <label class="form-label">שם הקבוצה</label>
        <input class="form-control" id="f-grp-name" value="${esc(grp ? grp.name || '' : '')}" placeholder="למשל: כל האורות">
      </div>
      <div class="form-group">
        <label class="form-label">מכשירים</label>
        <div class="member-list">
          ${checkboxes || '<div class="empty">אין מכשירים</div>'}
        </div>
      </div>
      <div class="form-actions">
        <button class="btn-secondary" type="button" data-action="modal-close">ביטול</button>
        <button class="btn-primary" type="submit">שמור</button>
      </div>
    </form>`;
}

// ── submit handlers ────────────────────────────────────────────────────

function rerenderCurrent() {
  if (state.tab === 'device') openDevicePage(state.deviceId);
  else renderDevices();
}

async function submitZone(form) {
  const name = val('f-zone-name');
  if (!name) return modalError('נא להזין שם אזור');
  const id = form.dataset.id;
  const res = id
    ? await api.put('/api/zones/' + id, { name })
    : await api.post('/api/zones', { name });
  if (!res.ok) return modalError(res.error);
  upsert('zones', res.data);
  closeModal();
  rerenderCurrent();
}

async function submitEndpoint(form) {
  const name = val('f-ep-name');
  if (!name) return modalError('נא להזין שם מכשיר');
  const body = { name };
  const zone = val('f-ep-zone');
  if (zone) body.zone_id = zone;
  const ieee = val('f-ep-ieee').trim();
  if (ieee) body.ieee_address = ieee;
  const zigbee = val('f-ep-zigbee');
  if (zigbee) body.zigbee_endpoint = parseInt(zigbee, 10);
  const id = form.dataset.id;
  const res = id
    ? await api.put('/api/endpoints/' + id, body)
    : await api.post('/api/endpoints', body);
  if (!res.ok) return modalError(res.error);
  upsert('endpoints', res.data);
  closeModal();
  rerenderCurrent();
}

async function submitGroup(form) {
  const name = val('f-grp-name');
  if (!name) return modalError('נא להזין שם קבוצה');
  const member_ids = [...document.querySelectorAll('.grp-member:checked')].map(cb => cb.value);
  const id = form.dataset.id;
  const res = id
    ? await api.put('/api/groups/' + id, { name, member_ids })
    : await api.post('/api/groups', { name, member_ids });
  if (!res.ok) return modalError(res.error);
  upsert('groups', res.data);
  closeModal();
  rerenderCurrent();
}

export async function deleteEntity(el, rerender) {
  const collection = el.dataset.collection;
  if (!(await confirmAction('למחוק?'))) return;
  const res = await api.delete('/api/' + collection + '/' + el.dataset.id);
  if (!res.ok) return showToast('שגיאה: ' + res.error, 'error');
  remove(collection, el.dataset.id);
  showToast('נמחק בהצלחה', 'success');
  rerender();
}

registerActions({
  'sub-tab': el => { state.subTab = el.dataset.sub; renderDevices(); },
  'flip-device': flipDevice,
  'group-control': groupControl,
  'add-zone': () => openModal('אזור חדש', zoneFormHtml(null)),
  'edit-zone': el => openModal('עריכת אזור', zoneFormHtml(byId('zones', el.dataset.id))),
  'submit-zone': submitZone,
  'add-endpoint': () => openModal('מכשיר חדש', endpointFormHtml(null)),
  'edit-endpoint': el => openModal('עריכת מכשיר', endpointFormHtml(byId('endpoints', el.dataset.id))),
  'submit-endpoint': submitEndpoint,
  'add-group': () => openModal('קבוצה חדשה', groupFormHtml(null)),
  'edit-group': el => openModal('עריכת קבוצה', groupFormHtml(byId('groups', el.dataset.id))),
  'submit-group': submitGroup,
});
