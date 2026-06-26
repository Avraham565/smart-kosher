'use strict';

// ─── Constants ────────────────────────────────────────────────────────────────

const ZMAN_LABELS = {
  alot_hashachar:             'עלות השחר',
  talit_and_tefillin:         'טלית ותפילין',
  netz_hachama:               'נץ החמה',
  sof_zman_shema_gra:         'סוף זמן שמע (גר"א)',
  sof_zman_shema_mga:         'סוף זמן שמע (מג"א)',
  sof_zman_tfilla_gra:        'סוף זמן תפילה (גר"א)',
  sof_zman_tfilla_mga:        'סוף זמן תפילה (מג"א)',
  chatzot_hayom:              'חצות היום',
  mincha_gedola:              'מנחה גדולה',
  mincha_gedola_30min:        'מנחה גדולה (30 דק׳)',
  mincha_ketana:              'מנחה קטנה',
  plag_hamincha:              'פלג המנחה',
  shkia:                      'שקיעה',
  tset_hakohavim:             'צאת הכוכבים',
  tset_hakohavim_shabbat:     'צאת הכוכבים (שבת)',
  tset_hakohavim_tsom:        'צאת הכוכבים (תענית)',
  tset_hakohavim_rabeinu_tam: 'צאת הכוכבים (ר"ת)',
  chatzot_halayla:            'חצות הלילה',
  candle_lighting:            'הדלקת נרות',
};

const RECURRENCE_LABELS = {
  daily:                  'יומי',
  days_of_week:           'ימים בשבוע',
  assur_bemelacha:        'שבת ויו"ט',
  erev_assur_bemelacha:   'ערב שבת/יו"ט',
  motzei_assur_bemelacha: 'מוצאי שבת/יו"ט',
  chol_hamoed:            'חול המועד',
  rosh_chodesh:           'ראש חודש',
  hebrew_day_of_month:    'יום בחודש עברי',
  hebrew_date:            'תאריך עברי',
  gregorian_date:         'תאריך לועזי',
  one_time:               'פעם אחת',
};

const ACTION_LABELS = { on: 'הדלק', off: 'כבה' };

// day index 0=Mon…6=Sun, displayed in Hebrew week order
const WEEK_DAYS = [
  { idx: 6, label: 'א׳' },
  { idx: 0, label: 'ב׳' },
  { idx: 1, label: 'ג׳' },
  { idx: 2, label: 'ד׳' },
  { idx: 3, label: 'ה׳' },
  { idx: 4, label: 'ו׳' },
  { idx: 5, label: 'ש׳' },
];

const HEBREW_MONTHS = [
  'ניסן','אייר','סיון','תמוז','אב','אלול',
  'תשרי','חשון','כסלו','טבת','שבט','אדר','אדר ב׳',
];

// ─── API layer ─────────────────────────────────────────────────────────────────

const api = {
  async _request(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    const json = await res.json();
    return json;
  },
  get:    (path)       => api._request('GET',    path),
  post:   (path, body) => api._request('POST',   path, body),
  put:    (path, body) => api._request('PUT',    path, body),
  patch:  (path, body) => api._request('PATCH',  path, body),
  delete: (path)       => api._request('DELETE', path),
};

// ─── App state ────────────────────────────────────────────────────────────────

const state = {
  tab: 'devices',
  subTab: 'endpoints',   // devices sub-tab: endpoints | zones | groups
  zones: [],
  endpoints: [],
  groups: [],
  schedules: [],
  settings: {},
};

// ─── Tab navigation ───────────────────────────────────────────────────────────

function showTab(name) {
  state.tab = name;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
  loadTab(name);
}

async function loadTab(name) {
  setMain('<div class="loading">טוען…</div>');
  try {
    if (name === 'devices') {
      const [z, ep, grp] = await Promise.all([
        api.get('/api/zones'),
        api.get('/api/endpoints'),
        api.get('/api/groups'),
      ]);
      state.zones     = z.data   || [];
      state.endpoints = ep.data  || [];
      state.groups    = grp.data || [];
      renderDevices();
    } else if (name === 'schedules') {
      const [ep, grp, sch] = await Promise.all([
        api.get('/api/endpoints'),
        api.get('/api/groups'),
        api.get('/api/schedules'),
      ]);
      state.endpoints = ep.data  || [];
      state.groups    = grp.data || [];
      state.schedules = sch.data || [];
      renderSchedules();
    } else if (name === 'settings') {
      const res = await api.get('/api/settings');
      state.settings = res.data || {};
      renderSettings();
    }
  } catch (e) {
    setMain(errorBanner('שגיאת תקשורת: ' + e.message));
  }
}

