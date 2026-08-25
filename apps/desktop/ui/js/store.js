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

// ── one gang's own state ───────────────────────────────────────────────
//
// The same four tokens the panel uses (products/panel/device/dev_common.py),
// and deliberately the same rule, because the two read the same payload. The
// import is blocked -- Python there, JavaScript here -- so
// tests/test_gang_state_rule_is_in_sync.py pins them together.

export const STATE_ON = 'on';
export const STATE_OFF = 'off';
export const STATE_UNKNOWN = 'unknown';
export const STATE_UNREACHABLE = 'unreachable';

const CLUSTER_ON_OFF = 6;

// This entity's own on/off, or null. Never the device's, never a neighbour's.
export function gangState(endpoint) {
  const ieee = endpoint && endpoint.ieee_address;
  if (!ieee) return null;
  const device = state.zigbee[ieee];
  if (!device) return null;
  const ep = endpoint.zigbee_endpoint == null ? 1 : endpoint.zigbee_endpoint;
  const perGang = device.endpoint_on_off || {};
  // The panel's map has integer keys; the same map arrives here through JSON,
  // where every key is a string. Both spellings are accepted rather than
  // assumed, because guessing wrong reads as "this gang never reported".
  for (const key of [String(ep), ep]) {
    if (Object.prototype.hasOwnProperty.call(perGang, key)) return perGang[key];
  }
  // No entry for this gang. On a device known to have more than one, that is
  // an answer of its own -- borrowing the device-level value hands gang 1
  // whatever gang 2 last did. "I don't know" beats a neighbour's state.
  const clusters = device.clusters || {};
  const onoff = (device.endpoints || []).filter(
    g => (clusters[String(g)] || []).includes(CLUSTER_ON_OFF));
  if (onoff.length > 1) return null;
  return typeof device.on_off === 'boolean' ? device.on_off : null;
}

// One of the STATE_* tokens for this endpoint entity.
export function stateOf(endpoint) {
  const ieee = endpoint && endpoint.ieee_address;
  const device = ieee ? state.zigbee[ieee] : null;
  if (!device) return STATE_UNKNOWN;
  // Device-wide: true of the radio, so every gang on it shows it.
  if (device.unreachable) return STATE_UNREACHABLE;
  const on = gangState(endpoint);
  if (on === null || on === undefined) return STATE_UNKNOWN;
  return on ? STATE_ON : STATE_OFF;
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
