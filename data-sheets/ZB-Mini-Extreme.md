# SONOFF ZBMINI Extreme (ZBMINIL2) — Zigbee Smart Switch (No Neutral Required)

## Overview

**Product branding:** ZBMINI Extreme  
**Model (specs):** ZBMINIL2  
**Product type:** Zigbee Smart Switch — NO NEUTRAL WIRE REQUIRED  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, GD, China 518000  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China

Ultra-compact Zigbee smart switch that requires NO neutral wire. Single-channel. Installs in a mounting box. Max load 6A resistive. Does NOT require a bypass module. Supports external switch. Works as Zigbee end device (not a router/repeater).

## Features

- Remote Control
- Timer Schedule
- Smart Scene integration
- Power-on State configuration
- Voice Control (Google Home, Amazon Alexa, Alice)
- No neutral wire required
- No bypass module required
- Supports External Switch
- Relay function

## Compatible Voice Assistants

- Google Home
- Amazon Alexa
- Alice

## Specifications

| Parameter | Value |
|-----------|-------|
| Model | ZBMINIL2 |
| Input | 100–240V AC 50/60Hz 6A Max |
| Output | 100–240V AC 50/60Hz 6A Max |
| Max load (Resistive) | 6A Max |
| Max load (LED) | 150W Max @ 100V; 300W Max @ 240V |
| Min. load | Not specified (no bypass needed) |
| Wireless | Zigbee 3.0 |
| Product dimension | 39.5 × 32 × 18.4 mm |
| Color | White |
| Casing material | PC V0 |
| Applicable place | Indoor |
| Working temperature | –10°C ~ 40°C |
| Certification | CE / FCC / ISED / RoHS |
| Chinese standard | GB/T 16915.2 |

> **Note on dimensions:** Width is 32mm and depth 18.4mm — differs from neutral-wire variants (33mm wide, 16.8mm deep).

## Terminals & Wiring

| Terminal | Description |
|----------|-------------|
| L Out | Live Output Terminal |
| L In | Live Input Terminal |
| S1 | Switch_1 |
| S2 | Switch_2 |

**Only 4 terminals — no Neutral terminal.**

**Wiring notes:**
- Single-phase use only (100–240V~).
- MCB or RCBO rated at 6A must be installed before the ZBMINIL2.
- S1 and S2 must NOT be connected to neutral or ground wire.
- UNSUPPORTED load types: fans and other inductive loads.
- For wiring configs ③ and ④ (no switch on S terminal): ensure proper wiring of L In or device works abnormally.

**Four wiring configurations:**
1. Push button + S1 and S2
2. Rocker switch + S1 and S2
3. Push button + S2 only (no S1)
4. Rocker switch + S2 only (no S1)

## Controls

### Button (on device body)
- **Hold 5 seconds:** Enter pairing mode (pairing window: 3 minutes)
- **Press 3 times:** Switch external switch type

### LED Indicator — GREEN

| State | Meaning |
|-------|---------|
| Slow flash | Pairing mode |
| Steady on (relay ON) | Device online |
| Quick flash (relay ON) | Abnormal: ZBMINI Extreme and router OK, but router/gateway disconnected from cloud |
| Slow flash (relay ON, not pairing) | Abnormal: ZBMINI Extreme disconnected from parent device |

> **Note:** LED color is GREEN — not blue like Wi-Fi/Matter MINI products.

## External Switch Types

- **Rocker switch** (factory default)
- **Push button (momentary)**

To change: press button 3 times → LED flashes 3 times = success.

**Important:** Device stays OFF and CANNOT be controlled by button or external switch while in pairing mode.

## Adding the Device

### Method 1: eWeLink App (via SONOFF Zigbee gateway)
1. Download **eWeLink** app (Google Play Store or Apple App Store)
2. Add a SONOFF ZB Bridge gateway in the app
3. Power on ZBMINI Extreme → device auto-enters pairing mode (LED slow flash)
4. In eWeLink app: tap **Add** on the ZB Bridge interface
5. Wait for pairing to complete

### Method 2: Amazon Echo (built-in Zigbee hub)
1. Download Alexa app
2. Power on ZBMINI Extreme
3. Say: "Alexa, discover my devices"

**Pairing window:** 3 minutes (shorter than Wi-Fi/Matter models). To re-enter pairing: hold button 5 seconds.

## Compatible Gateways

**Recommended SONOFF gateways:** ZBBridge-P, ZBBridge-U, NSPanel Pro, iHost  
**Other compatible SONOFF gateways:** ZBDongle-P, ZBDongle-E

## Factory Reset

Trigger conditions (any one):
- Press external switch 10 consecutive times
- Hold device button 5 seconds
- Delete device from eWeLink app

## Installation Notes

- Install in mounting box; cover with plate meeting national standards
- No part of product shall be exposed after installation

## RF / Regulatory

**EU Operating Frequency:** Zigbee 2405–2480 MHz  
**EU Output Power:** Zigbee ≤ **13 dBm** (higher than other Zigbee MINI products which are ≤10 dBm)  
**EU Compliance:** ZBMINIL2 complies with Directive 2014/53/EU — full declaration at sonoff.tech/compliance/  
**FCC:** Class B digital device, part 15; minimum 20 cm body separation; must not be co-located with other transmitters  
**ISED (Canada):** Licence-exempt RSS; ICES-003(B); RSS-247; minimum 20 cm body separation  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
