#!/usr/bin/env python3
"""Nordlux gym ceiling lights — control CLI.

Fully local control over our own Bluetooth SIG Mesh network, using the
Yankon/Nordlux vendor command encoding (reverse-engineered from the
Nordlux Smart Light Android app, see README.md).

Commands are sent as Light CTL Set Unacknowledged (opcode 0x825F) with the
Yankon multiplexed payload: lightness(2 LE), temperature(2 LE), delta_uv(2 LE),
tid(1), transition(1), delay(1).

  ON          (0,   10000, tr=0x00)
  OFF         (0,   15000, tr=0x00)
  Brightness  (1-100, 901,  tr=0x04)   # 901 = CONTROL_CCT marker
  Color temp  (101, 801-900, tr=0x04)  # bri=101 = CONTROL_BRI marker; 801=warm, 900=cool

IMPORTANT: TIDs must never repeat (Telink-style replay cache drops them);
the counter is persisted in nordlux_mesh_state.json.

Usage:
    python nordlux_light.py <1|2|all> on
    python nordlux_light.py <1|2|all> off
    python nordlux_light.py <1|2|all> bri <0-100>
    python nordlux_light.py <1|2|all> cct <0-100>     # 0=warm, 100=cool
    python nordlux_light.py <1|2|all> state
"""
from __future__ import annotations
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
LIB = HERE / "lib"                  # vendored btmesh + provisioning harness
STATE_FILE = HERE / "mesh_state.json"   # gitignored — contains your mesh keys

sys.path.insert(0, str(LIB))
spec = importlib.util.spec_from_file_location(
    "harness", LIB / "provision_and_toggle.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

from btmesh.access import OP_LIGHT_CTL_STATUS, light_ctl_get, encode_opcode  # noqa: E402
from btmesh.bearer import find_proxy_node  # noqa: E402
from btmesh.crypto import k3  # noqa: E402
from btmesh.node import MeshNode  # noqa: E402
from btmesh.proxy_pdu import MSG_TYPE_NETWORK_PDU  # noqa: E402
from btmesh.pump import BearerPump  # noqa: E402

UNICASTS = {"1": 0x0002, "2": 0x0003}
OP_CTL_SET_UNACK = 0x825F
CCT_FLOOR, CCT_CEIL = 801, 900  # firmware rejects anything outside


def load_state():
    return json.loads(STATE_FILE.read_text())


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def next_tid(state):
    state["tid"] = (state.get("tid", 99) + 1) & 0xFF
    return state["tid"]


def ctl_cmd(state, bri, temp, transition):
    payload = (encode_opcode(OP_CTL_SET_UNACK)
               + bri.to_bytes(2, "little")
               + temp.to_bytes(2, "little")
               + (0).to_bytes(2, "little")
               + bytes([next_tid(state), transition, 0x01]))
    if bri == 0 and temp in (10000, 15000):
        return payload, "ON" if temp == 10000 else "OFF"
    if bri == 101:
        return payload, f"CCT {temp}"
    return payload, f"BRI {bri}%"


async def control(unicast: int, entry: dict, state: dict, action, value=None):
    netkey = bytes.fromhex(state["netkey"])
    appkey = bytes.fromhex(state["appkey"])
    transport = harness.LocalTransport()
    scanner = transport.scanner()
    _, cands = await find_proxy_node(scanner, k3(netkey), timeout=15.0)
    ours = [c for c in cands if c.device.address == entry["address"]]
    if not ours:
        print(f"0x{unicast:04x}: no proxy advert in range")
        return
    client, bearer = await harness.open_gatt_session(
        transport, ours[0].device, provisioning=False,
        on_message=lambda mt, p: session and session[0](mt, p))
    session: list = []
    pump = BearerPump(bearer, MSG_TYPE_NETWORK_PDU)
    node = MeshNode(netkey=netkey, appkey=appkey, iv_index=state["iv_index"],
                    src_addr=state["provisioner_addr"],
                    send_network_pdu=lambda raw: (pump.put(raw), state.update(seq=node.ctx.seq)),
                    seq=state["seq"])
    node.add_device(unicast, bytes.fromhex(entry["device_key"]))
    session.append(lambda mt, p: mt == MSG_TYPE_NETWORK_PDU and node.handle_network_pdu(p))
    pump.start()
    try:
        if action == "state":
            r = await node.request(unicast, light_ctl_get(), OP_LIGHT_CTL_STATUS, timeout=5)
            bri = int.from_bytes(r.params[0:2], "little")
            cct = int.from_bytes(r.params[2:4], "little")
            if bri == 0 and cct == 15000:
                print(f"0x{unicast:04x}: OFF")
            else:
                pct = 0 if cct < CCT_FLOOR else round((cct - CCT_FLOOR) / (CCT_CEIL - CCT_FLOOR) * 100)
                print(f"0x{unicast:04x}: bri={bri}% cct={pct}% (raw {cct})"
                      + (" [off]" if bri == 0 else ""))
            return

        def expected_ok(bri, cct):
            """Check a readback against the command's expected result."""
            if action == "off":
                return bri == 0
            if action == "on":
                return bri != 0
            if action == "bri":
                return bri == (int(value) if int(value) > 0 else 1)
            if action == "cct":
                return cct == CCT_FLOOR + round((CCT_CEIL - CCT_FLOOR) * max(0, min(100, int(value))) / 100)
            return True

        def build(transition):
            if action == "on":
                return ctl_cmd(state, 0, 10000, transition)
            if action == "off":
                return ctl_cmd(state, 0, 15000, transition)
            if action == "bri":
                v = max(0, min(100, int(value)))
                return ctl_cmd(state, v if v > 0 else 1, 901, transition)
            if action == "cct":
                v = max(0, min(100, int(value)))
                return ctl_cmd(state, 101, CCT_FLOOR + round((CCT_CEIL - CCT_FLOOR) * v / 100), transition)

        label = None
        for attempt, transition in enumerate((0x04, 0x00, 0x00), start=1):
            payload, label = build(transition)
            node.send_access(unicast, payload)
            await asyncio.sleep(2.5)
            r = await node.request(unicast, light_ctl_get(), OP_LIGHT_CTL_STATUS, timeout=5)
            bri = int.from_bytes(r.params[0:2], "little")
            cct = int.from_bytes(r.params[2:4], "little")
            if expected_ok(bri, cct):
                print(f"0x{unicast:04x}: {label} ✓ (verified)")
                return
            print(f"0x{unicast:04x}: {label} not applied (bri={bri} cct={cct}), "
                  + (f"retry without fade ({attempt}/3)" if attempt < 3 else "GAVE UP"))
        print(f"0x{unicast:04x}: WARNING — command may not have applied")
    finally:
        await pump.stop()
        await bearer.stop()
        try:
            await client.disconnect()
        except Exception:
            pass


async def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[0] not in (*UNICASTS, "all") or \
       args[1] not in ("on", "off", "bri", "cct", "state"):
        raise SystemExit(__doc__)
    action = args[1]
    value = args[2] if len(args) > 2 else None
    if action in ("bri", "cct") and value is None:
        raise SystemExit(f"{action} requires a value 0-100")

    state = load_state()
    try:
        targets = [UNICASTS[args[0]]] if args[0] != "all" else list(UNICASTS.values())
        for unicast in targets:
            entry = state["devices"][f"0x{unicast:04x}"]
            await control(unicast, entry, state, action, value)
    finally:
        state["seq"] += 16  # leave headroom for next session
        save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