// ─── Render: devices tab ──────────────────────────────────────────────────────

function renderDevices() {
  const subTabs = `
    <div class="sub-tabs">
      <button class="sub-tab-btn ${state.subTab==='endpoints'?'active':''}" onclick="switchSubTab('endpoints')">מכשירים</button>
      <button class="sub-tab-btn ${state.subTab==='groups'?'active':''}" onclick="switchSubTab('groups')">קבוצות</button>
      <button class="sub-tab-btn ${state.subTab==='zones'?'active':''}" onclick="switchSubTab('zones')">אזורים</button>
    </div>`;

  let content = '';
  if (state.subTab === 'endpoints') content = renderEndpointList();
  else if (state.subTab === 'groups') content = renderGroupList();
  else content = renderZoneList();

  setMain(subTabs + content);
}

function switchSubTab(name) {
  state.subTab = name;
  renderDevices();
}

function renderEndpointList() {
  const byZone = {};
  state.endpoints.forEach(ep => {
    const zid = ep.zone_id || '';
    if (!byZone[zid]) byZone[zid] = [];
    byZone[zid].push(ep);
  });

  const addBtn = `<div class="section-row"><span class="section-title">מכשירים</span><button class="btn-add" onclick="openAddEndpoint()">+ הוסף</button></div>`;
  if (!state.endpoints.length) return addBtn + '<div class="empty">אין מכשירים רשומים</div>';

  let html = addBtn;

  const epCard = ep => `
    <div class="card" id="ep-${esc(ep.id)}">
      <div class="card-row">
        <span class="card-name">${esc(ep.name || ep.id)}</span>
        <div class="card-actions">
          <button class="btn-ctrl on"  onclick="sendControl('endpoint','${esc(ep.id)}','on')">הדלק</button>
          <button class="btn-ctrl off" onclick="sendControl('endpoint','${esc(ep.id)}','off')">כבה</button>
          <button class="btn-icon" onclick="openEditEndpoint('${esc(ep.id)}')">✎</button>
          <button class="btn-icon danger" onclick="deleteEntity('endpoints','${esc(ep.id)}')">🗑</button>
        </div>
      </div>
      ${ep.ieee_address ? `<div class="card-sub">${esc(ep.ieee_address)}</div>` : ''}
    </div>`;

  state.zones.forEach(zone => {
    const eps = byZone[zone.id] || [];
    if (!eps.length) return;
    html += `<div class="zone-header">${esc(zone.name)}</div>`;
    eps.forEach(ep => { html += epCard(ep); });
  });

  if (byZone['']) {
    html += `<div class="zone-header">ללא אזור</div>`;
    byZone[''].forEach(ep => { html += epCard(ep); });
  }
  return html;
}

function renderGroupList() {
  const addBtn = `<div class="section-row"><span class="section-title">קבוצות</span><button class="btn-add" onclick="openAddGroup()">+ הוסף</button></div>`;
  if (!state.groups.length) return addBtn + '<div class="empty">אין קבוצות</div>';

  return addBtn + state.groups.map(grp => {
    const memberNames = (grp.member_ids || []).map(id => {
      const ep = state.endpoints.find(e => e.id === id);
      return ep ? (ep.name || ep.id) : id;
    }).join(', ');
    return `
      <div class="card">
        <div class="card-row">
          <span class="card-name">${esc(grp.name || grp.id)}</span>
          <div class="card-actions">
            <button class="btn-ctrl on"  onclick="sendControl('group','${esc(grp.id)}','on')">הדלק</button>
            <button class="btn-ctrl off" onclick="sendControl('group','${esc(grp.id)}','off')">כבה</button>
            <button class="btn-icon" onclick="openEditGroup('${esc(grp.id)}')">✎</button>
            <button class="btn-icon danger" onclick="deleteEntity('groups','${esc(grp.id)}')">🗑</button>
          </div>
        </div>
        ${memberNames ? `<div class="card-sub">${esc(memberNames)}</div>` : ''}
      </div>`;
  }).join('');
}

