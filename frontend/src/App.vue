<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import DeviceTile from './components/DeviceTile.vue'
import DetailPanel from './components/DetailPanel.vue'
import { stateMeta, LEGEND_STATES, STATE_META } from './states.js'

const snapshot = ref(null)
const connected = ref(false)
const selectedId = ref(null)
const sortBySeat = ref(false)
const groupView = ref(false)
const busy = ref(false)

let ws = null
let reconnectTimer = null
let backoff = 1000

// ---- WebSocket ----------------------------------------------------------
function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  // location.host is empty for file:// — fall back to dev backend.
  const host = location.host || 'localhost:8000'
  return `${proto}://${host}/ws`
}

function connect() {
  try {
    ws = new WebSocket(wsUrl())
  } catch (e) {
    scheduleReconnect()
    return
  }
  ws.onopen = () => {
    connected.value = true
    backoff = 1000
  }
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg && msg.type === 'snapshot') snapshot.value = msg
    } catch (_) { /* ignore malformed */ }
  }
  ws.onclose = () => {
    connected.value = false
    scheduleReconnect()
  }
  ws.onerror = () => {
    try { ws.close() } catch (_) {}
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    backoff = Math.min(backoff * 1.5, 10000)
    connect()
  }, backoff)
}

onMounted(() => {
  // Initial REST load so the grid populates even before the first WS push.
  fetch('/api/state')
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d && d.type === 'snapshot' && !snapshot.value) snapshot.value = d })
    .catch(() => {})
  connect()
})

onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (ws) { ws.onclose = null; try { ws.close() } catch (_) {} }
})

// ---- Derived ------------------------------------------------------------
const session = computed(() => snapshot.value?.session || {})
const counts = computed(() => snapshot.value?.counts || {})
const mastery = computed(() => snapshot.value?.mastery || { n: 0, correct: 0, rate: 0 })

function sortDevices(list) {
  const arr = [...list]
  if (sortBySeat.value) {
    arr.sort((a, b) => (a.seat_no || 0) - (b.seat_no || 0))
  } else {
    arr.sort((a, b) => {
      const oa = stateMeta(a.state).order
      const ob = stateMeta(b.state).order
      if (oa !== ob) return oa - ob
      return (a.seat_no || 0) - (b.seat_no || 0)
    })
  }
  return arr
}

const sortedDevices = computed(() => sortDevices(snapshot.value?.devices || []))

const groups = computed(() => snapshot.value?.groups || [])

const groupedSections = computed(() =>
  groups.value.map((g) => ({
    group: g,
    devices: sortDevices((snapshot.value?.devices || []).filter((d) => d.group === g.id))
  }))
)

const masteryByQ = computed(() => snapshot.value?.mastery_by_q || [])

function masteryColor(rate) {
  if (rate >= 0.7) return '#22c55e'
  if (rate >= 0.4) return '#f59e0b'
  return '#ef4444'
}

function groupRateText(g) {
  return `정답률 ${Math.round((g.rate || 0) * 100)}% (${g.correct || 0}/${g.answered || 0})`
}

const selectedDevice = computed(() =>
  (snapshot.value?.devices || []).find((d) => d.id === selectedId.value) || null
)

const masteryText = computed(() => {
  const m = mastery.value
  return `정답률 ${Math.round((m.rate || 0) * 100)}% (${m.correct || 0}/${m.n || 0})`
})

const clock = ref(timeStr())
let clockTimer = null
function timeStr() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
onMounted(() => { clockTimer = setInterval(() => { clock.value = timeStr() }, 1000) })
onUnmounted(() => { if (clockTimer) clearInterval(clockTimer) })

// ---- Commands -----------------------------------------------------------
async function postCmd(target, cmd, payload) {
  busy.value = true
  try {
    await fetch('/api/cmd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, cmd, payload: payload || {} })
    })
  } catch (e) {
    // best-effort; backend may be unavailable in standalone preview
  } finally {
    busy.value = false
  }
}

function pushActivity() { postCmd({ type: 'all' }, 'push_activity', { act: 'shapes-quiz' }) }
function freezeAll() { postCmd({ type: 'all' }, 'freeze', { freeze: true }) }
function resumeAll() { postCmd({ type: 'all' }, 'resume', { freeze: false }) }

