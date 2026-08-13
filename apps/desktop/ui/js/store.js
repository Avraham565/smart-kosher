// App state — one plain object plus local mutation helpers.
//
// The important pattern: after a create/update/delete the hub returns the
// affected entity, so the store is patched locally and the view re-renders
// from memory. No full refetch, no flashing "loading" screen — the three
// collections are only fetched again when a tab actually needs data it
// has never loaded (or asks for a refresh).

import { api, ensureOk } from './api.js';

export const state = {
  tab: 'devices',
  subTab: 'endpoints',   // devices sub-tab: endpoints | groups | zones
  deviceId: null,        // open device page, when tab === 'device'
  zones: [],
  endpoints: [],
  groups: [],
  schedules: [],
  settings: {},
  zigbee: {},            // ieee -> {short_addr, endpoint, reporting, on_off?, unreachable?}
  loaded: {},            // collection name -> true after first fetch
};

const COLLECTION_PATHS = {
  zones: '/api/zones',
  endpoints: '/api/endpoints',
  groups: '/api/groups',
  schedules: '/api/schedules',
};

// Fetch the named collections (in parallel) unless already cached.
export async function ensureLoaded(names, { refresh = false } = {}) {
  const missing = names.filter(n => refresh || !state.loaded[n]);
  if (!missing.length) return;
  const results = await Promise.all(
    missing.map(n => api.get(COLLECTION_PATHS[n])));
  results.forEach((res, i) => {
    ensureOk(res);
    state[missing[i]] = res.data || [];
    state.loaded[missing[i]] = true;
  });
}

export function upsert(collection, entity) {
  if (!entity || !entity.id) return;
  const list = state[collection];
  const idx = list.findIndex(e => e.id === entity.id);
  if (idx >= 0) list[idx] = entity;
  else list.push(entity);
}

export function remove(collection, id) {
  state[collection] = state[collection].filter(e => e.id !== id);
}

export function byId(collection, id) {
  return state[collection].find(e => e.id === id) || null;
}

export function invalidate(...names) {
  for (const n of names) state.loaded[n] = false;
}

// ── live radio state ───────────────────────────────────────────────────

// Refreshes the ieee -> live-state map. Cheap (one op) and safe to poll;
// returns false when the hub has no radio gateway (dev simulator).
export async function refreshZigbee() {
  const res = await api.get('/api/zigbee/devices');
  if (!res.ok) return false;
  state.zigbee = res.data || {};
  return true;
}

// Live radio info for an endpoint entity, joined by its ieee address.
export function radioOf(endpoint) {
  if (!endpoint || !endpoint.ieee_address) return null;
  return state.zigbee[endpoint.ieee_address] || null;
}

// Schedules aimed at this endpoint, directly or through a group.
export function schedulesFor(endpointId) {
  const groupIds = state.groups
    .filter(g => (g.member_ids || []).includes(endpointId))
    .map(g => g.id);
  return state.schedules.filter(sch =>
    (sch.target_type === 'endpoint' && sch.target_id === endpointId) ||
    (sch.target_type === 'group' && groupIds.includes(sch.target_id)));
}
