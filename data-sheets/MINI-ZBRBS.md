# SONOFF MINI-ZBRBS — Smart Roller Shutter Switch

## Overview

**Product name:** MINI-ZBRBS  
**Product series:** MINI Extreme Series  
**Product type:** Smart Roller Shutter Switch  
**Model:** MINI-ZBRBS  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, China 518000  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China

Compact Zigbee smart curtain switch module that fits standard wall boxes. Converts a traditional motorized roller shutter into a smart curtain system. Supports motors up to 1A load. Works with a Zigbee hub for app-based remote control, scheduled operation, and smart scene automation. Also functions as a Zigbee signal repeater.

## Features

- Remote Control
- Percentage Control (position 0–100%)
- Timer Schedule
- Deviation Calibration
- Relay Function (can be used as generic relay)
- Smart Scene integration
- Direction Reverse
- Zigbee signal repeater

## Specifications

| Parameter | Value |
|-----------|-------|
| MCU | EFR32MG21 |
| Rating | 100–240V~ 50/60Hz 1A Max |
| Wireless connectivity | Zigbee 3.0 |
| Net weight | 25.1g |
| Product dimension | 39.5 × 33 × 16.8 mm |
| Color | White |
| Casing material | PC |
| Applicable place | Indoor |
| Working temperature | –10°C ~ 40°C |
| Working humidity | 5–95% RH, non-condensing |
| Max. altitude | 2000m |
| Wiring diameter (recommended) | 18AWG to 14AWG SOL/STR copper conductor only |
| Certification | CE / FCC / RoHS |
| FCC ID | 2APN5-MINIZBRBS |
| Pollution degree | II |
| Rated impulse voltage | 4kV |
| Automatic action | 10,000 Cycles |
| Control type | Type 1.B |

## Terminals & Wiring

| Terminal | Description | Wire | Description |
|----------|-------------|------|-------------|
| N | Neutral Line | N | Neutral Line |
| L | Live Line | L | Live Line (100–240V~) |
| L out1 | Live Output Terminal 1 (100–240V~) | Forward Line | Motor Forward Line |
| L out2 | Live Output Terminal 2 (100–240V~) | Reverse Line | Motor Reverse Line |
| S1 | Switch_1 (Forward Control) | — | — |
| S2 | Switch_2 (Reverse Control) | — | — |

## Wiring Configurations

Two supported wiring types:

1. **Momentary Switch Wiring** — Two separate momentary buttons (UP and DOWN) connected to S1 and S2
2. **Three-Position Rocker Switch Wiring** — Single three-position rocker switch (center-off type) connected to S1 and S2

**Wiring notes:**
- Single-phase use only (100–240V~). Connecting to multiple phases may damage the device.
- MCB or RCBO rated at 1A must be installed before the MINI-ZBRBS.
- All wires must be connected correctly.
- Installation by a professional electrician required.

## Controls

### Button (①)
- **Hold 5 seconds:** Enter pairing mode (pairing window: 3 minutes)
- **Short press 3 times:** Switch external switch type
- **Hold 10 seconds:** Start calibration

### LED Indicator — Blue (②)
| State | Meaning |
|-------|---------|
| Solid on | Normal connection with gateway |
| Slow flash | Device is in pairing mode |
| Fast flash | Abnormal connection with gateway |
| Off | Pairing failure / timeout |
| Breathing mode (hold 10s) | Device is in calibration |
| 3 flashes | Switch type successfully changed |

## External Switch Types

Supported external switch types:
- **Three-position rocker switch** (default from factory — Edge Mode)
- **Momentary switch**

**Switch type modes (cycle):** Edge Mode → Pulse Mode → Following Mode

To change switch type: short-press button 3 times → LED flashes 3 times = success.

## Roller Shutter Direction Test

Press external switch. If shutter moves in wrong direction: power off, swap L out1 and L out2 wires, test again.

## Travel Calibration

Percentage control requires travel calibration. Two methods:

### Method 1: Via eWeLink App
- Open "Initial Settings" on device settings page
- Choose **Automatic Calibration**: click "Start Now" and wait
- Choose **Manual Calibration**: click "Start Now" → "Manual" → move to fully open → click "Next" → move to fully closed → click "Done"

### Method 2: Via Device Button
1. Hold button >10 seconds → LED enters breathing mode
2. Briefly press button → enter Manual Calibration mode
3. Manually open curtains completely → briefly press button → LED flashes 3 times
4. Wait for device to auto-close curtains → briefly press button → LED flashes 3 times → calibration complete

Calibration can be repeated if result is inaccurate.

**Note:** Maximum one-way continuous motor operation time is 2 minutes. Pause before curtain reaches limit position to avoid motor damage.

## Adding the Device

1. Download **eWeLink** app (Google Play Store or Apple App Store)
2. Add a SONOFF Zigbee Gateway in the app
3. In app: tap **+** → **Scan** → scan QR code on device
4. Select **Add Device**
5. Power on device
6. Long-press button 5 seconds → LED flashes slowly for 180s
7. Select Zigbee gateway in app → wait for pairing to complete

## Compatible Gateways

**Recommended SONOFF gateways:** ZBBridge-P, ZBBridge-U, NSPanel Pro, iHost  
**Other compatible SONOFF gateways:** ZBDongle-P, ZBDongle-E

## Factory Reset

Trigger conditions (any one):
- Hold device button for 5 seconds
- Delete device from eWeLink app
- Via external switch (rocker): toggle UP and DOWN keys alternately more than 3 times within 6 seconds
- Via external switch (momentary): press UP key more than 6 times within 6 seconds

## Installation Notes

- Must be completely installed inside a flush-mounted box and enclosed with a cover plate or switch meeting national standard requirements
- No part of product shall be exposed after installation

## RF / Regulatory

**EU Operating Frequency:** Zigbee 2405–2480 MHz  
**EU Output Power:** Zigbee ≤ 10 dBm  
**EU Compliance:** Directive 2014/53/EU — full declaration at https://sonoff.tech/compliance/  
**FCC:** Complies with part 15 of FCC Rules (Class B digital device)  
**FCC RF Exposure:** Minimum 20 cm separation from body  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