function pushGroupActivity(id) { postCmd({ type: 'group', id }, 'push_activity', { act: 'shapes-quiz' }) }
function freezeGroup(id) { postCmd({ type: 'group', id }, 'freeze', { freeze: true }) }

function onSelect(id) { selectedId.value = id }

function onDeviceCmd({ cmd, payload }) {
  if (!selectedId.value) return
  postCmd({ type: 'device', id: selectedId.value }, cmd, payload)
}

function legendMeta(s) { return STATE_META[s] }
</script>

<template>
  <div class="layout">
    <!-- Header -->
    <header class="header">
      <div class="title">
        교실 현황 <span class="dim">— {{ session.sid || '햇님반' }}</span>
        <span class="sep">·</span>
        <span class="dim">세션:</span> {{ session.activity || '—' }}
      </div>
      <div class="status">
        <span class="conn" :class="{ on: connected }">
          <span class="dot"></span>{{ connected ? '브로커 연결됨' : '연결 끊김' }}
        </span>
        <span class="clock">{{ clock }}</span>
      </div>
    </header>

    <!-- Legend -->
    <div class="legend">
      <span class="legend-title">상태</span>
      <span v-for="s in LEGEND_STATES" :key="s" class="legend-item">
        <span class="swatch" :style="{ background: legendMeta(s).color }"></span>
        {{ legendMeta(s).label }} {{ counts[s] || 0 }}
      </span>
      <button class="sort-toggle" @click="groupView = !groupView">
        {{ groupView ? '전체 보기' : '그룹 보기' }}
      </button>
      <button class="sort-toggle" @click="sortBySeat = !sortBySeat">
        {{ sortBySeat ? '주목 순' : '좌석 순' }} 보기
      </button>
    </div>

    <!-- Main: grid + detail -->
    <main class="main">
      <section class="grid-wrap">
        <!-- Group view -->
        <template v-if="groupView">
          <div v-for="sec in groupedSections" :key="sec.group.id" class="group-section">
            <div class="group-header">
              <div class="group-id">{{ sec.group.id }}조</div>
              <div class="group-meta">
                <span class="group-counts">{{ sec.group.n || 0 }}명</span>
                <span v-for="s in LEGEND_STATES" :key="s" class="group-count-item">
                  <span class="swatch sm" :style="{ background: legendMeta(s).color }"></span>
                  {{ legendMeta(s).label }} {{ (sec.group.counts && sec.group.counts[s]) || 0 }}
                </span>
                <span class="group-rate">{{ groupRateText(sec.group) }}</span>
              </div>
              <div class="group-actions">
                <button class="gg push" :disabled="busy" @click="pushGroupActivity(sec.group.id)">활동 푸시</button>
                <button class="gg freeze" :disabled="busy" @click="freezeGroup(sec.group.id)">전체 멈춤</button>
              </div>
            </div>
            <div class="grid">
              <DeviceTile
                v-for="d in sec.devices"
                :key="d.id"
                :device="d"
                :selected="d.id === selectedId"
                @select="onSelect"
              />
            </div>
          </div>
          <p v-if="!groupedSections.length" class="empty-grid">
            {{ connected ? '그룹 정보가 없습니다.' : '서버에 연결 중…' }}
          </p>
        </template>

        <!-- Flat view -->
        <template v-else>
          <div class="grid">
            <DeviceTile
              v-for="d in sortedDevices"
              :key="d.id"
              :device="d"
              :selected="d.id === selectedId"
              @select="onSelect"
            />
          </div>
          <p v-if="!sortedDevices.length" class="empty-grid">
            {{ connected ? '기기가 없습니다.' : '서버에 연결 중…' }}
          </p>
        </template>

        <!-- Mastery by question -->
        <div v-if="masteryByQ.length" class="mastery-by-q">
          <div class="mbq-title">문항별 정답률</div>
          <div v-for="m in masteryByQ" :key="m.q" class="mbq-row">
            <span class="mbq-label">Q{{ m.q }}</span>
            <div class="mbq-track">
              <div class="mbq-fill" :style="{ width: Math.round((m.rate || 0) * 100) + '%', background: masteryColor(m.rate || 0) }"></div>
            </div>
            <span class="mbq-val">{{ Math.round((m.rate || 0) * 100) }}% ({{ m.correct || 0 }}/{{ m.answered || 0 }})</span>
          </div>
        </div>
      </section>

      <DetailPanel :device="selectedDevice" :busy="busy" @cmd="onDeviceCmd" />
    </main>

    <!-- Bottom action bar -->
    <footer class="actionbar">
      <div class="global-actions">
        <button class="g push" :disabled="busy" @click="pushActivity">활동 푸시</button>
        <button class="g freeze" :disabled="busy" @click="freezeAll">전체 멈춤 (주목)</button>
        <button class="g resume" :disabled="busy" @click="resumeAll">재개</button>
      </div>
      <div class="mastery">{{ masteryText }}</div>
    </footer>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 14px;
  gap: 12px;
  max-width: 1100px;
  margin: 0 auto;
}