function renderZoneList() {
  const addBtn = `<div class="section-row"><span class="section-title">אזורים</span><button class="btn-add" onclick="openAddZone()">+ הוסף</button></div>`;
  if (!state.zones.length) return addBtn + '<div class="empty">אין אזורים</div>';

  return addBtn + state.zones.map(z => `
    <div class="card">
      <div class="card-row">
        <span class="card-name">${esc(z.name || z.id)}</span>
        <div class="card-actions">
          <button class="btn-icon" onclick="openEditZone('${esc(z.id)}')">✎</button>
          <button class="btn-icon danger" onclick="deleteEntity('zones','${esc(z.id)}')">🗑</button>
        </div>
      </div>
    </div>`).join('');
}

// ─── Render: schedules tab ────────────────────────────────────────────────────

function renderSchedules() {
  const addBtn = `<div class="section-row"><span class="section-title">תזמונים</span><button class="btn-add" onclick="openAddSchedule()">+ הוסף</button></div>`;
  if (!state.schedules.length) {
    setMain(addBtn + '<div class="empty">אין תזמונים</div>');
    return;
  }
  const cards = state.schedules.map(sch => {
    const targetName = resolveTargetName(sch);
    const trigger    = describeTrigger(sch);
    const recurrence = RECURRENCE_LABELS[sch.recurrence_type] || sch.recurrence_type;
    const action     = ACTION_LABELS[sch.action_type] || sch.action_type;
    return `
      <div class="card">
        <div class="card-row">
          <span class="card-name">${esc(sch.name || sch.id)}</span>
          <div class="card-actions">
            <label class="toggle" title="${sch.enabled ? 'כבה תזמון' : 'הפעל תזמון'}">
              <input type="checkbox" ${sch.enabled ? 'checked' : ''} onchange="toggleSchedule('${esc(sch.id)}', this.checked)">
              <span class="toggle-slider"></span>
            </label>
            <button class="btn-icon" onclick="openEditSchedule('${esc(sch.id)}')">✎</button>
            <button class="btn-icon danger" onclick="deleteEntity('schedules','${esc(sch.id)}')">🗑</button>
          </div>
        </div>
        <div class="card-sub">${esc(targetName)} · ${esc(trigger)} · ${esc(recurrence)} · ${esc(action)}</div>
      </div>`;
  }).join('');
  setMain(addBtn + cards);
}

function resolveTargetName(sch) {
  if (sch.target_type === 'endpoint') {
    const ep = state.endpoints.find(e => e.id === sch.target_id);
    return ep ? (ep.name || ep.id) : sch.target_id;
  }
  const grp = state.groups.find(g => g.id === sch.target_id);
  return grp ? (grp.name || grp.id) : sch.target_id;
}

function describeTrigger(sch) {
  const td = sch.trigger_data || {};
  if (sch.trigger_type === 'fixed_time') {
    return pad2(td.h) + ':' + pad2(td.m);
  }
  const zLabel = ZMAN_LABELS[td.zman] || td.zman || '';
  if (sch.trigger_type === 'zman_offset' && td.offset) {
    return zLabel + (td.offset > 0 ? ' +' : ' ') + td.offset + ' דק׳';
  }
  return zLabel;
}

// ─── Render: settings tab ─────────────────────────────────────────────────────

function renderSettings() {
  const s = state.settings;
  setMain(`
    <div class="settings-card">
      <h3>עיר ומיקום</h3>
      <div class="settings-row"><span class="settings-key">עיר</span><span class="settings-val">${esc(s.city || '—')}</span></div>
      <div class="settings-row"><span class="settings-key">קו רוחב</span><span class="settings-val">${s.lat !== undefined ? s.lat : '—'}</span></div>
      <div class="settings-row"><span class="settings-key">קו אורך</span><span class="settings-val">${s.lon !== undefined ? s.lon : '—'}</span></div>
      <div class="settings-row"><span class="settings-key">היסט UTC</span><span class="settings-val">${s.utc_offset_minutes !== undefined ? s.utc_offset_minutes + ' דק׳' : '—'}</span></div>
      <button class="btn-add" style="margin-top:12px" onclick="openEditCity()">ערוך עיר</button>
    </div>
    <div class="settings-card">
      <h3>שעון המכשיר</h3>
      <div class="settings-row"><span class="settings-key">שעה</span><span class="settings-val">${esc(s.device_time || '—')}</span></div>
    </div>
    <div class="settings-card">
      <h3>הגדרות שבת</h3>
      <div class="settings-row"><span class="settings-key">הדלקת נרות לפני שקיעה</span><span class="settings-val">${s.candle_offset !== undefined ? s.candle_offset + ' דק׳' : '—'}</span></div>
      <div class="settings-row"><span class="settings-key">צאת שבת</span><span class="settings-val">${s.tzais_offset !== undefined ? s.tzais_offset + ' דק׳' : '—'}</span></div>
      <button class="btn-add" style="margin-top:12px" onclick="openEditShabbatSettings()">ערוך</button>
    </div>`);
}

