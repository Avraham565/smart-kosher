# SONOFF MINIR4M — Wi-Fi Smart Switch (Matter)

## Overview

**Product series:** MINI Extreme series  
**Product type:** Wi-Fi Smart Switch with Matter  
**Model:** MINIR4M  
**MCU:** ESP32-C3FN4  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, 518000, China  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China

Ultra-compact Wi-Fi smart switch supporting Matter protocol. Fits inside standard wall switch boxes. Supports SmartThings, Apple Home, Amazon Alexa, Google Home via Matter. Also works with eWeLink app.

## Features

- Remote Control
- Timer Schedule
- Smart Scene integration
- Power-on State configuration
- Matter protocol support
- eWeLink App support
- Voice Control (Alexa, Google Home, Apple Siri via Matter)
- Relay Function

## Compatible Platforms (Matter)

- Amazon Alexa
- Google Home
- Apple Home
- SmartThings

## Specifications

| Parameter | Value |
|-----------|-------|
| Model | MINIR4M |
| MCU | ESP32-C3FN4 |
| Rating | 100–240V~ 50/60Hz 10A Max Resistive Load |
| Max. Load | 2400W @ 240V |
| Wireless | Wi-Fi IEEE 802.11b/g/n 2.4GHz |
| Net weight | 26.7g |
| Product dimension | 39.5 × 33 × 16.8 mm |
| Color | White |
| Casing material | PC V0 |
| Applicable place | Indoor |
| Working temperature | –10°C ~ 40°C |
| Working humidity | 5%~95% RH, non-condensing |
| Certification | CE / FCC / RoHS / SRRC / TUV / ISED |
| Executive standard | EN IEC 60669-2-1 |

## Terminals & Wiring

| Terminal | Description |
|----------|-------------|
| N | Neutral Terminal |
| N | Neutral Terminal (second, shared) |
| L Out | Live Output Terminal (100–240V~) |
| L In | Live Input Terminal (100–240V~) |
| S1 | Switch_1 |
| S2 | Switch_2 |

**Wiring notes:**
- Single-phase use only (100–240V~). Multi-phase connection damages device.
- MCB or RCBO rated at 10A must be installed before the MINIR4M.
- S1 and S2 must NOT be connected to neutral or ground wire.
- Four wiring configurations supported:
  1. S1 + S2 (two external switches)
  2. S1 only
  3. No external switch
  4. S2 only

## Controls

### Button (①)
- **Single press:** Toggle relay on/off
- **Hold 5 seconds:** Enter pairing mode (pairing window: 10 minutes)

### LED Indicator — Blue (②)

**eWeLink mode:**

| State | Meaning |
|-------|---------|
| Steady on | Device online (cloud connected) |
| Flashes twice repeatedly | Connected to router, not cloud (LAN mode) |
| Flashes once repeatedly | Offline |
| 2 short + 1 long flash | Pairing mode |
| 3 flashes | Trigger mode changed |

**Matter mode:**

| State | Meaning |
|-------|---------|
| Steady on | Device online |
| Flashes once repeatedly | Offline |
| 2 short + 1 long flash | Pairing mode |
| 3 flashes | Trigger mode changed / Identify |

## External Switch Types

- **Rocker switch** (factory default)
- **Push button (momentary)**

To change: configure in eWeLink app or press button 3 times → LED flashes 3 times = success.

## Adding the Device

### Method 1: Matter (Scan QR code)
1. Open Alexa / Google Home / Apple Home / SmartThings app
2. Scan QR code on the device
3. Follow in-app instructions to add

### Method 2: eWeLink App
1. Download **eWeLink** app (Google Play Store or Apple App Store)
2. In app: tap **+** → **Scan** → scan QR code on device
3. Select Wi-Fi network and enter password
4. Wait for device to connect

**Pairing window:** 10 minutes. To re-enter pairing: hold button 5 seconds.

## Factory Reset

- Hold button 5 seconds → device re-enters pairing mode (LED: 2 short + 1 long flash)

## Installation Notes

- Install in mounting box; cover with plate meeting national standards
- No part of product shall be exposed after installation
- Must be completely enclosed

## RF / Regulatory

**EU Operating Frequency:** Wi-Fi 2412–2472 MHz  
**EU Output Power:** Wi-Fi ≤20dBm  
**EU Compliance:** Directive 2014/53/EU — full declaration at sonoff.tech/usermanuals  
**FCC:** Class B digital device, part 15; minimum 20 cm body separation; must not be co-located with other transmitters  
**ISED (Canada):** RSS-247; ICES-003; minimum 20 cm body separation; bilingual French/English labeling required  
**SAR:** Minimum 20 cm body separation  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
