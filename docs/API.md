# Phase 1 — Backend API (Frontend contract)

Backend: FastAPI at `http://localhost:8000`. The frontend renders the **Who's-Stuck grid** from snapshots pushed over WebSocket.

## WebSocket — `ws://localhost:8000/ws`
On connect the server immediately sends a full **snapshot**, then re-sends a full snapshot on every change and on a ~1s heartbeat. The frontend just re-renders from the latest snapshot (no delta merging needed).

Snapshot JSON:
```json
{
  "type": "snapshot",
  "ts": 1718900000.0,
  "session": { "sid": "s1", "activity": "color-quiz", "q": 3 },
  "counts": { "working": 9, "idle": 1, "stuck": 2, "done": 2, "help": 1, "offline": 0 },
  "mastery": { "n": 25, "correct": 18, "rate": 0.72 },
  "devices": [
    {
      "id": "r4-0007",
      "seat_no": 7,
      "group": "A",
      "seat_color": "#f59e0b",
      "state": "help",          // EFFECTIVE state — use THIS for the tile color
      "raw_state": "help",      // device-reported (help|working|idle|done)
      "act": "color-quiz",
      "q": 3,
      "last_answer": { "choice": 3, "correct": false },  // or null
      "rssi": -61,
      "uptime_s": 300,
      "since": 1718899958.0,        // epoch when current state began
      "stuck_for_s": 0,             // seconds past stuck threshold (0 if not stuck)
      "help_for_s": 42,             // seconds since help raised (0 if not help)
      "online": true
    }
  ]
}
```

### Effective state values (`state`) → tile color
| state | meaning | color |
|---|---|---|
| `idle` | waiting | `#e2e8f0` (gray) |
| `working` | in progress | `#93c5fd` (blue) |
| `stuck` | no progress (DERIVED) | `#fef3c7` (amber) |
| `done` | finished | `#a7f3d0` (green) |
| `help` | child pressed help | `#fee2e2` (red, thick border) |
| `offline` | disconnected | `#f1f5f9` (faded) |

**Tile sort order:** `help` → `stuck` → `working` → `idle` → `done` → `offline` (attention first). Provide a toggle for seat-number order.

## REST
- `GET /api/state` → the same snapshot object (for initial load / polling fallback).
- `POST /api/cmd` → publishes an MQTT command. Body:
```json
{ "target": { "type": "device", "id": "r4-0007" },   // type: device | group | all
  "cmd": "feedback",                                   // feedback|hint|freeze|resume|push_activity
  "payload": { "led": "green", "blink": 2, "sound": "chime", "ms": 800 } }
```
Returns `{ "ok": true, "topic": "edu/site1/r4-0007/cmd/feedback" }`.

## Frontend requirements (Phase 1)
- Grid of tiles, one per device, colored by **effective `state`**. `help` gets a thick red border; sort attention-first by default with a seat-order toggle.
- Top legend with live counts; bottom bar with mastery (`정답률 {rate}% ({correct}/{n})`).
- Click a tile → detail panel (state, activity/q, last_answer, rssi/uptime) + action buttons that `POST /api/cmd`:
  - **힌트 보내기** → cmd `hint` `{level:1}`
  - **빛+소리 피드백** → cmd `feedback` `{led:"green",blink:2,sound:"chime",ms:800}`
  - **개별 멈춤** → cmd `freeze` `{freeze:true}`
- Global action bar: **활동 푸시** (cmd `push_activity` to `all`), **전체 멈춤** (cmd `freeze` to `all`), **재개** (cmd `resume` to `all`).
- Reference visual: `docs/assets/whos-stuck-wireframe.png`.

## Phase 2–4 additions

The snapshot now also carries:
```json
{
  "mastery_by_q": [ {"q":1,"answered":15,"correct":11,"rate":0.73}, ... ],
  "groups": [ {"id":"A","counts":{...},"n":8,"answered":7,"correct":5,"rate":0.71}, ... ],
  "devices": [ { "...": "...", "fb": "feedback" } ]   // fb: "feedback"|"hint"|null (transient ~3s)
}
```

Commands (`POST /api/cmd`) gained:
- `target.type: "group"` with `id` = group id → publishes `edu/site1/group/<id>/cmd/<cmd>`.
- `cmd: "push_activity"` payload `{ "act": "shapes-quiz" }` → resets targeted boards to working, q=1, new activity.
- `cmd: "pace"` payload `{ "segment": 1, "timer": 60 }` → pacing hint (accepted).

Frontend additions (Phase 2–4):
- **Group view toggle**: section devices by `group` with per-group counts + per-group action buttons (활동 푸시 / 전체 멈춤 to that group via `target:{type:"group",id}`).
- **Mastery-by-question**: small per-question bars from `mastery_by_q` (정답률 by 문항).
- **Feedback badge**: when a device's `fb` is set, show a transient badge on its tile (🔔 피드백 / 💡 힌트) — confirms the teacher nudge reached the child.

## Run
Backend dev server is started by `run_dev.py` (broker+backend+simulator). Frontend dev: `npm run dev` (Vite), proxy `/api` and `/ws` to `localhost:8000`. Production: `npm run build` → served by backend at `/`.
