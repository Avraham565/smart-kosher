# SONOFF MINI-ZB2GS-L — 2-Gang Zigbee Smart Switch (No Neutral Required) (MINI DUO-L)

## Overview

**Product name:** MINI DUO-L  
**Product series:** MINI Extreme series  
**Product type:** 2-Gang Zigbee Smart Switch (No Neutral Required)  
**Model:** MINI-ZB2GS-L  
**MCU:** EFR32MG22  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, 518000, China  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China  
**FCC ID:** 2APN5-MINIZB2GSL  
**US Responsible Party:** SONOFF TECHNOLOGY LLC, 14777 NE 40th St, Suite 201, Bellevue, WA 98007  
**US Email:** usres@itead.cc

Ultra-compact Zigbee 3.0 dual-channel switch requiring NO neutral wire. Fits inside standard wall switch boxes. Total load up to 12A. Connects to a Zigbee gateway to transform traditional switches into smart controls.

## Features

- Remote Control
- Timer Schedule
- Smart Scene integration
- Power-on State configuration
- Dual Load Control (2 independent channels)
- Supports External Switch
- No Neutral Wire Required
- No Bypass Module Needed

## Specifications

| Parameter | Value |
|-----------|-------|
| Model | MINI-ZB2GS-L |
| MCU | EFR32MG22 |
| Rating | 100–240V~ 50/60Hz 8A/gang, Total 12A MAX Resistive load |
| LED load | 300W@240V/gang, 150W@100V/gang; Total 600W@240V, 300W@100V |
| Min. load | 3W (No Neutral Required) |
| Zigbee | IEEE 802.15.4 |
| Net weight | 33g |
| Product dimension | 45 × 39.4 × 16.8 mm |
| Color | White |
| Casing material | PC |
| Wiring diameter (recommended) | 16AWG to 14AWG SOL/STR copper conductor only |
| Applicable place | Indoor |
| Working temperature | –10°C ~ 40°C |
| Working humidity | 5–95% RH, non-condensing |
| Certification | CE / FCC / RoHS |

> **MCU note:** Uses EFR32MG22 — different from MINI-ZB2GS (with neutral) which uses EFR32MG21.

## Terminals & Wiring

| Terminal | Description |
|----------|-------------|
| L | Live Terminal — Live Line (100–240V~) |
| L | Live Terminal (second input, shared) |
| L | Live Terminal (third input, shared) |
| L1 | Live Output Terminal_1 (100–240V~) |
| L2 | Live Output Terminal_2 (100–240V~) |
| S1 | Switch_1 |
| S2 | Switch_2 |

**7 terminals total. NO Neutral terminal.**

**Wiring notes:**
- Single-phase use only (100–240V~). Multi-phase connection damages device.
- MCB or RCBO rated at 12A must be installed before the MINI-ZB2GS-L.
- S1 and S2 must NOT be connected to neutral or ground wire.
- Two wiring diagrams:
  1. Push button type (two loads, two push buttons)
  2. Rocker type (two loads, two rocker switches)

## Controls

### Button ① (Channel 1 button)
- **Hold 5 seconds:** Enter pairing mode (pairing window: 3 minutes)
- **Click 3 times:** Switch external switch type

### LED Indicator — Green ②

| State | Meaning |
|-------|---------|
| Slow flash | Pairing mode |
| Off | Normal connection with gateway |
| Fast flash | Abnormal connection / Pairing failure / Timeout |
| 3 quick flashes | External switch trigger type changed |
| 5 quick flashes | Factory Reset triggered |

> **Note:** LED is GREEN — matches other no-neutral Zigbee MINI products.

## External Switch Types

- **Rocker switch** (factory default)
- **Push button (momentary)**

To change: press button 3 times → LED flashes 3 times quickly = success.

**Important:** Device stays OFF and CANNOT be controlled while in pairing mode.

## Power On Behavior

On first use, device enters pairing mode by default (LED flashes slowly). Pairing mode exits after 3 minutes if not paired. To re-enter pairing: hold any button 5 seconds until LED flashes slowly.

## Adding the Device

1. Download **eWeLink** app (Google Play Store or Apple App Store)
2. Add a SONOFF Zigbee Gateway in the app
3. In app: tap **+** → **Scan** → scan QR code on device
4. Select **Add Device**
5. If device exited pairing mode: hold button 5 seconds until LED flashes slowly
6. Select Zigbee gateway in app
7. Wait for pairing to complete

## Compatible Gateways

**Recommended SONOFF gateways:** ZBBridge-P, ZBBridge-U, NSPanel Pro, iHost  
**Other compatible SONOFF gateways:** ZBDongle-P, ZBDongle-E

## Factory Reset

Trigger conditions (any one):
- Hold device button 10 seconds
- Delete device in the app

## Installation Notes

- Install in mounting box; cover with plate or switch meeting national standards
- No part of product shall be exposed after installation

## RF / Regulatory

**EU Operating Frequency:** Zigbee 2405–2480 MHz  
**EU Output Power:** Zigbee ≤ 10 dBm  
**EU Compliance:** Directive 2014/53/EU — full declaration at sonoff.tech/compliance/  
**FCC:** Complies with part 15 of FCC Rules (Class B digital device); minimum 20 cm body separation; must not be co-located with other transmitters  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