// ─── Modal helpers ────────────────────────────────────────────────────────────

function openModal(title, bodyHtml) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-overlay')) return;
  document.getElementById('modal-overlay').classList.add('hidden');
}

function modalError(msg) {
  const existing = document.getElementById('modal-error');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.id = 'modal-error';
  div.className = 'form-error';
  div.textContent = msg;
  document.getElementById('modal-body').prepend(div);
}

// ─── Zone forms ───────────────────────────────────────────────────────────────

function zoneFormHtml(zone) {
  return `
    <div class="form-group">
      <label class="form-label">שם האזור</label>
      <input class="form-control" id="f-zone-name" value="${esc(zone ? zone.name || '' : '')}" placeholder="למשל: סלון">
    </div>
    <div class="form-actions">
      <button class="btn-secondary" onclick="closeModal()">ביטול</button>
      <button class="btn-primary" onclick="submitZone(${zone ? `'${esc(zone.id)}'` : 'null'})">שמור</button>
    </div>`;
}

function openAddZone()        { openModal('אזור חדש', zoneFormHtml(null)); }
function openEditZone(zoneId) {
  const zone = state.zones.find(z => z.id === zoneId);
  openModal('עריכת אזור', zoneFormHtml(zone));
}

async function submitZone(id) {
  const name = val('f-zone-name');
  if (!name) return modalError('נא להזין שם אזור');
  const body = { name };
  const res = id
    ? await api.put('/api/zones/' + id, body)
    : await api.post('/api/zones', body);
  if (!res.ok) return modalError(res.error);
  closeModal();
  await loadTab('devices');
}

// ─── Endpoint forms ───────────────────────────────────────────────────────────

function endpointFormHtml(ep) {
  const zoneOpts = state.zones.map(z =>
    `<option value="${esc(z.id)}" ${ep && ep.zone_id===z.id?'selected':''}>${esc(z.name || z.id)}</option>`
  ).join('');
  return `
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
      <input class="form-control" id="f-ep-ieee" value="${esc(ep ? ep.ieee_address || '' : '')}" placeholder="0x00158d0001234567">
    </div>
    <div class="form-group">
      <label class="form-label">Zigbee Endpoint (אופציונלי)</label>
      <input class="form-control" id="f-ep-zigbee" type="number" min="1" max="254" value="${ep && ep.zigbee_endpoint ? ep.zigbee_endpoint : ''}">
    </div>
    <div class="form-actions">
      <button class="btn-secondary" onclick="closeModal()">ביטול</button>
      <button class="btn-primary" onclick="submitEndpoint(${ep ? `'${esc(ep.id)}'` : 'null'})">שמור</button>
    </div>`;
}

function openAddEndpoint()         { openModal('מכשיר חדש', endpointFormHtml(null)); }
function openEditEndpoint(epId)    {
  const ep = state.endpoints.find(e => e.id === epId);
  openModal('עריכת מכשיר', endpointFormHtml(ep));
}

async function submitEndpoint(id) {
  const name = val('f-ep-name');
  if (!name) return modalError('נא להזין שם מכשיר');
  const body = { name };
  const zone = val('f-ep-zone');
  if (zone) body.zone_id = zone;
  const ieee = val('f-ep-ieee');
  if (ieee) body.ieee_address = ieee;
  const zigbee = val('f-ep-zigbee');
  if (zigbee) body.zigbee_endpoint = parseInt(zigbee, 10);
  const res = id
    ? await api.put('/api/endpoints/' + id, body)
    : await api.post('/api/endpoints', body);
  if (!res.ok) return modalError(res.error);
  closeModal();
  await loadTab('devices');
}

