// The desktop client's per-gang state, tested where it costs nothing.
//
// These are the same assertions as tests/test_panel_state_layer.py makes about
// the panel, against the same payload, because the two clients read the same
// /api/zigbee/devices response and had the same bug: on_off was taken from the
// device record, so both gangs of a two-gang switch showed one state.
//
// Run by tests/test_desktop_gang_state.py so it lands in the normal suite.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  STATE_OFF, STATE_ON, STATE_UNKNOWN, STATE_UNREACHABLE,
  gangState, state, stateOf,
} from './store.js';
import { liveCountText } from './views/devices.js';

const IEEE = '70:d0:7e:ff:fe:6e:c6:40';

const TWO_GANG = {
  endpoints: [1, 2],
  clusters: { 1: [0, 3, 6], 2: [0, 3, 6] },
};

function gang(endpoint) {
  return { id: `e${endpoint}`, ieee_address: IEEE, zigbee_endpoint: endpoint };
}

function seed(device, endpoints = []) {
  state.zigbee = device === null ? {} : { [IEEE]: device };
  state.endpoints = endpoints;
}

test('each gang reads its own endpoint', () => {
  seed({ ...TWO_GANG, endpoint_on_off: { 1: false, 2: true } });
  assert.equal(stateOf(gang(1)), STATE_OFF);
  assert.equal(stateOf(gang(2)), STATE_ON);
});

test('the keys arrive as strings through JSON and still match', () => {
  // The panel's map has integer keys. The same map crosses HTTP to get here,
  // where every object key is a string -- if only one spelling were accepted
  // every gang would read "never reported".
  seed({ ...TWO_GANG, endpoint_on_off: { '1': true, '2': false } });
  assert.equal(stateOf(gang(1)), STATE_ON);
  assert.equal(stateOf(gang(2)), STATE_OFF);
});

test('a missing cell does not borrow the neighbour', () => {
  seed({ ...TWO_GANG, on_off: true, endpoint_on_off: { 2: true } });
  assert.equal(stateOf(gang(1)), STATE_UNKNOWN);
});

test('a single-gang device still reads device-wide', () => {
  seed({ endpoints: [1], clusters: { 1: [0, 3, 6] }, on_off: true });
  assert.equal(stateOf(gang(1)), STATE_ON);
});

test('unreachable belongs to the radio, so both gangs show it', () => {
  seed({ ...TWO_GANG, unreachable: true, endpoint_on_off: { 1: false, 2: true } });
  assert.equal(stateOf(gang(1)), STATE_UNREACHABLE);
  assert.equal(stateOf(gang(2)), STATE_UNREACHABLE);
});

test('an unknown device is unknown', () => {
  seed(null);
  assert.equal(stateOf(gang(1)), STATE_UNKNOWN);
  assert.equal(gangState(gang(1)), null);
});

test('one gang on out of two can be said at all', () => {
  // The whole point of the aggregate half. Read from the device record the two
  // entities were one radio, so known was 2 and on was 0 or 2: "1 of 2" was
  // not a sentence the client could produce, whatever the switch was doing.
  seed({ ...TWO_GANG, endpoint_on_off: { 1: true, 2: false } },
       [gang(1), gang(2)]);
  assert.equal(liveCountText(['e1', 'e2']), '1 \u05d3\u05d5\u05dc\u05e7\u05d9\u05dd \u05de\u05ea\u05d5\u05da 2');
});

test('the count says nothing when no gang has reported', () => {
  seed({ ...TWO_GANG }, [gang(1), gang(2)]);
  assert.equal(liveCountText(['e1', 'e2']), '');
});
