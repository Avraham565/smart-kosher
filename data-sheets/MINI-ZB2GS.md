# SONOFF MINI-ZB2GS — 2-Gang Zigbee Smart Switch (MINI DUO)

## Overview

**Product name:** MINI DUO  
**Product series:** MINI Extreme Series  
**Product type:** 2-Gang Zigbee Smart Switch  
**Model:** MINI-ZB2GS  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, 518000, China  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China  
**FCC ID:** 2APN5-MINIZB2GS  
**US Responsible Party:** SONOFF TECHNOLOGY LLC, 14777 NE 40th St, Suite 201, Bellevue, WA 98007  
**US Email:** usres@itead.cc

Ultra-compact Zigbee 3.0 dual-channel switch with neutral wire. Fits inside standard wall switch boxes. Supports total load up to 16A. Connects to a Zigbee gateway to transform traditional switches into smart switches. Has built-in Zigbee repeater functionality.

## Features

- Remote Control
- Timer Schedule
- Smart Scene integration
- Power-on State configuration
- Dual Load Control (2 independent channels)
- Supports External Switch
- Relay function
- Group Control
- Zigbee signal repeater

## Specifications

| Parameter | Value |
|-----------|-------|
| Product name | MINI DUO |
| Product series | MINI Extreme series |
| Product type | 2-Gang Zigbee Smart Switch |
| Model | MINI-ZB2GS |
| MCU | EFR32MG21 |
| Rating | 110–240V~ 50/60Hz, 10A/gang, Total 16A MAX Resistive load |
| Zigbee | IEEE 802.15.4 |
| Net weight | 36.2g |
| Product dimension | 45 × 39.4 × 16.8 mm |
| Color | White |
| Casing material | PC |
| Wiring diameter (recommended) | 16AWG to 14AWG SOL/STR copper conductor only |
| Applicable place | Indoor |
| Working temperature | –10°C ~ 40°C |
| Working humidity | 5–95% RH, non-condensing |
| Certification | CE / FCC / RoHS |

## Terminals & Wiring

| Terminal | Description |
|----------|-------------|
| L | Live Terminal — Live Line (110–240V~) |
| L | Live Terminal (second input, shared) |
| N | Neutral Terminal — Neutral Line |
| L1 | Live Output Terminal_1 (110–240V~) |
| L2 | Live Output Terminal_2 (110–240V~) |
| S1 | Switch_1 |
| S2 | Switch_2 |

**Wiring notes:**
- Single-phase use only (110–240V~). Connecting to multiple phases may damage device.
- MCB or RCBO rated at 16A must be installed before the MINI-ZB2GS.
- S1 and S2 must NOT be connected to neutral or ground wire (will damage equipment and cause danger).
- Supported switches: rocker switch (default) and push button.
- Two wiring diagrams:
  1. Two separate loads with two separate switches (push button type)
  2. Two separate loads with two separate switches (rocker type)

## Controls

### Button ① (Channel 1 button)
- **Hold 5 seconds:** Enter pairing mode (pairing window: 3 minutes)
- **Click 3 times:** Switch external switch type

### LED Indicator — Blue ②
| State | Meaning |
|-------|---------|
| Slow flash | Device is in pairing mode |
| Off | Normal connection with gateway |
| Fast flash | Abnormal connection with gateway / pairing failure / timeout |
| 3 quick flashes | External switch trigger type changed |
| 5 quick flashes | Factory reset triggered |

## External Switch Types

- **Rocker switch** (factory default)
- **Push button (momentary)**

To change: short-press button 3 times → LED flashes 3 times quickly = success.

## Power On Behavior

On first use, device enters pairing mode by default (LED flashes slowly). Pairing mode exits after 3 minutes if not paired. To re-enter pairing: hold button 5 seconds until LED flashes slowly.

## Adding the Device

1. Download **eWeLink** app (Google Play Store or Apple App Store)
2. Add a SONOFF Zigbee Gateway in the app
3. In app: tap **+** → **Scan** → scan QR code on device
4. Select **Add Device**
5. If device exited pairing mode: long-press button 5 seconds until LED flashes slowly
6. Select Zigbee gateway in app
7. Wait for pairing to complete

## Compatible Gateways

**Recommended SONOFF gateways:** ZBBridge-P, ZBBridge-U, NSPanel Pro, iHost  
**Other compatible SONOFF gateways:** ZBDongle-P, ZBDongle-E

## Factory Reset

Trigger conditions (any one):
- Hold device button for 10 seconds
- Delete device in the app

## Installation Notes

- Install device in mounting box; enclose with cover plate or switch meeting national standards
- No part of product shall be exposed after installation

## RF / Regulatory

**EU Operating Frequency:**
- Zigbee: 2405–2480 MHz
- BLE: 2402–2480 MHz

**EU Output Power:**
- Zigbee ≤ 10 dBm
- BLE ≤ 10 dBm

**Separation distance:** minimum 20 cm from body  
**EU Compliance:** Directive 2014/53/EU — full declaration at https://sonoff.tech/compliance/  
**FCC:** Complies with part 15 of FCC Rules (Class B digital device); minimum 20 cm separation from body; transmitter must not be co-located with other antennas/transmitters  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
