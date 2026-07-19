#pragma once

/* UART link to the hub (AtomS3). Step 1: loopback self-test.
 * Panel side: UART1-OUT connector — TX=IO20, RX=IO19 (official wiki pinout),
 * function switch must be in WM position (S1=0, S0=1). */

void link_init(void);