// ─── Group forms ──────────────────────────────────────────────────────────────

function groupFormHtml(grp) {
  const memberSet = new Set(grp ? (grp.member_ids || []) : []);
  const checkboxes = state.endpoints.map(ep => `
    <label style="display:flex;align-items:center;gap:8px;padding:5px 0">
      <input type="checkbox" value="${esc(ep.id)}" ${memberSet.has(ep.id) ? 'checked' : ''} class="grp-member">
      ${esc(ep.name || ep.id)}
    </label>`).join('');
  return `
    <div class="form-group">
      <label class="form-label">שם הקבוצה</label>
      <input class="form-control" id="f-grp-name" value="${esc(grp ? grp.name || '' : '')}" placeholder="למשל: כל האורות">
    </div>
    <div class="form-group">
      <label class="form-label">מכשירים</label>
      <div style="max-height:200px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:8px;padding:8px">
        ${checkboxes || '<div class="empty">אין מכשירים</div>'}
      </div>
    </div>
    <div class="form-actions">
      <button class="btn-secondary" onclick="closeModal()">ביטול</button>
      <button class="btn-primary" onclick="submitGroup(${grp ? `'${esc(grp.id)}'` : 'null'})">שמור</button>
    </div>`;
}

function openAddGroup()         { openModal('קבוצה חדשה', groupFormHtml(null)); }
function openEditGroup(grpId)   {
  const grp = state.groups.find(g => g.id === grpId);
  openModal('עריכת קבוצה', groupFormHtml(grp));
}

async function submitGroup(id) {
  const name = val('f-grp-name');
  if (!name) return modalError('נא להזין שם קבוצה');
  const member_ids = [...document.querySelectorAll('.grp-member:checked')].map(cb => cb.value);
  const body = { name, member_ids };
  const res = id
    ? await api.put('/api/groups/' + id, body)
    : await api.post('/api/groups', body);
  if (!res.ok) return modalError(res.error);
  closeModal();
  await loadTab('devices');
}

// ─── Schedule forms ───────────────────────────────────────────────────────────

