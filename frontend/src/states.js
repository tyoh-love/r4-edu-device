// Effective state -> tile color, Korean label, sort priority. From docs/API.md.
export const STATE_META = {
  help:    { color: '#fee2e2', label: '도움요청', order: 0, border: true },
  stuck:   { color: '#fef3c7', label: '막힘',     order: 1 },
  working: { color: '#93c5fd', label: '진행중',   order: 2 },
  idle:    { color: '#e2e8f0', label: '대기',     order: 3 },
  done:    { color: '#a7f3d0', label: '완료',     order: 4 },
  offline: { color: '#f1f5f9', label: '오프라인', order: 5, faded: true }
}

// Legend display order (attention-first, matching the wireframe).
export const LEGEND_STATES = ['working', 'idle', 'stuck', 'done', 'help']

export function stateMeta(state) {
  return STATE_META[state] || { color: '#ffffff', label: state || '?', order: 9 }
}

// Seconds -> "m:ss"
export function fmtTime(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}
