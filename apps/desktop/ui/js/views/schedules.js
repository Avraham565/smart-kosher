// Schedules tab: list, enable toggle, and the schedule form.

import { api } from '../api.js';
import { esc, pad2, registerActions, setMain, show, val } from '../dom.js';
import {
  ACTION_LABELS, HEBREW_MONTHS, RECURRENCE_LABELS, WEEK_DAYS, ZMAN_LABELS,
} from '../labels.js';
import { closeModal, modalError, openModal } from '../modal.js';
import { byId, ensureLoaded, state, upsert } from '../store.js';
import { showToast } from '../toast.js';

export async function loadSchedules() {
  await ensureLoaded(['endpoints', 'groups', 'schedules']);
  renderSchedules();
}

export function renderSchedules() {
  const addBtn = `<div class="section-row"><span class="section-title">תזמונים</span><button class="btn-add" data-action="add-schedule">+ הוסף</button></div>`;
  if (!state.schedules.length) {
    setMain(addBtn + '<div class="empty">אין תזמונים</div>');
    return;
  }
  const cards = state.schedules.map(sch => `
    <div class="card">
      <div class="card-row">
        <span class="card-name">${esc(sch.name || sch.id)}</span>
        <div class="card-actions">
          <label class="toggle" title="${sch.enabled ? 'כבה תזמון' : 'הפעל תזמון'}">
            <input type="checkbox" ${sch.enabled ? 'checked' : ''} data-change="toggle-schedule" data-id="${esc(sch.id)}">
            <span class="toggle-slider"></span>
          </label>
          <button class="btn-icon" type="button" aria-label="ערוך תזמון" title="ערוך תזמון" data-action="edit-schedule" data-id="${esc(sch.id)}">✎</button>
          <button class="btn-icon danger" type="button" aria-label="מחק תזמון" title="מחק תזמון" data-action="delete-entity" data-collection="schedules" data-id="${esc(sch.id)}">🗑</button>
        </div>
      </div>
      <div class="card-sub">${esc(targetName(sch))} · ${esc(describeTrigger(sch))} · ${esc(RECURRENCE_LABELS[sch.recurrence_type] || sch.recurrence_type)} · ${esc(ACTION_LABELS[sch.action_type] || sch.action_type)}</div>
    </div>`).join('');
  setMain(addBtn + cards);
}

function targetName(sch) {
  const list = sch.target_type === 'endpoint' ? 'endpoints' : 'groups';
  const entity = byId(list, sch.target_id);
  return entity ? (entity.name || entity.id) : sch.target_id;
}

function describeTrigger(sch) {
  const td = sch.trigger_data || {};
  if (sch.trigger_type === 'fixed_time') return pad2(td.h) + ':' + pad2(td.m);
  const zLabel = ZMAN_LABELS[td.zman] || td.zman || '';
  if (sch.trigger_type === 'zman_offset' && td.offset) {
    return zLabel + (td.offset > 0 ? ' +' : ' ') + td.offset + ' דק׳';
  }
  return zLabel;
}

// ── form ───────────────────────────────────────────────────────────────