function scheduleFormHtml(sch) {
  const td  = (sch && sch.trigger_data)    || {};
  const rd  = (sch && sch.recurrence_data) || {};
  const tt  = (sch && sch.trigger_type)    || 'fixed_time';
  const rt  = (sch && sch.recurrence_type) || 'daily';
  const at  = (sch && sch.action_type)     || 'on';
  const targetType = (sch && sch.target_type) || 'endpoint';
  const targetId   = (sch && sch.target_id)   || '';

  const epOpts  = state.endpoints.map(e => `<option value="${esc(e.id)}" ${targetId===e.id?'selected':''}>${esc(e.name || e.id)}</option>`).join('');
  const grpOpts = state.groups.map(g    => `<option value="${esc(g.id)}" ${targetId===g.id?'selected':''}>${esc(g.name || g.id)}</option>`).join('');

  const zmOpts = Object.entries(ZMAN_LABELS).map(([k, v]) =>
    `<option value="${k}" ${td.zman===k?'selected':''}>${v}</option>`).join('');

  const recOpts = Object.entries(RECURRENCE_LABELS).map(([k, v]) =>
    `<option value="${k}" ${rt===k?'selected':''}>${v}</option>`).join('');

  const dayBtns = WEEK_DAYS.map(d => {
    const sel = rd.days && rd.days.includes(d.idx) ? 'selected' : '';
    return `<button type="button" class="day-btn ${sel}" data-day="${d.idx}" onclick="toggleDay(this)">${d.label}</button>`;
  }).join('');

  return `
    <div class="form-group">
      <label class="form-label">שם התזמון</label>
      <input class="form-control" id="f-sch-name" value="${esc(sch ? sch.name || '' : '')}" placeholder="למשל: אורות שבת">
    </div>

    <div class="form-row">
      <div class="form-group">
        <label class="form-label">סוג יעד</label>
        <select class="form-control" id="f-sch-ttype" onchange="onTargetTypeChange()">
          <option value="endpoint" ${targetType==='endpoint'?'selected':''}>מכשיר</option>
          <option value="group"    ${targetType==='group'   ?'selected':''}>קבוצה</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">יעד</label>
        <select class="form-control" id="f-sch-tid">
          ${targetType === 'endpoint' ? epOpts : grpOpts}
        </select>
      </div>
    </div>

    <div class="form-group">
      <label class="form-label">טריגר</label>
      <select class="form-control" id="f-sch-trigger" onchange="onTriggerChange()">
        <option value="fixed_time"  ${tt==='fixed_time' ?'selected':''}>שעה קבועה</option>
        <option value="zman"        ${tt==='zman'       ?'selected':''}>זמן הלכתי</option>
        <option value="zman_offset" ${tt==='zman_offset'?'selected':''}>זמן הלכתי עם הקדמה/איחור</option>
      </select>
    </div>

    <div id="f-trigger-fixed" ${tt!=='fixed_time'?'style="display:none"':''}>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">שעה</label>
          <input class="form-control" id="f-sch-h" type="number" min="0" max="23" value="${td.h !== undefined ? td.h : 18}">
        </div>
        <div class="form-group">
          <label class="form-label">דקות</label>
          <input class="form-control" id="f-sch-m" type="number" min="0" max="59" value="${td.m !== undefined ? td.m : 0}">
        </div>
      </div>
    </div>

    <div id="f-trigger-zman" ${tt==='fixed_time'?'style="display:none"':''}>
      <div class="form-group">
        <label class="form-label">זמן</label>
        <select class="form-control" id="f-sch-zman">${zmOpts}</select>
      </div>
      <div id="f-trigger-offset" ${tt!=='zman_offset'?'style="display:none"':''}>
        <div class="form-group">
          <label class="form-label">הקדמה/איחור (דקות, שלילי=הקדמה)</label>
          <input class="form-control" id="f-sch-offset" type="number" value="${td.offset !== undefined ? td.offset : -18}">
        </div>
      </div>
    </div>

    <div class="form-group">
      <label class="form-label">חזרה</label>
      <select class="form-control" id="f-sch-rec" onchange="onRecurrenceChange()">
        ${recOpts}
      </select>
    </div>

    <div id="f-rec-extra">
      ${buildRecurrenceExtra(rt, rd, dayBtns)}
    </div>

    <div class="form-group">
      <label class="form-label">פעולה</label>
      <select class="form-control" id="f-sch-action">
        <option value="on"     ${at==='on'    ?'selected':''}>הדלק</option>
        <option value="off"    ${at==='off'   ?'selected':''}>כבה</option>
        <option value="toggle" ${at==='toggle'?'selected':''}>החלף</option>
      </select>
    </div>

    <div class="form-actions">
      <button class="btn-secondary" onclick="closeModal()">ביטול</button>
      <button class="btn-primary" onclick="submitSchedule(${sch ? `'${esc(sch.id)}'` : 'null'})">שמור</button>
    </div>`;
}

function buildRecurrenceExtra(rt, rd, dayBtns) {
  if (rt === 'days_of_week') return `<div class="form-group"><label class="form-label">ימים</label><div class="day-picker">${dayBtns}</div></div>`;
  if (rt === 'hebrew_day_of_month') return `<div class="form-group"><label class="form-label">יום בחודש (1–30)</label><input class="form-control" id="f-rec-day" type="number" min="1" max="30" value="${rd.day || 1}"></div>`;
  if (rt === 'hebrew_date') {
    const mOpts = HEBREW_MONTHS.map((m, i) => `<option value="${i+1}" ${rd.month===i+1?'selected':''}>${m}</option>`).join('');
    return `<div class="form-row"><div class="form-group"><label class="form-label">חודש</label><select class="form-control" id="f-rec-month">${mOpts}</select></div><div class="form-group"><label class="form-label">יום</label><input class="form-control" id="f-rec-day" type="number" min="1" max="30" value="${rd.day || 1}"></div></div>`;
  }
  if (rt === 'gregorian_date') return `<div class="form-row"><div class="form-group"><label class="form-label">חודש (1–12)</label><input class="form-control" id="f-rec-month" type="number" min="1" max="12" value="${rd.month || 1}"></div><div class="form-group"><label class="form-label">יום</label><input class="form-control" id="f-rec-day" type="number" min="1" max="31" value="${rd.day || 1}"></div></div>`;
  if (rt === 'one_time') return `<div class="form-group"><label class="form-label">תאריך</label><input class="form-control" id="f-rec-date" type="date" value="${rd.y ? rd.y+'-'+pad2(rd.m)+'-'+pad2(rd.d) : ''}"></div>`;
  return '';
}

