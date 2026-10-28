# nordlux-ble-mesh

**Local, cloud-free control of Nordlux Smart Light fixtures — and any other
light running the Yankon "YANKON-NX" / `smbt5` Bluetooth Mesh firmware on
PHYplus PHY6222 silicon.**

These are the "app-only" ceiling lights and bulbs (Nordlux Smart, MEGAMAN
Infinite IoT Lighting, and other brands white-labeling the same Chinese
controller) that Home Assistant cannot talk to: their Bluetooth SIG Mesh
stack *answers* standard lighting commands with correct status replies, but
**silently ignores them when driving the LEDs**. The real control protocol is
a vendor payload hidden inside `Light CTL Set Unacknowledged`, which this
project fully reverse-engineered from the official Android app.

Result: on/off, brightness (1–100 %) and color temperature (warm↔cool) work,
fully local, over a mesh network **you provision and own** — no vendor app,
no cloud, no bridge.

## What's inside

| Path | What it is |
|---|---|
| `nordlux_light.py` | **Control CLI** with verify-and-retry: `on / off / bri / cct / state` |
| `finish_nordlux.py` | Post-provisioning: AppKey add + model binds + demo |
| `lib/btmesh/` | Pure-Python SIG Mesh stack (vendored, MIT — see `lib/NOTICE.md`) |
| `lib/provision_and_toggle.py` | PB-GATT provisioning harness (vendored + Nordlux patch) |
| `docs/protocol.md` | **The full protocol** — command table, quirks, reverse-engineering notes |
| `esphome/bluetooth-proxy.yaml` | ESP32-C3 ESPHome Bluetooth proxy config (for Home Assistant) |
| `mesh_state.json`, `mesh.connect.json` | *Your* keys — created by provisioning, **gitignored** |

## Quickstart

Works from any Mac/Linux box with Bluetooth (tested on macOS + [bleak]).
Python ≥ 3.12.

```bash
pip install -r requirements.txt

# 1. Factory-reset a light: wall switch OFF/ON 3×, 1–2 s apart.
#    It will advertise as unprovisioned (service 0x1827, UUID "nx00…").

# 2. Provision it into your own mesh (repeat per light, same state file):
python lib/provision_and_toggle.py --transport local \
    --state mesh_state.json --device-uuid <16-byte-uuid-from-scan> --verbose

# 3. Bind the lightness/CTL models (first time only):
python finish_nordlux.py

# 4. Control it:
python nordlux_light.py 1 on          # light 1 (unicast 0x0002)
python nordlux_light.py all bri 50    # both lights, 50 %
python nordlux_light.py all cct 0     # full warm (0=2200K-ish warm, 100=cool)
python nordlux_light.py all state     # read back bri/cct from the lights
```

Every command is **verified by reading the light's state back** and retried
without fade if the firmware dropped it (it occasionally does — see protocol
notes).

## The protocol in one table

Sent as **Light CTL Set Unacknowledged** (opcode `0x825F`), payload
`lightness(2 LE) + temperature(2 LE) + delta_uv(2 LE) + tid(1) + transition(1) + delay(1)`:

| Function | lightness | temperature | transition |
|---|---|---|---|
| ON | 0 | **10000** | 0x00 |
| OFF | 0 | **15000** | 0x00 |
| Brightness % | **1–100** | **901** | 0x04 |
| Color temperature | **101** | **801–900** (801=warm, 900=cool) | 0x04 |

Gotchas (all verified on-air):

- **TIDs must never repeat** — the replay cache drops duplicates for far
  longer than the spec's 6 s. Keep a persistent monotonically increasing TID.
- **CCT below 801 is silently rejected** (the app's own 0 % = 800 does nothing).
- Standard SIG messages (Generic OnOff, Light Lightness/CTL Set) update the
  internal state machine and are acknowledged — but never change the LEDs.
- State readback works via standard `Light CTL Get`: lightness = brightness %,
  temperature = raw CCT (801–900). ON restores the previous brightness.
- Full details, plus the vendor-model (`0xC5`) variant the app uses:
  `docs/protocol.md`.

## Hardware identification

- **Chip**: PHYplus **PHY6222** (BLE 5 SoC)
- **Firmware**: **Yankon** (Zhejiang Yankon Group) white-label `smbt5` /
  "YANKON-NX" stack — Android app package `com.nx.smbt5.a.android`
  (Nordlux) / `com.megaman.professional.smbt5.a.android` (MEGAMAN)
- **Mesh identity**: CID `0x0504` (unregistered), PID `0x6212`;
  SIG models `0x1000/0x1300/0x1303/0x1304/0x1306` + vendor model `0x1111:0x3333`
- Unprovisioned devices advertise service `0x1827` with a device UUID
  starting ASCII `"nx00"` + serial + MAC — filter on that.

## Home Assistant integration

Plan (in progress): ESP32-C3 running ESPHome `bluetooth_proxy` near the
lights + a small custom HA integration that reuses `lib/btmesh` (it runs
transparently over ESPHome proxies) and sends the Yankon payload above.

⚠️ The stock [`ha-bluetooth-mesh`](https://github.com/dasimon135/ha-bluetooth-mesh)
integration alone will **not** drive these LEDs (standard models are ignored
by the LED driver) — the Yankon payload layer is required.

## Credits

- [dasimon135/ha-bluetooth-mesh](https://github.com/dasimon135/ha-bluetooth-mesh) — the `btmesh` stack and provisioning harness (MIT)
- [TheCamelt0e's HA community post](https://community.home-assistant.io/t/nordlux-smart-light-products/243545/21) — the original on/off/brightness magic values for a fixed-white Nordlux bulb; this project adds color temperature, the TID/replay findings, the firmware mode/verify quirks, and provisioning tooling
- The `smbt5` command constants extracted from the decompiled Nordlux Android app

## License

MIT — see `LICENSE`. Vendored third-party code: see `lib/NOTICE.md`.

*Interoperability research on hardware its owner paid for. Contains no
vendor keys, app code, or cloud credentials — your mesh, your keys.*
