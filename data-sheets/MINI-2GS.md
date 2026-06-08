# SONOFF MINI-2GS — 2-Gang Matter Over Wi-Fi Smart Switch (MINI DUO)

## Overview

**Product name:** MINI DUO  
**Product series:** MINI Extreme series  
**Product type:** 2-Gang Matter Over Wi-Fi Smart Switch  
**Model:** MINI-2GS  
**MCU:** ESP32-C3FH4X  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, 518000, China  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China  
**FCC ID:** 2APN5-MINI2GS  
**US Responsible Party:** SONOFF TECHNOLOGY LLC, 14777 NE 40th St, Suite 201, Bellevue, WA 98007  
**US Email:** usres@itead.cc

Ultra-compact 2-gang Wi-Fi smart switch supporting Matter protocol. Fits inside standard wall switch boxes. Dual channel with total load up to 16A. Supports Matter for seamless integration across smart home ecosystems.

## Features

- Remote Control
- Timer Schedule
- Smart Scene integration
- Share Device
- Group Control
- Matter protocol support
- eWeLink App support
- Voice Control (Alexa, Google Home via Matter)
- Dual Load Control (2 independent channels)
- Supports External Switch

## Compatible Platforms (Matter)

- Amazon Alexa
- Google Home
- Apple Home
- SmartThings

## Specifications

| Parameter | Value |
|-----------|-------|
| Model | MINI-2GS |
| MCU | ESP32-C3FH4X |
| Rating | 110–240V~ 50/60Hz 10A/gang, Total 16A MAX Resistive load |
| Wireless | Wi-Fi IEEE 802.11b/g/n 2.4GHz |
| Net weight | 36.5g |
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
- Single-phase use only (110–240V~). Multi-phase connection damages device.
- MCB or RCBO rated at 16A must be installed before the MINI-2GS.
- S1 and S2 must NOT be connected to neutral or ground wire.
- Two wiring diagrams supported:
  1. Push button type (two push buttons to S1 and S2)
  2. Rocker type (two rocker switches to S1 and S2)

## Controls

### Buttons ① and ② (one per channel)
- **Hold 5 seconds:** Enter pairing mode (pairing window: 10 minutes)
- **Click 3 times:** Change external switch type

### LED Indicator — Blue

**eWeLink mode:**

| State | Meaning |
|-------|---------|
| Steady on | Device online (cloud connected) |
| Flashes twice repeatedly | Connected to router, NOT cloud |
| Flashes once repeatedly | Offline |
| 2 short + 1 long flash | Pairing mode |

**Matter mode:**

| State | Meaning |
|-------|---------|
| Steady on | Device online |
| Flashes once repeatedly | Offline |
| 2 short + 1 long flash | Pairing mode |

## External Switch Types

- **Rocker switch** (factory default)
- **Push button (momentary)**

To change: press button 3 times → LED flashes 3 times quickly = success.

## Adding the Device

### Method 1: Matter (Scan QR code)
1. Open Apple Home / Google Home / Alexa / SmartThings app
2. Scan QR code on the device
3. Follow in-app instructions

### Method 2: eWeLink App
1. Download **eWeLink** app (Google Play Store or Apple App Store)
2. In app: tap **+** → **Scan** → scan QR code, or select Add Device
3. Long press button 5 seconds to enter pairing mode
4. Select Wi-Fi network and enter password
5. Wait for device to connect

**Pairing window:** 10 minutes. To re-enter pairing: hold button 5 seconds.

## Factory Reset

Trigger conditions (any one):
- Delete device in the eWeLink app
- Hold button 10 seconds

## Installation Notes

- Install in mounting box; cover with plate meeting national standards
- No part of product shall be exposed after installation

## RF / Regulatory

**EU Operating Frequency:**
- Wi-Fi 802.11 b/g/n20: 2412–2472 MHz
- Wi-Fi 802.11 n40: 2422–2462 MHz
- BLE: 2402–2480 MHz

**EU Output Power:**
- Wi-Fi 2.4G ≤ 20 dBm
- BLE ≤ 10 dBm

**EU Compliance:** Directive 2014/53/EU — full declaration at sonoff.tech/compliance/  
**FCC:** Complies with part 15 of FCC Rules (Class B digital device); minimum 20 cm body separation; must not be co-located with other transmitters  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
