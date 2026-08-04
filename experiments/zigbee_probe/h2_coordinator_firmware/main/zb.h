/*
 * Zigbee side of the coordinator: owns the radio stack, the in-flight request
 * table, and the command/event vocabulary spoken over the link.
 *
 * Everything here runs in the Zigbee stack's own context. Commands arrive on
 * the link's queue and are drained by a scheduler alarm (zb_pump) rather than
 * by another task reaching in behind esp_zigbee_lock_acquire() -- which is why
 * this firmware no longer takes that lock anywhere.
 */

#ifndef H2_ZB_H
#define H2_ZB_H

/* Runs the Zigbee task: init, endpoint registration, mainloop. Never returns
 * until the stack shuts down. */
void zb_task(void *arg);

#endif /* H2_ZB_H */
