# Vendored third-party code

## `btmesh/` and `provision_and_toggle.py`

Source: https://github.com/dasimon135/ha-bluetooth-mesh
License: MIT (see below), © dasimon135 / David Simon

The `btmesh/` directory is the pure-Python Bluetooth SIG Mesh stack, and
`provision_and_toggle.py` is the PB-GATT provisioning harness from that
project's `phase0/` directory.

Local modification to `provision_and_toggle.py`: `_find_proxy_target()` was
patched to select between multiple "Node Identity" (type 0x01) proxy
advertisers by matching the BLE address recorded for the node's unicast
address at provisioning time. The upstream code refuses to guess when more
than one node advertises Node Identity instead of Network ID.

MIT license text (upstream):

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
