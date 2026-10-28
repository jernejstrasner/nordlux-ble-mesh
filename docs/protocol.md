# The Yankon/Nordlux BLE Mesh control protocol

Reverse-engineered from the official "Nordlux Smart Light" Android app
(`com.nx.smbt5.a.android`, v2.6.2, decompiled with jadx) and verified
on-air against two Nordlux tunable-white ceiling fixtures
(CID `0x0504`, PID `0x6212`, VID `0x0010`).

## Background

These lights are standard **Bluetooth SIG Mesh** nodes and provision
perfectly with any compliant provisioner (PB-GATT). After provisioning you
can bind AppKeys to their models, read composition data, and exchange
standard messages — Generic OnOff, Light Lightness, Light CTL all respond
with *correct, honest status replies*.

**But none of those messages ever change the LEDs.** The LED driver is wired
to a vendor command parser instead. This makes every "it replied OK" test a
false positive — only your eyes (or the state readback trick below) tell the
truth.

## Command encoding

The parser accepts a multiplexed payload carried in **Light CTL Set
Unacknowledged** (opcode `0x825F`, app-keyed):

```
lightness(2, LE)  temperature(2, LE)  delta_uv(2, LE)  tid(1)  transition(1)  delay(1)
```

| Function | lightness | temperature | transition | Constant in app source |
|---|---|---|---|---|
| ON | 0 | 10000 | 0x00 | `CONTROL_POWER_OPEN` |
| OFF | 0 | 15000 | 0x00 | `CONTROL_POWER_CLOSED` |
| Brightness % | 1–100 | 901 | 0x04 | 901 = `CONTROL_CCT` marker |
| Color temp % | **101** | **801–900** | 0x04 | 101 = `CONTROL_BRI` marker |

Source: `com/nx/smbt5/a/android/ConstantUtils.java` and
`ble_mesh/silicon/vendorcontrol/SiliconControl.java` (`setDoubleRingNormal` /
`setDoubleRingPower` — the ON bytes `(16, 39)` and OFF bytes `(-104, 58)`
are 10000/15000 little-endian).

The app itself sends the same bytes as **vendor model** opcode `0xC5`
(+ CID LE), payload `[bri][temp 2LE][uv 2LE][time][room][flag]`, addressed
to a group (`DEFAULT_GROUP_ADDR = 0xC000`). The `0x825F` framing works
identically on this firmware and is easier to build with standard mesh
libraries. Default group address: `0xC000`.

### Scale notes

- Brightness is **1–100 percent** (not 0–65535). `DEFAULT_BRI = 100`.
- Color temperature is **801–900**, where 801 = warmest and 900 = coolest
  (`DEFAULT_CCT = 900`). The app UI slider maps 0–100 % → `cct - 800`, but
  **800 itself is silently rejected** — the effective floor is 801.
  Physical range depends on the fixture's LEDs.
- ON (10000) **restores the previous brightness**; it is not "full on".

## State readback (feedback channel)

Standard **Light CTL Get** (app-keyed, acknowledged) returns the *actual*
applied state — this is how you can blind-test candidate commands:

- `present lightness` = current brightness percent (0 when off)
- `present temperature` = raw CCT (801–900) while on; other values while off

This works even though standard *Set* commands don't drive the LEDs: the
vendor parser writes its state into the standard CTL state variables.

## Firmware quirks (all verified on-air)

1. **TID replay cache is unbounded-ish.** Reusing a `(src, TID)` pair that
   was used in an *earlier session* (minutes/hours before) gets silently
   dropped — far beyond the spec's 6-second window. Always keep a persistent,
   monotonically increasing TID counter per provisioner address. Several
   false "the command doesn't work" conclusions during reverse-engineering
   were caused by TID reuse from earlier test scripts.

2. **First faded command of a fresh GATT session is sometimes dropped.**
   Observed repeatedly: a brightness command with transition `0x04` sent as
   the very first access message after connecting is ignored, while the same
   command with transition `0x00` applies instantly. **Always verify every
   command with Light CTL Get and retry without fade on mismatch** (the CLI
   in this repo does this).

3. **Standard SIG model messages never drive the LEDs** — only the vendor
   payload does. Statuses are nonetheless correct and honest.

4. **Proxy nodes advertise Node Identity** (type 0x01), not Network ID
   (type 0x00), so a scanning client cannot cryptographically match them to
   its network when several are in range. Match by the BLE address recorded
   at provisioning time instead (see the patch in
   `lib/provision_and_toggle.py`).

5. Factory reset (wall switch off/on 3×, 1–2 s apart) returns the light to
   unprovisioned state, advertising service `0x1827` with device UUID
   `ASCII "nx" + serial + MAC`. Deleting the light in the vendor app does
   **not** reset it.

## Provisioning summary

Standard SIG provisioning (PB-GATT) works with any compliant provisioner:

1. Factory-reset the light (power-cycle 3×).
2. Provision with your own NetKey/AppKey (e.g. `lib/provision_and_toggle.py
   --transport local`). One element; algorithms: FIPS P-256; no OOB.
3. AppKey Add + bind to models `0x1000`, `0x1300`, `0x1303`, `0x1304`
   (`finish_nordlux.py` does this and runs a live demo).
4. Control with the table above (`nordlux_light.py`).

## Raw examples (on-air access payload, hex)

```
ON   : 825f 0000 1027 0000 <tid> 00 01     (lightness 0, temp 10000)
OFF  : 825f 0000 983a 0000 <tid> 00 01     (lightness 0, temp 15000)
BRI  : 825f 3200 8503 0000 <tid> 04 01     (lightness 50, temp 901)
CCT  : 825f 6500 2103 0000 <tid> 04 01     (lightness 101, temp 801 = full warm)
```
