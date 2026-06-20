<script setup>
import { computed } from 'vue'
import { stateMeta, fmtTime } from '../states.js'

const props = defineProps({
  device: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})
defineEmits(['select'])

const meta = computed(() => stateMeta(props.device.state))

const timerText = computed(() => {
  const d = props.device
  if (d.state === 'help' && d.help_for_s > 0) return fmtTime(d.help_for_s)
  if (d.state === 'stuck' && d.stuck_for_s > 0) return fmtTime(d.stuck_for_s)
  return ''
})

const labelText = computed(() => {
  const d = props.device
  if (d.state === 'help') return '도움요청!'
  if (d.state === 'done') return '완료 ✓'
  return meta.value.label
})

const fbText = computed(() => {
  const fb = props.device.fb
  if (fb === 'feedback') return '🔔 피드백'
  if (fb === 'hint') return '💡 힌트'
  return ''
})
</script>

<template>
  <button
    class="tile"
    :class="{ help: device.state === 'help', faded: meta.faded, selected }"
    :style="{ background: meta.color }"
    @click="$emit('select', device.id)"
  >
    <div v-if="fbText" class="fb-badge">{{ fbText }}</div>
    <div class="seat">
      <span v-if="device.state === 'help'" class="hand">✋</span>{{ device.seat_no }}번
    </div>
    <div class="label">{{ labelText }}</div>
    <div v-if="timerText" class="timer">{{ timerText }}</div>
  </button>
</template>

<style scoped>
.tile {
  position: relative;
  border: 2px solid rgba(0, 0, 0, 0.08);
  border-radius: 14px;
  min-height: 92px;
  padding: 10px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  text-align: center;
  color: #1f2733;
  transition: transform 0.08s ease, box-shadow 0.1s ease;
}
.fb-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  background: #1e293b;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 8px;
  white-space: nowrap;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
}
.tile:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12); }
.tile.help {
  border: 3px solid #ef4444;
}
.tile.faded { color: #94a3b8; }
.tile.selected { box-shadow: 0 0 0 3px #7c3aed; }
.seat { font-weight: 700; font-size: 15px; }
.hand { margin-right: 2px; }
.label { font-size: 13px; }
.timer { font-size: 12px; font-weight: 600; opacity: 0.85; }
</style>
