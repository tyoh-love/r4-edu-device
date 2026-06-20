<script setup>
import { computed } from 'vue'
import { stateMeta, fmtTime } from '../states.js'

const props = defineProps({
  device: { type: Object, default: null },
  busy: { type: Boolean, default: false }
})
const emit = defineEmits(['cmd'])

const meta = computed(() => (props.device ? stateMeta(props.device.state) : null))

const stateLine = computed(() => {
  const d = props.device
  if (!d) return ''
  let s = meta.value.label
  if (d.state === 'help' && d.help_for_s > 0) s += ` (${fmtTime(d.help_for_s)})`
  else if (d.state === 'stuck' && d.stuck_for_s > 0) s += ` (${fmtTime(d.stuck_for_s)})`
  return s
})

const answerLine = computed(() => {
  const a = props.device && props.device.last_answer
  if (!a) return '—'
  return `${a.choice}번 ${a.correct ? '(정답)' : '(오답)'}`
})

function send(cmd, payload) {
  emit('cmd', { cmd, payload })
}
</script>

<template>
  <aside class="panel">
    <template v-if="device">
      <h2 class="title">선택: {{ device.seat_no }}번 좌석</h2>
      <dl class="info">
        <div><dt>상태</dt><dd>{{ stateLine }}</dd></div>
        <div><dt>현재 활동</dt><dd>{{ device.act || '—' }} Q{{ device.q ?? '—' }}</dd></div>
        <div><dt>최근 답안</dt><dd>{{ answerLine }}</dd></div>
        <div><dt>연결</dt><dd>RSSI {{ device.rssi }} · 가동 {{ Math.round((device.uptime_s || 0) / 60) }}분</dd></div>
      </dl>

      <div class="actions">
        <button class="act hint" :disabled="busy" @click="send('hint', { level: 1 })">
          힌트 보내기 <span class="cmd">(cmd/hint)</span>
        </button>
        <button class="act feedback" :disabled="busy"
          @click="send('feedback', { led: 'green', blink: 2, sound: 'chime', ms: 800 })">
          빛+소리 피드백 <span class="cmd">(cmd/feedback)</span>
        </button>
        <button class="act freeze" :disabled="busy" @click="send('freeze', { freeze: true })">
          개별 멈춤 <span class="cmd">(cmd/freeze)</span>
        </button>
      </div>
    </template>
    <template v-else>
      <p class="empty">타일을 선택하면 상세 정보가 표시됩니다.</p>
    </template>
  </aside>
</template>

<style scoped>
.panel {
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
  width: 280px;
  flex: none;
  align-self: flex-start;
}
.title { color: #7c3aed; font-size: 17px; margin: 0 0 14px; }
.info { margin: 0 0 18px; }
.info > div { display: flex; gap: 8px; padding: 5px 0; font-size: 14px; }
.info dt { color: var(--muted); width: 72px; flex: none; }
.info dd { margin: 0; font-weight: 500; }
.actions { display: flex; flex-direction: column; gap: 10px; }
.act {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 12px;
  font-size: 14px;
  font-weight: 600;
  text-align: left;
  background: #f8fafc;
}
.act .cmd { color: var(--muted); font-weight: 400; font-size: 12px; }
.act.hint { background: #ede9fe; border-color: #c4b5fd; }
.act.feedback { background: #dcfce7; border-color: #86efac; }
.act.freeze { background: #ffedd5; border-color: #fdba74; }
.empty { color: var(--muted); font-size: 14px; }
</style>