/* Header */
.header {
  background: var(--header-bg);
  color: var(--header-fg);
  border-radius: 12px;
  padding: 12px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header .title { font-size: 17px; font-weight: 700; }
.header .dim { color: #9fb0c3; font-weight: 500; }
.header .sep { margin: 0 8px; color: #5b6878; }
.status { display: flex; align-items: center; gap: 18px; }
.conn { display: inline-flex; align-items: center; gap: 7px; font-size: 14px; color: #fca5a5; }
.conn.on { color: #86efac; }
.conn .dot { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
.clock { font-variant-numeric: tabular-nums; font-size: 15px; }

/* Legend */
.legend {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 4px 6px;
}
.legend-title { color: var(--muted); font-weight: 600; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 500; }
.swatch { width: 16px; height: 16px; border-radius: 4px; border: 1px solid rgba(0, 0, 0, 0.12); }
.sort-toggle {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
}
.sort-toggle:first-of-type { margin-left: auto; }

/* Main */
.main { display: flex; gap: 14px; align-items: flex-start; flex: 1; }
.grid-wrap { flex: 1; min-width: 0; }
.grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.empty-grid { color: var(--muted); text-align: center; padding: 40px 0; }

/* Group view */
.group-section { margin-bottom: 18px; }
.group-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 6px 4px 10px;
}
.group-id { font-size: 16px; font-weight: 700; }
.group-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 13px; color: var(--muted); }
.group-count-item { display: inline-flex; align-items: center; gap: 5px; }
.swatch.sm { width: 12px; height: 12px; }
.group-rate { font-weight: 600; color: #334155; }
.group-actions { display: flex; gap: 8px; margin-left: auto; }
.gg {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
}
.gg.push { background: #dcfce7; border-color: #86efac; }
.gg.freeze { background: #fee2e2; border-color: #fca5a5; }

/* Mastery by question */
.mastery-by-q {
  margin-top: 16px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
}
.mbq-title { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
.mbq-row { display: flex; align-items: center; gap: 10px; padding: 3px 0; font-size: 13px; }
.mbq-label { width: 32px; flex: none; font-weight: 600; font-variant-numeric: tabular-nums; }
.mbq-track {
  flex: 1;
  height: 12px;
  background: #e2e8f0;
  border-radius: 6px;
  overflow: hidden;
}
.mbq-fill { height: 100%; border-radius: 6px; transition: width 0.2s ease; }
.mbq-val { width: 120px; flex: none; text-align: right; font-variant-numeric: tabular-nums; color: #475569; }

/* Action bar */
.actionbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  gap: 16px;
}
.global-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.g {
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 10px 16px;
  font-size: 14px;
  font-weight: 600;
}
.g.push { background: #dcfce7; border-color: #86efac; }
.g.freeze { background: #fee2e2; border-color: #fca5a5; }
.g.resume { background: #e0e7ff; border-color: #a5b4fc; }
.mastery { font-size: 16px; font-weight: 700; white-space: nowrap; }

@media (max-width: 760px) {
  .grid { grid-template-columns: repeat(3, 1fr); }
  .main { flex-direction: column; }
  .panel { width: 100%; }
}
</style>