function scheduleFormHtml(sch) {
  const td = (sch && sch.trigger_data) || {};
  const rd = (sch && sch.recurrence_data) || {};
  const tt = (sch && sch.trigger_type) || 'fixed_time';
  const rt = (sch && sch.recurrence_type) || 'daily';
  const at = (sch && sch.action_type) || 'on';
  const targetType = (sch && sch.target_type) || 'endpoint';
  const targetId = (sch && sch.target_id) || '';

  const targetOpts = (targetType === 'endpoint' ? state.endpoints : state.groups)
    .map(e => `<option value="${esc(e.id)}" ${targetId === e.id ? 'selected' : ''}>${esc(e.name || e.id)}</option>`)
    .join('');

  const zmOpts = Object.entries(ZMAN_LABELS).map(([k, v]) =>
    `<option value="${k}" ${td.zman === k ? 'selected' : ''}>${v}</option>`).join('');

  const recOpts = Object.entries(RECURRENCE_LABELS).map(([k, v]) =>
    `<option value="${k}" ${rt === k ? 'selected' : ''}>${v}</option>`).join('');

  return `
    <form data-submit="submit-schedule" data-id="${sch ? esc(sch.id) : ''}">
      <div class="form-group">
        <label class="form-label">שם התזמון</label>
        <input class="form-control" id="f-sch-name" value="${esc(sch ? sch.name || '' : '')}" placeholder="למשל: אורות שבת">
      </div>

      <div class="form-row">
        <div class="form-group">
          <label class="form-label">סוג יעד</label>
          <select class="form-control" id="f-sch-ttype" data-change="schedule-target-type">
            <option value="endpoint" ${targetType === 'endpoint' ? 'selected' : ''}>מכשיר</option>
            <option value="group" ${targetType === 'group' ? 'selected' : ''}>קבוצה</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">יעד</label>
          <select class="form-control" id="f-sch-tid">${targetOpts}</select>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">טריגר</label>
        <select class="form-control" id="f-sch-trigger" data-change="schedule-trigger">
          <option value="fixed_time" ${tt === 'fixed_time' ? 'selected' : ''}>שעה קבועה</option>
          <option value="zman" ${tt === 'zman' ? 'selected' : ''}>זמן הלכתי</option>
          <option value="zman_offset" ${tt === 'zman_offset' ? 'selected' : ''}>זמן הלכתי עם הקדמה/איחור</option>
        </select>
      </div>

      <div id="f-trigger-fixed" ${tt !== 'fixed_time' ? 'style="display:none"' : ''}>
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

      <div id="f-trigger-zman" ${tt === 'fixed_time' ? 'style="display:none"' : ''}>
        <div class="form-group">
          <label class="form-label">זמן</label>
          <select class="form-control" id="f-sch-zman">${zmOpts}</select>
        </div>
        <div id="f-trigger-offset" ${tt !== 'zman_offset' ? 'style="display:none"' : ''}>
          <div class="form-group">
            <label class="form-label">הקדמה/איחור (דקות, שלילי=הקדמה)</label>
            <input class="form-control" id="f-sch-offset" type="number" value="${td.offset !== undefined ? td.offset : -18}">
          </div>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">חזרה</label>
        <select class="form-control" id="f-sch-rec" data-change="schedule-recurrence">${recOpts}</select>
      </div>

      <div id="f-rec-extra">${recurrenceExtra(rt, rd)}</div>

      <div class="form-group">
        <label class="form-label">פעולה</label>
        <select class="form-control" id="f-sch-action">
          <option value="on" ${at === 'on' ? 'selected' : ''}>הדלק</option>
          <option value="off" ${at === 'off' ? 'selected' : ''}>כבה</option>
        </select>
      </div>

      <div class="form-actions">
        <button class="btn-secondary" type="button" data-action="modal-close">ביטול</button>
        <button class="btn-primary" type="submit">שמור</button>
      </div>
    </form>`;
}

function recurrenceExtra(rt, rd) {
  if (rt === 'days_of_week') {
    const dayBtns = WEEK_DAYS.map(d => {
      const sel = rd.days && rd.days.includes(d.idx) ? 'selected' : '';
      return `<button type="button" class="day-btn ${sel}" data-day="${d.idx}" data-action="toggle-day">${d.label}</button>`;
    }).join('');
    return `<div class="form-group"><label class="form-label">ימים</label><div class="day-picker">${dayBtns}</div></div>`;
  }
  if (rt === 'hebrew_day_of_month') {
    return `<div class="form-group"><label class="form-label">יום בחודש (1–30)</label><input class="form-control" id="f-rec-day" type="number" min="1" max="30" value="${rd.day || 1}"></div>`;
  }
  if (rt === 'hebrew_date') {
    const mOpts = HEBREW_MONTHS.map((m, i) => `<option value="${i + 1}" ${rd.month === i + 1 ? 'selected' : ''}>${m}</option>`).join('');
    return `<div class="form-row"><div class="form-group"><label class="form-label">חודש</label><select class="form-control" id="f-rec-month">${mOpts}</select></div><div class="form-group"><label class="form-label">יום</label><input class="form-control" id="f-rec-day" type="number" min="1" max="30" value="${rd.day || 1}"></div></div>`;
  }
  if (rt === 'gregorian_date') {
    return `<div class="form-row"><div class="form-group"><label class="form-label">חודש (1–12)</label><input class="form-control" id="f-rec-month" type="number" min="1" max="12" value="${rd.month || 1}"></div><div class="form-group"><label class="form-label">יום</label><input class="form-control" id="f-rec-day" type="number" min="1" max="31" value="${rd.day || 1}"></div></div>`;
  }
  if (rt === 'one_time') {
    return `<div class="form-group"><label class="form-label">תאריך</label><input class="form-control" id="f-rec-date" type="date" value="${rd.y ? rd.y + '-' + pad2(rd.m) + '-' + pad2(rd.d) : ''}"></div>`;
  }
  return '';
}

