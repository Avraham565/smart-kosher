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
  zones: [],
  endpoints: [],
  groups: [],
  schedules: [],
  settings: {},
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
