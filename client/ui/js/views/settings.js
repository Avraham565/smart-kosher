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
      <div class="settings-row"><span class="settings-key">גובה</span><span class="settings-val">${s.elevation !== undefined ? s.elevation + ' מ׳' : '—'}</span></div>
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
      <div class="settings-row"><span class="settings-key">צאת שבת</span><span class="settings-val">8.5° מתחת לאופק</span></div>
      <div class="settings-row"><span class="settings-key"></span><span class="settings-val">קבוע לכל הארץ — לא ניתן לשינוי</span></div>
    </div>`);
}

// The packaged list, fetched once. Picking from it is the normal path: the
// server expands the chosen id into latitude, longitude and elevation, so the
// three can never drift apart the way they did when the name was free text and
// the coordinates were typed beside it.
let cityList = [];

async function loadCities() {
  if (cityList.length) return cityList;
  const res = await api.get('/api/settings/cities');
  if (res.ok) cityList = res.data || [];
  return cityList;
}

function cityFormHtml() {
  const s = state.settings;
  const options = cityList.map((c) =>
    `<option value="${esc(c.id)}"${c.name_he === s.city ? ' selected' : ''}>${esc(c.name_he)}</option>`
  ).join('');
  // "אחר" keeps hand-entered locations reachable -- the list covers the country
  // but not every yishuv, and the API accepts explicit coordinates.
  const custom = !cityList.some((c) => c.name_he === s.city);
  return `
    <form data-submit="submit-city">
      <div class="form-group">
        <label class="form-label">עיר</label>
        <select class="form-control" id="f-city-select" data-change="city-picked">
          ${options}
          <option value="__custom__"${custom ? ' selected' : ''}>אחר (הזנה ידנית)</option>
        </select>
      </div>
      <div id="f-city-custom" style="${custom ? '' : 'display:none'}">
        <div class="form-group">
          <label class="form-label">שם המקום</label>
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
          <label class="form-label">גובה (מטרים)</label>
          <input class="form-control" id="f-city-elev" type="number" step="1" min="0" value="${s.elevation !== undefined ? s.elevation : 0}">
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

function cityPicked() {
  const picked = val('f-city-select');
  const box = document.getElementById('f-city-custom');
  if (box) box.style.display = picked === '__custom__' ? '' : 'none';
}

async function submitCity() {
  const utc = parseInt(val('f-city-utc'), 10);
  const picked = val('f-city-select');

  if (picked !== '__custom__') {
    // Send the id alone. The server owns the geography behind the name, so the
    // client cannot save a city with someone else's coordinates.
    const res = await api.put('/api/settings', { city: picked, utc_offset_minutes: utc });
    if (!res.ok) return modalError(res.error);
    state.settings = res.data || state.settings;
    closeModal();
    return renderSettings();
  }

  const city = val('f-city-name');
  const lat = parseFloat(val('f-city-lat'));
  const lon = parseFloat(val('f-city-lon'));
  const elevation = parseFloat(val('f-city-elev'));
  if (!city) return modalError('נא להזין שם מקום');
  if (isNaN(lat) || isNaN(lon)) return modalError('קו רוחב ואורך חייבים להיות מספרים');
  // Elevation moves sunset by ~5 minutes at Jerusalem's altitude, so a blank or
  // negative field must not quietly become sea level.
  if (isNaN(elevation) || elevation < 0) return modalError('גובה חייב להיות מספר אי-שלילי');
  const res = await api.put('/api/settings', { city, lat, lon, elevation, utc_offset_minutes: utc });
  if (!res.ok) return modalError(res.error);
  state.settings = res.data || state.settings;
  closeModal();
  renderSettings();
}

// The Shabbat offsets used to be editable here. Candle lighting is a fixed
// product rule now -- 18 minutes before sunset, identical across Israel -- so
// the API rejects a write to it and this editor was removed rather than left to
// fail. The card shows the value the API reports from the constant itself, so a
// device whose settings.json predates the rule cannot display a stale number.
//
// Shabbat exit has no number to show at all: it is an angle (8.5 degrees below
// the horizon), which is roughly 36 minutes after sunset at the equinox but
// stretches past 42 in June. It used to be stored as a flat 36.

registerActions({
  // The list is fetched before the modal opens so the picker is never rendered
  // empty; a failed fetch leaves it empty and the "אחר" path still works.
  'edit-city': async () => {
    await loadCities();
    openModal('עיר ומיקום', cityFormHtml());
  },
  'city-picked': cityPicked,
  'submit-city': submitCity,
});
