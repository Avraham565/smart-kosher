// Settings tab: city/location, device clock display, Shabbat offsets.

import { api, ensureOk } from '../api.js';
import { esc, registerActions, setMain, val } from '../dom.js';
import { closeModal, modalError, openModal } from '../modal.js';
import { state } from '../store.js';

export async function loadSettings() {
  const res = ensureOk(await api.get('/api/settings'));
  state.settings = res.data || {};
  renderSettings();
}

export function renderSettings() {
  const s = state.settings;
  setMain(`
    <div class="settings-card">
      <h3>עיר ומיקום</h3>
      <div class="settings-row"><span class="settings-key">עיר</span><span class="settings-val">${esc(s.city || '—')}</span></div>
      <div class="settings-row"><span class="settings-key">קו רוחב</span><span class="settings-val">${s.lat !== undefined ? s.lat : '—'}</span></div>
      <div class="settings-row"><span class="settings-key">קו אורך</span><span class="settings-val">${s.lon !== undefined ? s.lon : '—'}</span></div>
      <div class="settings-row"><span class="settings-key">היסט UTC</span><span class="settings-val">${s.utc_offset_minutes !== undefined ? s.utc_offset_minutes + ' דק׳' : '—'}</span></div>
      <button class="btn-add settings-edit" data-action="edit-city">ערוך עיר</button>
    </div>
    <div class="settings-card">
      <h3>שעון המכשיר</h3>
      <div class="settings-row"><span class="settings-key">שעה</span><span class="settings-val">${esc(s.device_time || '—')}</span></div>
    </div>
    <div class="settings-card">
      <h3>הגדרות שבת</h3>
      <div class="settings-row"><span class="settings-key">הדלקת נרות לפני שקיעה</span><span class="settings-val">${s.candle_offset !== undefined ? s.candle_offset + ' דק׳' : '—'}</span></div>
      <div class="settings-row"><span class="settings-key">צאת שבת</span><span class="settings-val">${s.tzais_offset !== undefined ? s.tzais_offset + ' דק׳' : '—'}</span></div>
      <button class="btn-add settings-edit" data-action="edit-shabbat">ערוך</button>
    </div>`);
}

function cityFormHtml() {
  const s = state.settings;
  return `
    <form data-submit="submit-city">
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
        <button class="btn-secondary" type="button" data-action="modal-close">ביטול</button>
        <button class="btn-primary" type="submit">שמור</button>
      </div>
    </form>`;
}

async function submitCity() {
  const city = val('f-city-name');
  const lat = parseFloat(val('f-city-lat'));
  const lon = parseFloat(val('f-city-lon'));
  const utc = parseInt(val('f-city-utc'), 10);
  if (!city) return modalError('נא להזין שם עיר');
  if (isNaN(lat) || isNaN(lon)) return modalError('קו רוחב ואורך חייבים להיות מספרים');
  const res = await api.put('/api/settings', { city, lat, lon, utc_offset_minutes: utc });
  if (!res.ok) return modalError(res.error);
  state.settings = res.data || state.settings;
  closeModal();
  renderSettings();
}

function shabbatFormHtml() {
  const s = state.settings;
  return `
    <form data-submit="submit-shabbat">
      <div class="form-group">
        <label class="form-label">הדלקת נרות לפני שקיעה (דקות)</label>
        <input class="form-control" id="f-candle" type="number" value="${s.candle_offset !== undefined ? s.candle_offset : 18}">
      </div>
      <div class="form-group">
        <label class="form-label">צאת שבת אחרי שקיעה (דקות)</label>
        <input class="form-control" id="f-tzais" type="number" value="${s.tzais_offset !== undefined ? s.tzais_offset : 40}">
      </div>
      <div class="form-actions">
        <button class="btn-secondary" type="button" data-action="modal-close">ביטול</button>
        <button class="btn-primary" type="submit">שמור</button>
      </div>
    </form>`;
}

async function submitShabbat() {
  const candle = parseInt(val('f-candle'), 10);
  const tzais = parseInt(val('f-tzais'), 10);
  if (isNaN(candle) || isNaN(tzais)) return modalError('נא להזין מספרים תקינים');
  const res = await api.put('/api/settings', { candle_offset: candle, tzais_offset: tzais });
  if (!res.ok) return modalError(res.error);
  state.settings = res.data || state.settings;
  closeModal();
  renderSettings();
}

registerActions({
  'edit-city': () => openModal('עיר ומיקום', cityFormHtml()),
  'submit-city': submitCity,
  'edit-shabbat': () => openModal('הגדרות שבת', shabbatFormHtml()),
  'submit-shabbat': submitShabbat,
});
