# 최우선 기능 설계 — Who's-Stuck 그리드 (교사 실시간 현황)

> 근거: 교사 오케스트레이션에서 근거가 가장 강한 기능(Lumilo, AIED 2018 — 실시간 "도움필요" 표시가 측정된 학습 향상으로 이어짐).
> 핵심 원칙(Dillenbourg): **보여주되 대신 판단하지 않는다.** 교사에게 주의 재배분의 단서를 주는 것이 목적.
> 와이어프레임: `whos-stuck-wireframe.png` 참고. 본 문서는 그 뒤의 토픽/페이로드/상태머신/집계 스펙.

---

## 1. 상태 모델 (5-state)

| state | 의미 | 누가 설정 | 타일 색 |
|---|---|---|---|
| `idle` | 활동 미시작·대기 | 디바이스 | 회색 |
| `working` | 진행 중(최근 입력 있음) | 디바이스 | 파랑 |
| `stuck` | 일정 시간 진전 없음 | **백엔드 자동 판정** | 황색 |
| `done` | 현재 활동 완료 | 디바이스 | 초록 |
| `help` | 아이가 도움 버튼 누름 | 디바이스(명시적) | 빨강(굵은 테두리) |
| *(offline)* | 연결 끊김 | **브로커 LWT** | 흐림/빗금 |

> **stuck vs help 구분이 설계의 핵심.** `help`는 아이의 *명시적* 요청(도움 버튼) — 즉시·확실. `stuck`은 *추론* — 디바이스가 "마지막 진전 후 N초"를 보고하거나 백엔드가 타이머로 판정. 둘을 분리해야 교사가 "손든 아이(즉시)"와 "조용히 막힌 아이(놓치기 쉬움)"를 모두 본다. 후자가 Lumilo가 증명한 가치.

---

## 2. 토픽 (기존 트리에 추가)

기존: `edu/{site}/{id}/{birth,status,health,telemetry,answer,cmd/+}`

```
edu/{site}/{id}/state          # 신규 ★ 핵심 — retained, QoS1
edu/{site}/{id}/meta           # 신규 — {group_id, seat_color} retained
edu/{site}/{id}/cmd/feedback   # 신규 — 교사→보드 빛/소리 넛지
edu/{site}/{id}/cmd/hint       # 신규 — 교사→보드 단계 힌트
edu/{site}/{id}/cmd/freeze     # 신규 — 개별 멈춤/재개
edu/{site}/group/{g}/cmd/+     # 신규 — push_activity|freeze|resume|pace
edu/{site}/group/{g}/mastery   # 신규 — 백엔드 집계 결과 (대시보드용)
edu/{site}/session/{sid}/+     # 신규 — start|end (활동 세션 경계)
```

`{id}` = 디바이스 chip-ID(RA4M1 128-bit UID 또는 ESP32-S3 MAC). **아동 이름·매핑은 토픽/페이로드에 절대 넣지 않음**(PIPA — §5 참조).

---

## 3. 페이로드 스키마

### 3.1 `state` (디바이스 → 브로커, **retained**, QoS1)
타일을 그리는 단일 진실 소스. retained여서 교사 대시보드가 늦게 접속해도 즉시 현재 상태를 받는다.

```json
{
  "st": "working",          // idle|working|stuck|done|help
  "act": "color-quiz",      // 현재 활동 id (없으면 null)
  "q": 3,                   // 현재 문항 인덱스
  "since": 1718900000,      // 이 상태 진입 시각(epoch, NTP 동기)
  "idle_ms": 4200,          // 마지막 입력 이후 경과(ms) — stuck 판정 입력
  "seq": 87                 // 단조 증가(중복/순서)
}
```
- 디바이스는 `idle/working/done/help`만 직접 보고. **`stuck`은 보고하지 않음**(백엔드가 파생).
- `help`는 도움 버튼 인터럽트 시 즉시 publish(디바운스 300ms).

### 3.2 `meta` (디바이스 또는 프로비저닝, **retained**)
```json
{ "group_id": "A", "seat_color": "#f59e0b", "seat_no": 7 }
```
> `seat_no`는 *좌석* 번호(물리적 자리)이지 아동 식별자가 아님. 아동↔좌석 매핑은 분리 저장소.

### 3.3 `cmd/feedback` (교사 → 디바이스)
```json
{ "led": "green", "blink": 2, "sound": "chime", "ms": 800 }
```
정답 축하·주의 환기 등 다감각 넛지(<100ms 로컬 반응 권장).

### 3.4 `cmd/hint` (교사 → 디바이스)
```json
{ "level": 1 }   // 1=넛지 빛, 2=방향 힌트, 3=정답 근접 — 단계적
```

### 3.5 `cmd/freeze` (개별/그룹 → 디바이스)
```json
{ "freeze": true, "msg": "선생님 보기" }   // 입력 잠금 + 화면/LED 신호
```

### 3.6 `group/{g}/mastery` (백엔드 → 대시보드, retained)
```json
{ "act": "color-quiz", "q": 3, "n": 25, "correct": 18, "rate": 0.72,
  "stuck": 2, "help": 1, "done": 2 }
```

