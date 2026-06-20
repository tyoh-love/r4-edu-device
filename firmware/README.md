# R4 Swarm Firmware (Phase 5 — real device)

Arduino sketch for the **Arduino UNO R4 WiFi** that implements the same MQTT
contract the Phase-1 simulator (`sim/simulate.py`) and backend
(`server/contract.py`, `server/store.py`) speak. A flashed board is a drop-in
replacement for one simulated board in the Who's-Stuck grid.

```
firmware/
├── README.md            (this file)
└── r4_swarm/
    ├── r4_swarm.ino     main sketch (WiFi + MQTT + inputs + feedback + NTP)
    └── config.h         per-deployment + per-board constants (EDIT THIS)
```

## What it does (MQTT contract)

site = `site1`, device id = `r4-XXXX` (last 2 bytes of the WiFi MAC, lower hex).

| Topic | Payload | Retained | When |
|---|---|---|---|
| `edu/site1/<id>/meta`   | `{"group_id","seat_color","seat_no"}` | yes | once at (re)connect |
| `edu/site1/<id>/state`  | `{"st","act","q","since","idle_ms","seq"}` | yes | on change **and** ~5s heartbeat |
| `edu/site1/<id>/answer` | `{"choice","correct","act","q"}` | no | on each answer |
| `edu/site1/<id>/status` | `"online"` (birth) / `"offline"` (LWT) | yes | connect / ungraceful drop |

Subscribes `edu/site1/<id>/cmd/#` and reacts to the leaf command name:
`feedback` (LED+buzzer flash), `hint` (LED nudge), `freeze` (lock input),
`resume` (unlock), `push_activity` (reset to working, q=1, new activity).

The device only ever reports `idle|working|done|help`. **`stuck` is derived by
the backend** from `idle_ms` (`STUCK_THRESHOLD_MS = 30000`), so the firmware
recomputes `idle_ms = millis() - lastInput` fresh on every publish and keeps
heartbeating so the value climbs while the board stays online.

## Required libraries / board package

| Dependency | Version | Source | Notes |
|---|---|---|---|
| Board: `arduino:renesas_uno` | **>= 1.1.0** | Boards Manager / `arduino-cli core install` | <1.1.0 returned a zero / byte-reversed WiFi MAC; pin >= 1.1.0. Bundles `WiFiS3` + `WiFiUdp`. |
| `ArduinoMqttClient` | >= 0.1.8 | Library Manager (arduino-libraries) | **No auto-reconnect, no MQTT5.** Print-based publish API. |
| `ArduinoJson` | **>= 7.0** | Library Manager (bblanchon) | v7 `JsonDocument` idioms used (not v6 `StaticJsonDocument`). |
| `Arduino_LED_Matrix` | bundled w/ core | — | only if `USE_LED_MATRIX = 1` in config.h |

`WiFiS3`, `WiFiSSLClient`, and `WiFiUDP` ship inside the renesas core — no
separate install.

## Build

Install toolchain (one-time):

```bash
arduino-cli core update-index
arduino-cli core install arduino:renesas_uno      # the R4 board package (>=1.1.0)
arduino-cli lib install ArduinoMqttClient
arduino-cli lib install ArduinoJson
```

Edit `r4_swarm/config.h` (WiFi SSID/pass, broker IP, and the **seat assignment**
`SEAT_GROUP_ID` / `SEAT_COLOR` / `SEAT_NO` for this physical board), then:

```bash
arduino-cli compile --fqbn arduino:renesas_uno:unor4wifi firmware/r4_swarm
arduino-cli upload  --fqbn arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 firmware/r4_swarm
```

> The seat identity (group / colour / seat number) is a **human decision the
> board cannot infer** and lives in `config.h`. Only the device *id* is derived
> from the chip (MAC). One firmware image + per-board `config.h`, or inject the
> seat constants via `-D` build flags if you flash a single image to all boards.

## Pin map

Buttons are wired to GND with `INPUT_PULLUP` (a press reads **LOW**). Use
**physical buttons >= 2cm** — non-reader UX requirement (docs §4.2: large
single-press targets for pre-literate children).

| Function | Pin | Wiring |
|---|---|---|
| Answer 1 | D2 | button → GND (INPUT_PULLUP) |
| Answer 2 | D3 | button → GND |
| Answer 3 | D4 | button → GND |
| Answer 4 | D5 | button → GND |
| Help / "I'm stuck" | D6 | button → GND (300ms debounce — deliberate press) |
| Feedback LED | D13 (`LED_BUILTIN`) | onboard; or external LED + resistor |
| Buzzer | D9 | passive buzzer via `tone()` (PWM pin) |
| LED matrix | onboard 12×8 | optional, `USE_LED_MATRIX = 1` |

Answer buttons debounce at 40ms; the help button at 300ms (a deliberate press).

## TLS / mTLS

The R4 supports **server-auth TLS** but **NOT client-cert mTLS**
(`WiFiSSLClient` cannot present a client certificate — arduino renesas core
issue #499).

To switch to TLS on port 8883:

1. In `config.h` set `USE_TLS 1`, `BROKER_PORT 8883`, and paste your Mosquitto
   CA into `BROKER_CA_CERT`.
2. The sketch then compiles `WiFiSSLClient` instead of `WiFiClient` and calls
   `gNet.setCACert(BROKER_CA_CERT)` before connecting (server verification).

Because mTLS is impossible, use the documented compensating controls instead
(docs §6.5 / §7): **per-device user/pass** (set `MQTT_USER_IS_DEVICE_ID 1` so the
username equals the runtime device id, matching `infra/mosquitto/aclfile` `%u`),
**topic ACLs** confining each board to `edu/site1/<id>/#`, and **network
isolation (VLAN)**.

## Time (`since` / epoch)

NTP over `WiFiUDP` seeds the epoch clock used for the `state.since` field; it is
re-synced every 10 min because the R4 has no crystal and its RTC drifts ~2s/min.
If NTP never answers, the firmware falls back to a `millis()`-based pseudo-epoch
(`store.py` only compares `since` relatively, so this is acceptable for the grid).

## Reconnect behaviour

`ArduinoMqttClient` has **no auto-reconnect**. `loop()` calls `mqtt.poll()` every
iteration (keepalive + inbound dispatch) and runs a **non-blocking jittered
exponential backoff** (1s → 30s, ±25% jitter). On every (re)connect the firmware
re-arms the LWT *before* `connect()`, then publishes the `online` birth,
re-subscribes to `cmd/#`, and re-publishes retained `meta` + `state`.

## Local feedback (answer judging)

For the demo, `color-quiz` treats answer **choice 1 as correct** (`judge()` in
the sketch) so behaviour is deterministic and testable. A real activity would
carry the answer key in the `push_activity` command payload.
