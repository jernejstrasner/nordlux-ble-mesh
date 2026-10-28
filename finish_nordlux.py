"""Bind Light Lightness/CTL models on both Nordlux mesh lights and demo them.

Reuses the phase0 harness helpers. Reads the same state file, connects the
GATT proxy to whichever provisioned light is advertising, binds 0x1300 and
0x1303 (and 0x1304) on BOTH unicasts, then runs a visible demo:
  50% -> 100% brightness, then cool white -> warm white -> neutral.
"""
import asyncio
import importlib.util
import json
import time
from pathlib import Path

HERE = Path(__file__).parent
LIB = HERE / "lib"
import sys
sys.path.insert(0, str(LIB))

# load the phase0 harness as a module to reuse its helpers
spec = importlib.util.spec_from_file_location(
    "provision_harness", LIB / "provision_and_toggle.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

from btmesh.access import (
    MODEL_LIGHT_LIGHTNESS_SERVER,
    MODEL_LIGHT_CTL_SERVER,
    MODEL_LIGHT_CTL_TEMPERATURE_SERVER,
    OP_CONFIG_MODEL_APP_STATUS,
    OP_LIGHT_LIGHTNESS_STATUS,
    OP_LIGHT_CTL_STATUS,
    OP_LIGHT_CTL_TEMPERATURE_RANGE_STATUS,
    config_model_app_bind,
    parse_config_model_app_status,
    parse_light_lightness_status,
    light_lightness_set,
    light_ctl_set,
    light_ctl_temperature_range_get,
    encode_opcode,
)
from btmesh.bearer import find_proxy_node
from btmesh.node import MeshNode
from btmesh.provisioner import Provisioner  # noqa: F401 (unused, documents deps)
from btmesh.proxy_pdu import MSG_TYPE_NETWORK_PDU
from btmesh.pump import BearerPump
from btmesh.crypto import k3

STATE = HERE / "mesh_state.json"
MODELS_TO_BIND = [
    (MODEL_LIGHT_LIGHTNESS_SERVER, "Light Lightness Server"),
    (MODEL_LIGHT_CTL_SERVER, "Light CTL Server"),
    (MODEL_LIGHT_CTL_TEMPERATURE_SERVER, "Light CTL Temperature Server"),
]


async def main() -> None:
    state = json.loads(STATE.read_text())
    netkey = bytes.fromhex(state["netkey"])
    appkey = bytes.fromhex(state["appkey"])
    transport = harness.LocalTransport()

    tid = 0

    def next_tid():
        nonlocal tid
        tid = (tid + 1) & 0xFF
        return tid

    async def per_light(unicast: int, entry: dict) -> None:
        addr = entry["address"]
        print(f"\n=== Node 0x{unicast:04x} via {addr} ===")
        # scan briefly for this specific node's proxy advert
        scanner = transport.scanner()
        _, candidates = await find_proxy_node(scanner, k3(netkey), timeout=15.0)
        ours = [c for c in candidates if c.device.address == addr]
        if not ours:
            print(f"  !! no proxy advert from {addr}; skipping (mesh relay may still work)")
            return
        target = ours[0].device

        session_handler: list = []

        def dispatch(msg_type, payload):
            if session_handler:
                session_handler[0](msg_type, payload)

        client, bearer = await harness.open_gatt_session(
            transport, target, provisioning=False, on_message=dispatch
        )
        pump = BearerPump(bearer, MSG_TYPE_NETWORK_PDU)
        pump.on_error = lambda exc: print(f"  TX error: {exc}")

        def send_network_pdu(raw: bytes) -> None:
            pump.put(raw)
            state["seq"] = node.ctx.seq
            json.dump(state, open(STATE, "w"), indent=2)

        node = MeshNode(
            netkey=netkey, appkey=appkey, iv_index=state["iv_index"],
            src_addr=state["provisioner_addr"], send_network_pdu=send_network_pdu,
            seq=state["seq"],
        )
        node.add_device(unicast, bytes.fromhex(entry["device_key"]))

        def on_message(msg_type, payload):
            if msg_type == MSG_TYPE_NETWORK_PDU:
                node.handle_network_pdu(payload)

        session_handler.append(on_message)
        pump.start()
        try:
            print("--- Binding lightness/CTL models ---")
            for model_id, name in MODELS_TO_BIND:
                try:
                    resp = await node.request(
                        unicast, config_model_app_bind(unicast, state["appkey_index"], model_id),
                        OP_CONFIG_MODEL_APP_STATUS, dev_key=True, timeout=10,
                    )
                    st = parse_config_model_app_status(encode_opcode(resp.opcode) + resp.params)
                    print(f"  bind 0x{model_id:04x} {name}: "
                          f"{'Success' if st.status == 0 else f'STATUS 0x{st.status:02x}'}")
                except TimeoutError:
                    print(f"  bind 0x{model_id:04x} {name}: TIMEOUT")

            print("--- DEMO: watch this light (2 s steps) ---")
            try:
                resp = await node.request(unicast, light_ctl_temperature_range_get(),
                                          OP_LIGHT_CTL_TEMPERATURE_RANGE_STATUS, timeout=5)
                print(f"  CTL temp range raw: {resp.params.hex()}")
            except TimeoutError:
                print("  CTL temp range: no reply")

            steps = [
                ("brightness 50%", lambda u: node.request(
                    u, light_lightness_set(0x8000, next_tid()), OP_LIGHT_LIGHTNESS_STATUS, timeout=5)),
                ("brightness 100%", lambda u: node.request(
                    u, light_lightness_set(0xFFFF, next_tid()), OP_LIGHT_LIGHTNESS_STATUS, timeout=5)),
                ("cool white 6500K", lambda u: node.request(
                    u, light_ctl_set(0xFFFF, 6500, 0, next_tid()), OP_LIGHT_CTL_STATUS, timeout=5)),
                ("warm white 2700K", lambda u: node.request(
                    u, light_ctl_set(0xFFFF, 2700, 0, next_tid()), OP_LIGHT_CTL_STATUS, timeout=5)),
                ("settle: 100% neutral 4000K", lambda u: node.request(
                    u, light_ctl_set(0xFFFF, 4000, 0, next_tid()), OP_LIGHT_CTL_STATUS, timeout=5)),
            ]
            for label, fn in steps:
                try:
                    t0 = time.perf_counter()
                    await fn(unicast)
                    print(f"  [{label}] ok ({(time.perf_counter() - t0) * 1000:.0f} ms)")
                except TimeoutError:
                    print(f"  [{label}] TIMEOUT")
                await asyncio.sleep(2.0)
        finally:
            await pump.stop()
            await bearer.stop()
            try:
                await client.disconnect()
            except Exception:
                pass

    for addr_hex, entry in state["devices"].items():
        await per_light(int(addr_hex, 16), entry)

    print("\n=== ALL BINDS + DEMOS COMPLETE ===")


asyncio.run(main())
