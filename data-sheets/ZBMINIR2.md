# SONOFF ZBMINIR2 — Zigbee Smart Switch (Neutral Wire Required)

## Overview

**Model:** ZBMINIR2  
**Manual version:** V1.2  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, China 518000  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China

Extremely compact Zigbee 3.0 single-channel neutral wire switch. Installs in a mounting box. Supports max load of 10A. Makes ordinary switches smart. Supports Zigbee repeater function to improve network communication quality. Can link with other devices in smart scenes for home automation.

## Features

- Remote Control
- Timer Schedule
- Voice Control (Google Home, Amazon Alexa)
- Smart Scene integration
- Power-on State configuration
- Inching Mode
- Relay function
- Group Control
- Zigbee signal repeater

## Compatible Voice Assistants

- Google Home
- Amazon Alexa

## Specifications

| Parameter | Value |
|-----------|-------|
| Model | ZBMINIR2 |
| MCU | EFR32MG21 |
| Rating | 100–240V~ 50/60Hz 10A Max Resistive Load |
| Max. Load | 2400W @ 240V |
| Wireless Connectivity | Zigbee 3.0 |
| Net Weight | 26.7g |
| Dimension | 39.5 × 33 × 16.8 mm |
| Color | White |
| Casing Material | PC V0 |
| Applicable Place | Indoor |
| Working Temperature | –10°C ~ 40°C |
| Working Humidity | 5%~95% RH, non-condensing |
| Working height | Less than 2000m |
| Certification | CE / FCC / ISED / RoHS |
| Executive standard | EN 60669-2-1 |

## Terminals & Wiring

Terminals: **N** (Neutral), **N** (Neutral), **L Out**, **L In**, **S1**, **S2**

**Wiring notes:**
- Neutral wire required (N terminal must be connected)
- S1 and S2 are switch inputs — do NOT connect to neutral or ground wire (will damage equipment)
- Make sure all wires are connected correctly
- Supported external switches: rocker switch and push button (factory default: rocker switch)
- MCB or RCBO rated at 10A must be installed before the ZBMINIR2

**Four wiring configurations supported:**
1. Single switch with S1 only
2. Single switch with S2 only
3. Two switches with S1 and S2 (independent)
4. Two switches with S1 and S2 (coordinated)

## Controls

### Button (①)
- **Single press:** Turn on/off the device
- **Hold 5 seconds:** Enter pairing mode (pairing window: 10 minutes)
- **Click 3 times:** Switch external switch type

### LED Indicator — Green (②)
| State | Meaning |
|-------|---------|
| Slow flash for 180s | First-time power on / device is in pairing mode |
| Steady on | Normal connection with gateway |
| Slow flash | Device is in pairing mode |
| Fast flash | Abnormal connection with gateway |
| 3 quick flashes | External switch trigger type changed |

## External Switch Types

- **Rocker switch** (factory default)
- **Push button (momentary)**

To change: short-press button 3 times → green indicator flashes 3 times quickly = success.

## Adding the Device

1. Download **eWeLink** app (Google Play Store or Apple App Store)
2. Add a SONOFF Zigbee Gateway in the app
3. In app: tap **+** → **Scan** → scan QR code on device
4. Select **Add Device**
5. Power on device
6. Long-press button 5 seconds → LED flashes slowly for 180s
7. Select Zigbee gateway in app → wait for pairing to complete

## Compatible Gateways

**Recommended SONOFF gateways:** ZBBridge-P, NSPanel Pro, iHost, ZBBridge-U  
**Other compatible SONOFF gateways:** ZBDongle-P, ZBDongle-E  
**Third-party compatible gateways:**
- Amazon: Echo Plus 2nd, Echo Show 2nd, Echo 4th Gen
- Samsung: SmartThings hub V3
- Any gateway supporting ZigBee 3.0 wireless protocol

## Factory Reset

Trigger conditions (any one):
- Hold device button for 5 seconds
- Quickly press external switch 10 times (restores all settings except external switch type)
- Delete device in eWeLink app

## Installation Notes

- Install in the MINI Extreme mounting box
- MCB or RCBO rated at 10A must be installed upstream

## RF / Regulatory

**EU Operating Frequency:** Zigbee 2405–2480 MHz  
**EU Output Power:** Zigbee ≤ 10 dBm  
**EU Compliance:** Directive 2014/53/EU — full declaration at https://sonoff.tech/compliance/  
**FCC:** Complies with part 15 of FCC Rules (Class B digital device)  
**FCC RF Exposure:** Minimum 20 cm separation from body  
**ISED (Canada):** Complies with licence-exempt RSS(s), RSS-247, ICES-003(B); minimum 20 cm separation from body  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