// ── form behaviors ─────────────────────────────────────────────────────

function onTargetTypeChange() {
  const items = val('f-sch-ttype') === 'endpoint' ? state.endpoints : state.groups;
  document.getElementById('f-sch-tid').innerHTML = items
    .map(i => `<option value="${esc(i.id)}">${esc(i.name || i.id)}</option>`)
    .join('');
}

function onTriggerChange() {
  const tt = val('f-sch-trigger');
  show('f-trigger-fixed', tt === 'fixed_time');
  show('f-trigger-zman', tt !== 'fixed_time');
  show('f-trigger-offset', tt === 'zman_offset');
}

function onRecurrenceChange() {
  document.getElementById('f-rec-extra').innerHTML =
    recurrenceExtra(val('f-sch-rec'), {});
}

async function submitSchedule(form) {
  const name = val('f-sch-name');
  if (!name) return modalError('נא להזין שם תזמון');

  const tt = val('f-sch-trigger');
  const rt = val('f-sch-rec');
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
    recurrence_data.days = [...document.querySelectorAll('.day-btn.selected')]
      .map(b => parseInt(b.dataset.day, 10));
    if (!recurrence_data.days.length) return modalError('נא לבחור לפחות יום אחד');
  } else if (rt === 'hebrew_day_of_month') {
    recurrence_data.day = parseInt(val('f-rec-day'), 10);
  } else if (rt === 'hebrew_date' || rt === 'gregorian_date') {
    recurrence_data.month = parseInt(val('f-rec-month'), 10);
    recurrence_data.day = parseInt(val('f-rec-day'), 10);
  } else if (rt === 'one_time') {
    const d = val('f-rec-date');
    if (!d) return modalError('נא לבחור תאריך');
    const [y, m, day] = d.split('-').map(Number);
    recurrence_data.y = y; recurrence_data.m = m; recurrence_data.d = day;
  }

  const id = form.dataset.id;
  const existing = id ? byId('schedules', id) : null;
  const body = {
    name,
    enabled: existing ? (existing.enabled !== false) : true,
    target_type: val('f-sch-ttype'),
    target_id: tid,
    trigger_type: tt,
    trigger_data,
    recurrence_type: rt,
    recurrence_data,
    action_type: val('f-sch-action'),
    action_data: {},
  };

  const res = id
    ? await api.put('/api/schedules/' + id, body)
    : await api.post('/api/schedules', body);
  if (!res.ok) return modalError(res.error);
  upsert('schedules', res.data);
  closeModal();
  renderSchedules();
}

async function toggleSchedule(input) {
  const id = input.dataset.id;
  const enabled = input.checked;
  const res = await api.patch('/api/schedules/' + id + '/enabled', { enabled });
  if (!res.ok) {
    input.checked = !enabled;
    showToast('שגיאה: ' + res.error, 'error');
    return;
  }
  upsert('schedules', res.data);
  showToast(enabled ? 'תזמון הופעל' : 'תזמון כובה', 'success');
}

registerActions({
  'add-schedule': () => openModal('תזמון חדש', scheduleFormHtml(null)),
  'edit-schedule': el => openModal('עריכת תזמון', scheduleFormHtml(byId('schedules', el.dataset.id))),
  'submit-schedule': submitSchedule,
  'toggle-schedule': toggleSchedule,
  'toggle-day': el => el.classList.toggle('selected'),
  'schedule-target-type': onTargetTypeChange,
  'schedule-trigger': onTriggerChange,
  'schedule-recurrence': onRecurrenceChange,
});
