# SONOFF MINI-ZBDIM — Zigbee Dimmer Switch (MINI DIM)

## Overview

**Product name:** MINI DIM (Zigbee)  
**Product series:** MINI Extreme series  
**Product type:** Zigbee Dimmer Switch  
**Model:** MINI-ZBDIM  
**MCU:** EFR32MG21  
**Manual version:** V1.0  
**Manufacturer:** Shenzhen Sonoff Technologies Co., Ltd.  
**Address:** 3F & 6F, Bldg A, No. 663, Bulong Rd, Shenzhen, Guangdong, 518000, China  
**Service email:** support@itead.cc  
**Website:** sonoff.tech  
**Made in:** China

Ultra-compact Zigbee 3.0 smart dimmer controller. Max load current 2A. Compatible with dimmable LED lamps, incandescent bulbs, halogen lamps, and dimmable electronic transformers. Built-in overheat protection, power detection, and brightness calibration.

> **Important:** 220–240V~ ONLY (50Hz). EU market product — no FCC certification. Not suitable for 110V markets.

## Features

- Remote Control
- Smart Timer / Delay
- Smart Scene integration
- External Switch support
- Brightness Calibration (auto and manual)
- Over-Temperature Protection
- Power Detection
- Excellent Lamp Compatibility

## Compatible Lamp Types

- Dimmable LED lamps
- Incandescent bulbs
- Halogen lamps
- Dimmable electronic transformers

## Specifications

| Parameter | Value |
|-----------|-------|
| Model | MINI-ZBDIM |
| MCU | EFR32MG21 |
| Rating | 220–240V~ 50Hz 400W Max Resistive load |
| LED load | 200VA |
| Zigbee | IEEE 802.15.4 |
| Net weight | 24.5g |
| Product dimension | 45 × 39.4 × 16.8 mm |
| Color | White |
| Casing material | PC |
| Wiring diameter (recommended) | 18AWG to 16AWG SOL/STR copper conductor only |
| Applicable place | Indoor |
| Working temperature | –10°C ~ 40°C |
| Working humidity | 5–95% RH, non-condensing |
| Certification | CE / RoHS |

> **No FCC certification** — for EU / 220–240V markets only.

## Terminals & Wiring

| Terminal | Description |
|----------|-------------|
| L | Live Terminal — Live Line (220–240V~) |
| L | Live Terminal (second input, shared) |
| L | Live Terminal (third input, shared) |
| N | Neutral Terminal — Neutral Line |
| O | Live Output Terminal — Dimmer output (220–240V~) |
| S1 | Switch_1 |
| S2 | Switch_2 |

**7 terminals total. Neutral wire required.**

**Wiring notes:**
- Single-phase use only (220–240V~). Multi-phase connection damages device.
- MCB or RCBO rated at 2A must be installed before the MINI-ZBDIM.
- S1 and S2 must NOT be connected to neutral or ground wire.
- Supported switches: rocker and push button.
- Factory default: double push button mode.
- To match external switch: set mode in eWeLink app, or press button 3 times.

## Controls

### Buttons ① and ②
- **Single tap ①:** Turn device on or off
- **Hold 5 seconds ①:** Enter pairing mode (pairing window: 3 minutes)
- **Click 3 times ①:** Switch external switch type
- **Hold 10 seconds ①:** Auto-calibrate dimming (brightness range calibration)
- **Hold 15 seconds ①:** Restore factory settings

### LED Indicator — Blue (②)

| State | Meaning |
|-------|---------|
| Slow flash | Pairing mode |
| Fast flash | Abnormal connection with gateway |
| Steady on | Normal connection with gateway |
| Off | Pairing failure / Timeout |
| 3 quick flashes | External switch trigger type changed |
| 5 quick flashes | Factory Reset triggered |
| Breathing pattern | Device is calibrating (brightness calibration in progress) |

## External Switch Types

- **Rocker switch**
- **Push button (momentary)**
- **Factory default:** Double push button

To change: press button 3 times → LED flashes 3 times quickly = success. Or change in eWeLink app.

## Brightness Range Calibration

Required for percentage-based brightness control.

### Auto Calibration
- Hold device button 10 seconds, OR
- Use "Auto Calibration" in the eWeLink app  
  LED enters breathing pattern during calibration.

### Manual Calibration
- Adjust brightness limits manually in eWeLink app for fine-tuned control.

## Power On Behavior

On first use, device enters pairing mode by default (LED flashes slowly). Exits pairing after 3 minutes if not paired. To re-enter: hold button 5 seconds until LED flashes slowly.

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
**Other compatible SONOFF gateways:** ZBDongle-P, ZBDongle-E, Dongle-M, Dongle-PMG24, Dongle-LMG21

> **Note:** MINI-ZBDIM supports more dongle models than other MINI Zigbee products.

## Factory Reset

Trigger conditions (any one):
- Delete device in eWeLink app
- Re-pair with a different eWeLink account (device resets and joins new account)
- Hold device button 15 seconds (NOTE: 15 seconds, not 10)

## Installation Notes

- Install in mounting box; cover with plate meeting national standards
- No part of product shall be exposed after installation

## RF / Regulatory

**EU Operating Frequency:**
- Zigbee: 2405–2480 MHz
- BLE: 2402–2480 MHz

**EU Output Power:**
- Zigbee ≤ 10 dBm
- BLE ≤ 10 dBm

**EU Compliance:** Directive 2014/53/EU — full declaration at sonoff.tech/compliance/  
**WEEE:** Directive 2012/19/EU — do not dispose with household waste
