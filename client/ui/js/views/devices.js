// Devices tab: endpoints / groups / zones sub-tabs, forms, and control.

import { api } from '../api.js';
import { esc, registerActions, setMain, val, withButtonBusy } from '../dom.js';
import { ACTION_LABELS } from '../labels.js';
import { closeModal, confirmAction, modalError, openModal } from '../modal.js';
import { byId, ensureLoaded, remove, state, upsert } from '../store.js';
import { showToast } from '../toast.js';

export async function loadDevices() {
  await ensureLoaded(['zones', 'endpoints', 'groups']);
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

// ── list rendering ─────────────────────────────────────────────────────

function controlButtons(targetType, id) {
  return `
    <button class="btn-ctrl on"  data-action="control" data-type="${targetType}" data-id="${esc(id)}" data-cmd="on">הדלק</button>
    <button class="btn-ctrl off" data-action="control" data-type="${targetType}" data-id="${esc(id)}" data-cmd="off">כבה</button>`;
}

function iconButtons(kind, id, editLabel, deleteLabel) {
  return `
    <button class="btn-icon" type="button" aria-label="${editLabel}" title="${editLabel}" data-action="edit-${kind}" data-id="${esc(id)}">✎</button>
    <button class="btn-icon danger" type="button" aria-label="${deleteLabel}" title="${deleteLabel}" data-action="delete-entity" data-collection="${kind}s" data-id="${esc(id)}">🗑</button>`;
}

function endpointCard(ep) {
  return `
    <div class="card" id="ep-${esc(ep.id)}">
      <div class="card-row">
        <span class="card-name">${esc(ep.name || ep.id)}</span>
        <div class="card-actions">
          ${controlButtons('endpoint', ep.id)}
          ${iconButtons('endpoint', ep.id, 'ערוך מכשיר', 'מחק מכשיר')}
        </div>
      </div>
      ${ep.ieee_address ? `<div class="card-sub">${esc(ep.ieee_address)}</div>` : ''}
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
  state.zones.forEach(zone => {
    const eps = byZone[zone.id] || [];
    if (!eps.length) return;
    html += `<div class="zone-header">${esc(zone.name)}</div>`;
    html += eps.map(endpointCard).join('');
  });
  if (byZone['']) {
    html += `<div class="zone-header">ללא אזור</div>`;
    html += byZone[''].map(endpointCard).join('');
  }
  return html;
}

function groupList() {
  const addBtn = `<div class="section-row"><span class="section-title">קבוצות</span><button class="btn-add" data-action="add-group">+ הוסף</button></div>`;
  if (!state.groups.length) return addBtn + '<div class="empty">אין קבוצות</div>';

  return addBtn + state.groups.map(grp => {
    const memberNames = (grp.member_ids || []).map(id => {
      const ep = byId('endpoints', id);
      return ep ? (ep.name || ep.id) : id;
    }).join(', ');
    return `
      <div class="card">
        <div class="card-row">
          <span class="card-name">${esc(grp.name || grp.id)}</span>
          <div class="card-actions">
            ${controlButtons('group', grp.id)}
            ${iconButtons('group', grp.id, 'ערוך קבוצה', 'מחק קבוצה')}
          </div>
        </div>
        ${memberNames ? `<div class="card-sub">${esc(memberNames)}</div>` : ''}
      </div>`;
  }).join('');
}

function zoneList() {
  const addBtn = `<div class="section-row"><span class="section-title">אזורים</span><button class="btn-add" data-action="add-zone">+ הוסף</button></div>`;
  if (!state.zones.length) return addBtn + '<div class="empty">אין אזורים</div>';

  return addBtn + state.zones.map(z => `
    <div class="card">
      <div class="card-row">
        <span class="card-name">${esc(z.name || z.id)}</span>
        <div class="card-actions">
          ${iconButtons('zone', z.id, 'ערוך אזור', 'מחק אזור')}
        </div>
      </div>
    </div>`).join('');
}

// ── forms ──────────────────────────────────────────────────────────────

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

function endpointFormHtml(ep) {
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

// ── submit handlers: patch the store from the response, no refetch ─────

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
  renderDevices();
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
  renderDevices();
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
  renderDevices();
}

// ── control + delete ───────────────────────────────────────────────────

async function sendControl(el) {
  const done = withButtonBusy(el);
  try {
    const res = await api.post('/api/control', {
      target_type: el.dataset.type,
      target_id: el.dataset.id,
      action_type: el.dataset.cmd,
    });
    if (!res.ok) return showToast('שגיאה: ' + res.error, 'error');
    showToast((ACTION_LABELS[el.dataset.cmd] || 'פעולה') + ' נשלחה', 'success');
  } finally {
    done();
  }
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
  'control': sendControl,
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