---

## 4. 상태 머신 & stuck 자동 판정

### 4.1 디바이스 측 (펌웨어)
```
부팅 → idle
활동 푸시 수신 → working (since=now)
입력 이벤트 → working 유지, idle_ms=0, seq++
문항 완료 → answer publish + (다음 문항 working | 마지막이면 done)
도움 버튼 → help 즉시 publish (인터럽트, 디바운스 300ms)
freeze 수신 → 입력 잠금(상태는 유지)
```
- `state`는 **변화 시 + 하트비트(≤10s)** 로 publish. ArduinoMqttClient는 자동 재접속이 없으므로 `poll()` ≤10s + 지터 백오프 재접속 필수.

### 4.2 백엔드 측 (stuck 파생)
```
각 디바이스의 마지막 state 보관.
working 상태에서 idle_ms > THRESHOLD(예: 활동별 30~60s) → 대시보드에 stuck 표시.
help → 항상 최우선(빨강), stuck보다 위.
done/idle → 타이머 리셋.
LWT(offline) 수신 → 타일 흐림 처리(상태 보존하되 "연결끊김" 배지).
```
- THRESHOLD는 활동 난이도별 설정(저연령·쉬운 활동은 짧게). 교사가 슬라이더로 민감도 조절 가능하게.
- **stuck은 "추론"이므로 부드럽게**: 깜빡임 대신 색만, 오탐 시 교사가 무시 가능(대신 판단 X 원칙).

---

## 5. 백엔드 집계 (마스터리 뷰)

`answer` 이벤트를 활동·문항별로 집계 → `group/{g}/mastery` retained publish.
- 전 학생 응답 시스템의 본질적 강점 실현(형성평가 자동화 — 교사의 #1 장벽인 시간·학급규모 제거).
- 대시보드: 하단 "정답률 72% (18/25)" + (옵션) 문항별 분포 막대.
- **개인 식별 없이 집계만**: `mastery`는 합계/비율만, 누가 틀렸는지는 교사 클릭 시 *좌석 단위*로만.

---

## 6. 대시보드 동작 규칙

- **타일 1개 = 보드 1개.** `state.st` → 색. `help` → 굵은 빨강 테두리 + 상단 정렬(자동 소트: help → stuck → 나머지).
- **정렬 옵션**: 좌석순(기본) / 주의필요순(help·stuck 먼저).
- 타일 클릭 → 우측 상세(state, 현재 활동/문항, 최근 answer, RSSI/uptime) + 개별 명령 버튼.
- 글로벌 액션바: `활동 푸시`(group cmd) · `전체 멈춤(주목)` · `재개` · `그룹 보기`.
- retained 덕분에 새 교사 기기·새로고침에도 즉시 현재 화면 복원.

---

## 7. 브로커 ACL (Mosquitto Dynamic Security)

디바이스 principal은 자기 네임스페이스만:
```
# device {id}:
pub  edu/{site}/{id}/#           # 자기 state/answer/health
sub  edu/{site}/{id}/cmd/#       # 자기 명령만
sub  edu/{site}/group/{g}/cmd/#  # 자기 그룹 명령
deny sub edu/{site}/+/#          # 와일드카드 금지(다른 보드 데이터 차단)
```
대시보드/백엔드 principal만 광역 구독. **와일드카드 구독을 디바이스에 절대 부여 금지**(아동 데이터 유출 방지).

---

## 8. 신뢰성 (가짜 offline 방지)

- **MQTT 5 Will Delay Interval** 적용 → 교실 WiFi 깜빡임에 LWT가 즉발하지 않게 디바운스(예: 8s). 교사 화면의 offline 오탐 제거.
- `state`·`meta`·`mastery`는 **retained**, QoS1.
- 디바이스 재접속은 지터 지수 백오프(재접속 폭주 방지).

---

## 9. PIPA 가드레일

- 토픽/페이로드는 **기기·좌석 단위**만(chip-ID, seat_no, 값). 아동 이름 0.
- **아동 ↔ 좌석/기기 매핑은 분리된 접근통제 저장소**에만. 매핑 조회는 교사 인증·권한 하에서만, 접속기록 남김.
- `mastery`는 집계치만. 개인 답안 열람은 좌석 단위 + 교사 RBAC.
- retained 메시지에 아동 PII 금지(상태·집계만 retained).

---

## 10. 구현 순서 (MVP)

1. **펌웨어**: `state` publish(변화+하트비트) + 도움 버튼 → `help`. 로컬 즉시 LED/소리.
2. **백엔드**: state 수집 + stuck 타이머 파생 + LWT offline 처리.
3. **대시보드**: 타일 그리드(색·정렬·help 강조) + retained 복원.
4. **개별 명령**: `cmd/feedback`(빛+소리) → 교사가 한 명에게 넛지.
5. **집계**: `answer` → `mastery` + 하단 정답률.
6. **그룹/글로벌**: `group/{g}/cmd`(push_activity·freeze·resume).

> MVP의 1~3만으로도 "누가 막혔나 한눈에"라는 최고가치 기능이 동작한다. 4~6은 점증.
