// HTTP layer — every call resolves to {ok, status, data?, error?}; it
// never throws, so views decide how to surface failures.

async function request(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  try {
    const res = await fetch(path, opts);
    const json = await res.json().catch(() => ({}));
    const payload = json && typeof json === 'object' ? json : { data: json };
    payload.status = res.status;
    if (!res.ok && payload.ok !== false) {
      payload.ok = false;
      payload.error = payload.error || 'HTTP ' + res.status;
    }
    return payload;
  } catch (err) {
    return { ok: false, status: 0, error: (err && err.message) || 'אין תקשורת לשרת' };
  }
}

export const api = {
  get:    (path)       => request('GET',    path),
  post:   (path, body) => request('POST',   path, body),
  put:    (path, body) => request('PUT',    path, body),
  patch:  (path, body) => request('PATCH',  path, body),
  delete: (path)       => request('DELETE', path),
};

// Wraps a response: returns it when ok, throws a typed error otherwise.
export function ensureOk(res) {
  if (res && res.ok !== false) return res;
  const err = new Error((res && res.error) || 'הפעולה נכשלה');
  err.response = res || null;
  err.status = res ? res.status : 0;
  throw err;
}

export function isConnectionError(err) {
  if (err && (err.status === 503 || err.status === 502 || err.status === 0)) return true;
  const msg = String((err && err.message) || '');
  return msg.includes('אינו מחובר') || msg.includes('לא מחובר') ||
    msg.toLowerCase().includes('not connected') ||
    msg.toLowerCase().includes('no device');
}