function toggleDay(btn) { btn.classList.toggle('selected'); }

function onTargetTypeChange() {
  const ttype = val('f-sch-ttype');
  const sel   = document.getElementById('f-sch-tid');
  const items = ttype === 'endpoint' ? state.endpoints : state.groups;
  sel.innerHTML = items.map(i => `<option value="${esc(i.id)}">${esc(i.name || i.id)}</option>`).join('');
}

function onTriggerChange() {
  const tt = val('f-sch-trigger');
  show('f-trigger-fixed',  tt === 'fixed_time');
  show('f-trigger-zman',   tt !== 'fixed_time');
  show('f-trigger-offset', tt === 'zman_offset');
}

function onRecurrenceChange() {
  const rt      = val('f-sch-rec');
  const rd      = {};
  const dayBtns = WEEK_DAYS.map(d => `<button type="button" class="day-btn" data-day="${d.idx}" onclick="toggleDay(this)">${d.label}</button>`).join('');
  document.getElementById('f-rec-extra').innerHTML = buildRecurrenceExtra(rt, rd, dayBtns);
}

function openAddSchedule()         { openModal('תזמון חדש', scheduleFormHtml(null)); }
function openEditSchedule(schId)   {
  const sch = state.schedules.find(s => s.id === schId);
  openModal('עריכת תזמון', scheduleFormHtml(sch));
}

async function submitSchedule(id) {
  const name = val('f-sch-name');
  if (!name) return modalError('נא להזין שם תזמון');

  const tt  = val('f-sch-trigger');
  const rt  = val('f-sch-rec');
  const at  = val('f-sch-action');
  const tid = val('f-sch-tid');
  if (!tid) return modalError('נא לבחור יעד');

  const trigger_data = {};
  if (tt === 'fixed_time') {
    trigger_data.h = parseInt(val('f-sch-h'), 10);
    trigger_data.m = parseInt(val('f-sch-m'), 10);
  } else {
    trigger_data.zman = val('f-sch-zman');
    if (tt === 'zman_offset') trigger_data.offset = parseInt(val('f-sch-offset'), 10);
  }

  const recurrence_data = {};
  if (rt === 'days_of_week') {
    recurrence_data.days = [...document.querySelectorAll('.day-btn.selected')].map(b => parseInt(b.dataset.day, 10));
    if (!recurrence_data.days.length) return modalError('נא לבחור לפחות יום אחד');
  } else if (rt === 'hebrew_day_of_month') {
    recurrence_data.day = parseInt(val('f-rec-day'), 10);
  } else if (rt === 'hebrew_date') {
    recurrence_data.month = parseInt(val('f-rec-month'), 10);
    recurrence_data.day   = parseInt(val('f-rec-day'), 10);
  } else if (rt === 'gregorian_date') {
    recurrence_data.month = parseInt(val('f-rec-month'), 10);
    recurrence_data.day   = parseInt(val('f-rec-day'), 10);
  } else if (rt === 'one_time') {
    const d = val('f-rec-date');
    if (!d) return modalError('נא לבחור תאריך');
    const [y, m, day] = d.split('-').map(Number);
    recurrence_data.y = y; recurrence_data.m = m; recurrence_data.d = day;
  }

  const existing = id ? state.schedules.find(s => s.id === id) : null;
  const body = {
    name,
    enabled: existing ? (existing.enabled !== false) : true,
    target_type: val('f-sch-ttype'),
    target_id: tid,
    trigger_type: tt,
    trigger_data,
    recurrence_type: rt,
    recurrence_data,
    action_type: at,
    action_data: {},
  };

  const res = id
    ? await api.put('/api/schedules/' + id, body)
    : await api.post('/api/schedules', body);
  if (!res.ok) return modalError(res.error);
  closeModal();
  await loadTab('schedules');
}

// ─── Settings forms ───────────────────────────────────────────────────────────

