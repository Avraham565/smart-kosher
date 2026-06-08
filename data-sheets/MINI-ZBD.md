# SONOFF MINI-ZBD — Zigbee Dry Contact Smart Switch

## Overview

**Product name:** MINI Dry  
**Product type:** Zigbee Dry Contact Smart Switch  
**Model:** MINI-ZBD  
**MCU:** EFR32MG21  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, 518000, China  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China  
**FCC ID:** 2APN5-MINIZBD  
**US Responsible Party:** SONOFF TECHNOLOGY LLC, 14777 NE 40th St, Suite 201, Bellevue, WA 98007  
**US Email:** usres@itead.cc

Zigbee 3.0 dry contact smart switch supporting both AC and DC power input. Controls motors, garage doors, and other dry contact devices. Also acts as a Zigbee router to extend signal coverage. Supports smart automation with other devices.

## Features

- Remote Control
- Dry Contact Output (NO / COM / NC)
- Support AC/DC Input (AC 100–240V~ OR DC 12–48V)
- External Switch support
- Relay Function
- Timer Schedule
- Voice Control
- Smart Scene integration
- Zigbee router (signal repeater)

## Compatible Voice Assistants

- Google Home
- Amazon Alexa

## Specifications

| Parameter | Value |
|-----------|-------|
| Model | MINI-ZBD |
| MCU | EFR32MG21 |
| Rating (AC) | 100–240V~ 50/60Hz 0.1A Max |
| Rating (DC) | 12–48V⎓ 1A Max |
| Load (DC resistive) | 24V⎓ 2A Max |
| Load (DC low power) | 12/24V⎓ 8W Max |
| Zigbee | IEEE 802.15.4 |
| Net Weight | 35.3g |
| Dimensions | 41 × 43 × 21.5 mm |
| Color | White |
| Casing Material | PC |
| Wiring | 18AWG to 14AWG (0.75mm² to 1.5mm²) |
| Applicable Place | Indoor |
| Working Temperature | –10°C ~ 40°C |
| Working Humidity | 5%~95% RH, non-condensing |
| Working Height | Less than 2000m |
| Pollution Degree | II |
| Rated Impulse Voltage | 4KV |
| Automatic Action | 20000 Cycles |
| Control Type | 1.B |
| Certification | CE / FCC / RoHS |

> **Note on dimensions:** 41×43×21.5mm — physically different/larger shape compared to other MINI series products.

## Terminals & Wiring

### Top terminals (output — dry contact):
| Terminal | Description |
|----------|-------------|
| NO | Normally Open (Output Terminal) |
| COM | Common (Output Terminal) |
| NC | Normally Closed (Output Terminal) |

### Bottom terminals (input):
| Terminal | Description |
|----------|-------------|
| N | Neutral (AC Input Terminal) |
| L | Live (AC Input Terminal, 100–240V~) |
| S1 | External Switch (Input Terminal) |
| S2 | External Switch (Input Terminal) |
| DC+ | 12V–48V DC Positive (Input Terminal) |
| DC– | 12V–48V DC Negative (Input Terminal) |

**Wiring notes:**
- DO NOT connect AC and DC power inputs at the same time.
- For AC use: connect N and L; for DC use: connect DC+ and DC–.
- Single-phase AC (100–240V~) OR DC 12–48V⎓ only. Multi-phase damages device.
- 3A overcurrent protection device required in MINI-ZBD control output circuit.
- Two wiring configs: AC input diagram and DC input diagram.
- Applicable to any device controllable via dry contact (motors, garage doors, etc.).
- For garage door compatibility test: short-circuit wall-switch terminals on motor — if motor activates, compatible; if not, incompatible.

## Controls

### Button (①)
- **Single press:** Turn on/off
- **Hold 5 seconds:** Enter pairing mode (pairing window: 3 minutes)
- **Hold 10 seconds:** Factory Reset
- **Click 3 times:** Switch external switch type

### LED Indicator — Blue (②)

| State | Meaning |
|-------|---------|
| Slow flash | Pairing mode |
| Steady off | Pairing failure / Timeout |
| Steady on | Normal connection with gateway |
| Fast flash | Abnormal connection with gateway |
| 3 quick flashes | External switch trigger type changed |

## External Switch Types

- **Rocker switch** (factory default)
- **Momentary (push button)**

To change: press button 3 times → LED flashes 3 times = success.

## Power On Behavior

On first use, device enters pairing mode automatically (LED flashes slowly). Exits pairing after 3 minutes if not paired. To re-enter: hold button 5 seconds until LED flashes slowly.

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

**Third-party compatible gateways:**
- Amazon: Echo Plus 2nd, Echo Show 2nd, Echo 4th Gen
- Samsung: SmartThings hub V3
- Any gateway supporting ZigBee 3.0

## Factory Reset

Trigger conditions (any one):
- Hold device button 10 seconds
- Toggle external switch rapidly 10 times (resets all settings except external switch type)
- Delete device in eWeLink app

## Installation Notes

- Install in mounting box; cover with plate meeting national standards
- No part of product shall be exposed after installation

## RF / Regulatory

**EU Operating Frequency:** Zigbee 2405–2480 MHz  
**EU Output Power:** Zigbee ≤ 10 dBm  
**EU Compliance:** Directive 2014/53/EU — full declaration at sonoff.tech/compliance/  
**FCC:** Class B digital device, part 15; minimum 20 cm body separation; must not be co-located with other transmitters  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