function openEditCity() {
  const s = state.settings;
  openModal('עיר ומיקום', `
    <div class="form-group">
      <label class="form-label">שם העיר</label>
      <input class="form-control" id="f-city-name" value="${esc(s.city || '')}">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">קו רוחב</label>
        <input class="form-control" id="f-city-lat" type="number" step="0.0001" value="${s.lat !== undefined ? s.lat : ''}">
      </div>
      <div class="form-group">
        <label class="form-label">קו אורך</label>
        <input class="form-control" id="f-city-lon" type="number" step="0.0001" value="${s.lon !== undefined ? s.lon : ''}">
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">היסט UTC (דקות)</label>
      <input class="form-control" id="f-city-utc" type="number" value="${s.utc_offset_minutes !== undefined ? s.utc_offset_minutes : 120}">
    </div>
    <div class="form-actions">
      <button class="btn-secondary" onclick="closeModal()">ביטול</button>
      <button class="btn-primary" onclick="submitCity()">שמור</button>
    </div>`);
}

async function submitCity() {
  const city = val('f-city-name');
  const lat  = parseFloat(val('f-city-lat'));
  const lon  = parseFloat(val('f-city-lon'));
  const utc  = parseInt(val('f-city-utc'), 10);
  if (!city) return modalError('נא להזין שם עיר');
  if (isNaN(lat) || isNaN(lon)) return modalError('קו רוחב ואורך חייבים להיות מספרים');
  const res = await api.put('/api/settings', { city, lat, lon, utc_offset_minutes: utc });
  if (!res.ok) return modalError(res.error);
  closeModal();
  await loadTab('settings');
}

function openEditShabbatSettings() {
  const s = state.settings;
  openModal('הגדרות שבת', `
    <div class="form-group">
      <label class="form-label">הדלקת נרות לפני שקיעה (דקות)</label>
      <input class="form-control" id="f-candle" type="number" value="${s.candle_offset !== undefined ? s.candle_offset : 18}">
    </div>
    <div class="form-group">
      <label class="form-label">צאת שבת אחרי שקיעה (דקות)</label>
      <input class="form-control" id="f-tzais" type="number" value="${s.tzais_offset !== undefined ? s.tzais_offset : 40}">
    </div>
    <div class="form-actions">
      <button class="btn-secondary" onclick="closeModal()">ביטול</button>
      <button class="btn-primary" onclick="submitShabbatSettings()">שמור</button>
    </div>`);
}

async function submitShabbatSettings() {
  const candle = parseInt(val('f-candle'), 10);
  const tzais  = parseInt(val('f-tzais'),  10);
  if (isNaN(candle) || isNaN(tzais)) return modalError('נא להזין מספרים תקינים');
  const res = await api.put('/api/settings', { candle_offset: candle, tzais_offset: tzais });
  if (!res.ok) return modalError(res.error);
  closeModal();
  await loadTab('settings');
}

// ─── Control + toggle ─────────────────────────────────────────────────────────

async function sendControl(targetType, targetId, actionType) {
  const res = await api.post('/api/control', { target_type: targetType, target_id: targetId, action_type: actionType });
  if (!res.ok) alert('שגיאה: ' + res.error);
}

async function toggleSchedule(schId, enabled) {
  const res = await api.patch('/api/schedules/' + schId + '/enabled', { enabled });
  if (!res.ok) {
    alert('שגיאה: ' + res.error);
    await loadTab('schedules');
  } else {
    const sch = state.schedules.find(s => s.id === schId);
    if (sch) sch.enabled = enabled;
  }
}

async function deleteEntity(type, id) {
  if (!confirm('למחוק?')) return;
  const res = await api.delete('/api/' + type + '/' + id);
  if (!res.ok) return alert('שגיאה: ' + res.error);
  await loadTab(state.tab);
}

// ─── Utility ──────────────────────────────────────────────────────────────────

function setMain(html)  { document.getElementById('app-main').innerHTML = html; }
function errorBanner(m) { return `<div class="error-banner">${esc(m)}</div>`; }
function val(id)        { const el = document.getElementById(id); return el ? el.value : ''; }
function pad2(n)        { return String(n).padStart(2, '0'); }
function show(id, vis)  { const el = document.getElementById(id); if (el) el.style.display = vis ? '' : 'none'; }

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── Init ─────────────────────────────────────────────────────────────────────

showTab('devices');
