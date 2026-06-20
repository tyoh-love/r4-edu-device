// =============================================================================
// r4_swarm.ino — Arduino UNO R4 WiFi firmware for the "Who's-Stuck" classroom
// grid (Phase 5: real device that drops in for a simulated board).
//
// Implements the exact MQTT contract the Python simulator (sim/simulate.py) and
// backend (server/contract.py + server/store.py) speak, so a physical board is
// interchangeable with a simulated one. Topics & payloads follow docs/README.md
// §6 and docs/API.md.
//
// MQTT contract implemented here (site="site1", id derived from WiFi MAC):
//   - RETAINED  edu/site1/<id>/meta   {group_id,seat_color,seat_no}   once @ boot
//   - RETAINED  edu/site1/<id>/state  {st,act,q,since,idle_ms,seq}    on change + ~5s heartbeat
//               edu/site1/<id>/answer {choice,correct,act,q}          on each answer
//   - LWT       edu/site1/<id>/status "offline" (retained will) + birth "online"
//   - SUBSCRIBE edu/site1/<id>/cmd/#  -> feedback|hint|freeze|resume|push_activity
//
// Libraries (see firmware/README.md for exact versions / board package):
//   WiFiS3            (bundled with arduino:renesas_uno core — R4 WiFi)
//   ArduinoMqttClient (arduino-libraries; NO auto-reconnect, no MQTT5)
//   ArduinoJson v7    (JsonDocument idioms)
//   WiFiUDP           (bundled — used for NTP)
//
// HARDWARE CAVEAT: early renesas cores returned a zero / byte-reversed WiFi MAC.
// Fixed in arduino:renesas_uno >= 1.1.0 — pin the core version. We still guard
// against an all-zero MAC and fall back to a millis-seeded id (see deviceId()).
// TLS CAVEAT: R4 does server-auth TLS (WiFiSSLClient + setCACert) but NOT client
// -cert mTLS (core issue #499) — see config.h USE_TLS and the #if blocks below.
// =============================================================================

#include <WiFiS3.h>
#include <WiFiUdp.h>
#include <ArduinoMqttClient.h>
#include <ArduinoJson.h>

#include "config.h"

#if USE_LED_MATRIX
  #include "Arduino_LED_Matrix.h"
  static ArduinoLEDMatrix gMatrix;
#endif

// ---- Transport: plain TCP, or server-auth TLS on 8883 -----------------------
// R4 supports server-auth TLS; client-cert mTLS is NOT supported (issue #499).
#if USE_TLS
  static WiFiSSLClient   gNet;     // verifies broker via setCACert(); no client cert
#else
  static WiFiClient      gNet;
#endif
static MqttClient        gMqtt(gNet);
static WiFiUDP           gUdp;

// =============================================================================
// Device identity — derived from the WiFi MAC (last 2 bytes -> "r4-XXXX").
// =============================================================================
static String gDeviceId;          // e.g. "r4-3f7a"
static String gTopicMeta, gTopicState, gTopicAnswer, gTopicStatus, gTopicCmdSub;

static String deviceId() {
  uint8_t mac[6] = {0};
  WiFi.macAddress(mac);
  // Guard the historical R4 zero-MAC bug (fixed in core >= 1.1.0): if the MAC
  // is all-zero, fall back to a millis-seeded pseudo-id so devices stay unique.
  bool allZero = true;
  for (int i = 0; i < 6; i++) if (mac[i]) { allZero = false; break; }
  uint16_t tail = allZero ? (uint16_t)(micros() & 0xFFFF)
                          : (uint16_t)((mac[4] << 8) | mac[5]);
  char buf[8];
  snprintf(buf, sizeof(buf), "r4-%04x", tail);  // last 2 MAC bytes, lower hex
  return String(buf);
}

static void buildTopics() {
  String base = String("edu/") + SITE + "/" + gDeviceId + "/";
  gTopicMeta   = base + "meta";
  gTopicState  = base + "state";
  gTopicAnswer = base + "answer";
  gTopicStatus = base + "status";
  gTopicCmdSub = base + "cmd/#";   // subscribe wildcard; leaf = command name
}

// =============================================================================
// Local UX state (mirrors the simulator's Board model). The device only ever
// REPORTS idle|working|done|help; the backend DERIVES `stuck` from idle_ms.
// =============================================================================
enum DevState { ST_IDLE, ST_WORKING, ST_DONE, ST_HELP };
static const char* stateName(DevState s) {
  switch (s) {
    case ST_IDLE:    return "idle";
    case ST_WORKING: return "working";
    case ST_DONE:    return "done";
    case ST_HELP:    return "help";
  }
  return "idle";
}

static DevState  gState     = ST_WORKING;  // boots into the activity
static String    gActivity  = DEFAULT_ACTIVITY;
static int       gQuestion  = 1;
static uint32_t  gSeq       = 0;
static bool      gFrozen    = false;       // freeze cmd locks input
static unsigned long gLastInputMs = 0;     // millis() of last button press
static unsigned long gStateSinceMs = 0;    // millis() when current state began
static uint32_t  gStateSinceEpoch = 0;     // epoch when current state began (NTP)
// NOTE: epoch values are uint32_t (not time_t) so we depend on no <time.h>; fine
// until 2106 and store.py compares `since` only relatively.

// =============================================================================
// Time — NTP over UDP for the `since` epoch. R4 RTC drifts ~2s/min (no crystal)
// so we periodically resync. If NTP never answers we fall back to millis-based
// pseudo-epoch (store.py tolerates either; it only compares relative values).
// =============================================================================
static bool          gNtpOk = false;
static uint32_t      gEpochBase = 0;        // epoch at gEpochBaseMs
static unsigned long gEpochBaseMs = 0;
static unsigned long gLastNtpMs = 0;

// Returns current epoch seconds (NTP-anchored, extrapolated by millis()).
static uint32_t nowEpoch() {
  if (gEpochBase == 0) return (uint32_t)(millis() / 1000);  // pre-sync fallback
  return gEpochBase + (uint32_t)((millis() - gEpochBaseMs) / 1000);
}

// Blocking-but-bounded NTP query (~1.5s max). Called occasionally, not in hot loop.
static bool syncNtp() {
  const int NTP_PACKET_SIZE = 48;
  uint8_t pkt[NTP_PACKET_SIZE] = {0};
  pkt[0] = 0b11100011;  // LI=3 (unsync), VN=4, Mode=3 (client)

  gUdp.begin(2390);
  if (!gUdp.beginPacket(NTP_SERVER, NTP_PORT)) { gUdp.stop(); return false; }
  gUdp.write(pkt, NTP_PACKET_SIZE);
  gUdp.endPacket();

  unsigned long start = millis();
  while (millis() - start < 1500) {
    if (gUdp.parsePacket() >= NTP_PACKET_SIZE) {
      gUdp.read(pkt, NTP_PACKET_SIZE);
      gUdp.stop();
      // Seconds since 1900 are in bytes 40..43 (big-endian).
      unsigned long secs1900 = ((unsigned long)pkt[40] << 24) |
                               ((unsigned long)pkt[41] << 16) |
                               ((unsigned long)pkt[42] << 8)  |
                               ((unsigned long)pkt[43]);
      const unsigned long SEVENTY_YEARS = 2208988800UL;  // 1900 -> 1970
      uint32_t epoch = (uint32_t)(secs1900 - SEVENTY_YEARS) + TZ_OFFSET_SEC;
      gEpochBase   = epoch;
      gEpochBaseMs = millis();
      gNtpOk = true;
      return true;
    }
    delay(5);
  }
  gUdp.stop();
  return false;
}

// =============================================================================
// Feedback — LED + buzzer (multisensory, <100ms; docs §4.2). Non-blocking blink
// scheduling kept minimal: short tone()s + an LED pulse driven from loop().
// =============================================================================
static unsigned long gLedOffAtMs = 0;      // 0 = LED steady-off control window
static int           gPendingBlinks = 0;
static unsigned long gNextBlinkMs = 0;
static unsigned long gBlinkMs = 200;

static void buzz(int freqHz, int ms) {
  if (freqHz > 0) tone(PIN_BUZZER, freqHz, ms);
}

static void startFeedback(int blinks, int onMs, int freqHz) {
  gPendingBlinks = max(1, blinks);
  gBlinkMs       = (onMs > 0) ? onMs : 200;
  gNextBlinkMs   = millis();
  if (freqHz > 0) buzz(freqHz, gBlinkMs);
#if USE_LED_MATRIX
  // simple full-on flash on the matrix
  uint32_t frame[3] = {0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF};
  gMatrix.loadFrame(frame);
#endif
}

// Drive the non-blocking blink state machine; call every loop().
static void serviceFeedback() {
  unsigned long now = millis();
  if (gPendingBlinks > 0 && now >= gNextBlinkMs) {
    static bool on = false;
    on = !on;
    digitalWrite(PIN_LED, on ? HIGH : LOW);
    gNextBlinkMs = now + gBlinkMs;
    if (!on) {
      gPendingBlinks--;
      if (gPendingBlinks == 0) {
        digitalWrite(PIN_LED, LOW);
#if USE_LED_MATRIX
        gMatrix.clear();
#endif
      }
    }
  }
}

// =============================================================================
// Publishing — ArduinoMqttClient is Print-based:
//   beginMessage(topic, retained, qos); print(payload); endMessage();
// (NOT PubSubClient's publish(topic,payload,retain).)
// =============================================================================
static void publishMeta() {
  JsonDocument doc;
  doc["group_id"]   = SEAT_GROUP_ID;
  doc["seat_color"] = SEAT_COLOR;
  doc["seat_no"]    = SEAT_NO;
  String out; serializeJson(doc, out);
  gMqtt.beginMessage(gTopicMeta, /*retain=*/true, /*qos=*/1);
  gMqtt.print(out);
  gMqtt.endMessage();
}

// idle_ms MUST be recomputed fresh on every publish (= millis()-lastInput) so the
// backend's stuck derivation sees it climb while we heartbeat. Never cache it.
static void publishState() {
  gSeq++;
  unsigned long idleMs = millis() - gLastInputMs;
  JsonDocument doc;
  doc["st"]      = stateName(gState);
  doc["act"]     = gActivity;
  doc["q"]       = gQuestion;
  doc["since"]   = (uint32_t)gStateSinceEpoch;  // epoch secs (store.py: int ok)
  doc["idle_ms"] = (uint32_t)idleMs;
  doc["seq"]     = gSeq;
  String out; serializeJson(doc, out);
  gMqtt.beginMessage(gTopicState, /*retain=*/true, /*qos=*/1);
  gMqtt.print(out);
  gMqtt.endMessage();
}

static void publishAnswer(int choice, bool correct) {
  JsonDocument doc;
  doc["choice"]  = choice;
  doc["correct"] = correct;
  doc["act"]     = gActivity;
  doc["q"]       = gQuestion;
  String out; serializeJson(doc, out);
  gMqtt.beginMessage(gTopicAnswer, /*retain=*/false, /*qos=*/1);  // answers are NOT retained
  gMqtt.print(out);
  gMqtt.endMessage();
}

// =============================================================================
// State transitions.
// =============================================================================
static void enterState(DevState s) {
  if (s != gState) {
    gState = s;
    gStateSinceMs = millis();
    gStateSinceEpoch = nowEpoch();
  }
  publishState();  // publish on every change (and we also heartbeat)
}

// =============================================================================
// Command handling — onMessage callback. The command NAME is the topic leaf
// (edu/site1/<id>/cmd/<name>), NOT a field in the payload. We reassemble the
// payload via available()/read() and parse it with ArduinoJson.
// =============================================================================
static String readPayload(int messageSize) {
  String s;
  s.reserve(messageSize > 0 ? messageSize : 32);
  while (gMqtt.available()) s += (char)gMqtt.read();
  return s;
}

static void onMqttMessage(int messageSize) {
  String topic = gMqtt.messageTopic();           // edu/site1/<id>/cmd/<name>
  String body  = readPayload(messageSize);

  // command name = last path segment
  int slash = topic.lastIndexOf('/');
  String cmd = (slash >= 0) ? topic.substring(slash + 1) : topic;

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, body);
  // (commands may legitimately have an empty/absent body, e.g. resume)

  if (cmd == "feedback") {
    // {led, blink, sound, ms} -> flash LED + buzzer
    int blinks = doc["blink"] | 2;
    int ms     = doc["ms"]    | 800;
    const char* sound = doc["sound"] | "chime";
    int freq = (strcmp(sound, "buzz") == 0) ? 220 : 880;  // chime=high, buzz=low
    startFeedback(blinks, ms / max(1, blinks), freq);
    // teacher acknowledged -> clear an outstanding help (mirrors simulator)
    if (gState == ST_HELP) { gLastInputMs = millis(); enterState(ST_WORKING); }

  } else if (cmd == "hint") {
    // {level} -> escalating LED nudge (1 short .. 3 long), no answer reveal
    int level = doc["level"] | 1;
    startFeedback(level, 150 + 100 * level, 660);
    if (gState == ST_HELP) { gLastInputMs = millis(); enterState(ST_WORKING); }

  } else if (cmd == "freeze") {
    bool f = doc["freeze"] | true;   // {freeze:true}; default true if body empty
    gFrozen = f;
    digitalWrite(PIN_LED, f ? HIGH : LOW);  // steady LED = locked

  } else if (cmd == "resume") {
    gFrozen = false;
    digitalWrite(PIN_LED, LOW);

  } else if (cmd == "push_activity") {
    // {act} -> reset to working q=1 with the new activity
    const char* act = doc["act"] | DEFAULT_ACTIVITY;
    gActivity = String(act);
    gQuestion = 1;
    gFrozen   = false;
    gLastInputMs = millis();
    enterState(ST_WORKING);
  }
  // unknown commands are ignored (forward-compatible)
}

// =============================================================================
// Connection — WiFi + MQTT with will (set BEFORE connect) + birth + subscribe.
// On EVERY (re)connect we must re-arm the will, re-subscribe, re-publish retained
// meta, and publish the "online" birth. ArduinoMqttClient has no auto-reconnect.
// =============================================================================
static bool gWifiUp = false;

static void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) { gWifiUp = true; return; }
  gWifiUp = false;
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  // bounded wait; loop() will retry if this attempt fails
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) delay(200);
  gWifiUp = (WiFi.status() == WL_CONNECTED);
}

static bool connectMqtt() {
  if (!gWifiUp) return false;

#if USE_TLS
  gNet.setCACert(BROKER_CA_CERT);   // server-auth only; R4 cannot do client-cert mTLS
#endif

  gMqtt.setId(gDeviceId);
  gMqtt.setKeepAliveInterval(MQTT_KEEPALIVE_MS);   // library expects milliseconds
  gMqtt.setConnectionTimeout(5000);
  gMqtt.setTxPayloadSize(512);      // default 256 is tight for state+meta JSON

  // Credentials (production: username == device id for the ACL).
#if MQTT_USER_IS_DEVICE_ID
  gMqtt.setUsernamePassword(gDeviceId, MQTT_PASSWORD);
#else
  if (strlen(MQTT_USERNAME) > 0) gMqtt.setUsernamePassword(MQTT_USERNAME, MQTT_PASSWORD);
#endif

  // LWT MUST be armed before connect(): retained "offline" on status topic.
  gMqtt.beginWill(gTopicStatus, /*retain=*/true, /*qos=*/1);
  gMqtt.print("offline");
  gMqtt.endWill();

  if (!gMqtt.connect(BROKER_HOST, BROKER_PORT)) {
    return false;  // connectError() has detail if you want to log it
  }

  // On connect: birth, subscribe, retained meta + first state.
  gMqtt.beginMessage(gTopicStatus, /*retain=*/true, /*qos=*/1);
  gMqtt.print("online");                  // birth overrides the retained will
  gMqtt.endMessage();

  gMqtt.onMessage(onMqttMessage);
  gMqtt.subscribe(gTopicCmdSub, /*qos=*/1);

  publishMeta();
  // Do NOT reset gStateSinceEpoch here: a mid-activity WiFi blip must not make
  // `since` jump to reconnect time (state didn't change). It's seeded in setup()
  // and updated only on real transitions in enterState(). Backfill only if we
  // never got a valid epoch before (e.g. NTP came up after boot).
  if (gStateSinceEpoch == 0) gStateSinceEpoch = nowEpoch();
  publishState();
  return true;
}

// Non-blocking reconnect with jittered exponential backoff.
static unsigned long gNextReconnectMs = 0;
static unsigned long gBackoffMs = RECONNECT_MIN_MS;

static void serviceConnection() {
  if (gMqtt.connected()) { gBackoffMs = RECONNECT_MIN_MS; return; }

  unsigned long now = millis();
  if (now < gNextReconnectMs) return;     // still backing off

  ensureWifi();
  bool ok = connectMqtt();
  if (ok) {
    gBackoffMs = RECONNECT_MIN_MS;
  } else {
    // exponential backoff with +/-25% jitter, capped.
    gBackoffMs = min(gBackoffMs * 2, RECONNECT_MAX_MS);
    long jitter = (long)random(-(long)(gBackoffMs / 4), (long)(gBackoffMs / 4) + 1);
    gNextReconnectMs = now + gBackoffMs + jitter;
  }
}

// =============================================================================
// Inputs — 4 answer buttons + 1 help button, INPUT_PULLUP (press = LOW).
// Physical buttons should be >= 2cm (non-reader UX, docs §4.2). Debounced.
// =============================================================================
struct Button {
  uint8_t pin;
  bool    stable;        // debounced level (true = released/HIGH)
  bool    lastRead;
  unsigned long lastChangeMs;
  unsigned long debounceMs;
};

static Button gAnswerBtn[4] = {
  {PIN_BTN_A1, true, true, 0, BUTTON_DEBOUNCE_MS},
  {PIN_BTN_A2, true, true, 0, BUTTON_DEBOUNCE_MS},
  {PIN_BTN_A3, true, true, 0, BUTTON_DEBOUNCE_MS},
  {PIN_BTN_A4, true, true, 0, BUTTON_DEBOUNCE_MS},
};
static Button gHelpBtn = {PIN_BTN_HELP, true, true, 0, HELP_DEBOUNCE_MS};

// Returns true exactly once on a debounced press (HIGH->LOW edge).
static bool pressed(Button& b) {
  bool raw = (digitalRead(b.pin) == LOW);   // active-low
  bool rawHigh = !raw;
  if (rawHigh != b.lastRead) { b.lastRead = rawHigh; b.lastChangeMs = millis(); }
  if (millis() - b.lastChangeMs >= b.debounceMs && b.stable != rawHigh) {
    b.stable = rawHigh;
    if (b.stable == false) return true;     // just became pressed (LOW)
  }
  return false;
}

// A wrong/right answer is judged locally. For color-quiz we treat choice #1 as
// the "correct" key for demo purposes; a real activity would carry the key from
// push_activity. Keep deterministic so behaviour is testable.
static bool judge(int choice) { return choice == 1; }

static void handleAnswer(int choice) {
  if (gFrozen) return;
  if (gState == ST_DONE) return;
  gLastInputMs = millis();
  bool correct = judge(choice);
  publishAnswer(choice, correct);
  startFeedback(correct ? 2 : 1, correct ? 120 : 400, correct ? 880 : 200);
  gQuestion++;
  if (gQuestion > LAST_QUESTION) enterState(ST_DONE);
  else if (gState != ST_WORKING) enterState(ST_WORKING);
  else publishState();   // same state, but report progress (q advanced)
}

static void handleHelp() {
  // help is the explicit "I'm stuck" signal — the single highest-value signal in
  // the system (Lumilo, docs §6.1). It is deliberately allowed THROUGH freeze:
  // "eyes on me" must never silence a stuck child raising their hand.
  gLastInputMs = millis();
  enterState(gState == ST_HELP ? ST_WORKING : ST_HELP);  // toggle hand up/down
}

static void serviceInputs() {
  for (int i = 0; i < 4; i++) {
    if (pressed(gAnswerBtn[i])) handleAnswer(i + 1);
  }
  if (pressed(gHelpBtn)) handleHelp();
}

// =============================================================================
// Arduino entry points.
// =============================================================================
void setup() {
  Serial.begin(115200);
  // don't block forever waiting for USB serial in a headless classroom
  unsigned long s = millis();
  while (!Serial && millis() - s < 1500) {}

  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_BTN_A1, INPUT_PULLUP);
  pinMode(PIN_BTN_A2, INPUT_PULLUP);
  pinMode(PIN_BTN_A3, INPUT_PULLUP);
  pinMode(PIN_BTN_A4, INPUT_PULLUP);
  pinMode(PIN_BTN_HELP, INPUT_PULLUP);

#if USE_LED_MATRIX
  gMatrix.begin();
#endif

  ensureWifi();
  gDeviceId = deviceId();        // needs WiFi up for a valid MAC
  buildTopics();
  randomSeed(micros());

  // Seed time: try NTP, else fall back to millis-based epoch.
  if (gWifiUp && syncNtp()) gLastNtpMs = millis();
  gStateSinceEpoch = nowEpoch();
  gStateSinceMs    = millis();
  gLastInputMs     = millis();

  Serial.print("device id: "); Serial.println(gDeviceId);
  Serial.print("ntp: ");       Serial.println(gNtpOk ? "ok" : "fallback(millis)");

  connectMqtt();                 // first attempt; loop() owns retries
}

void loop() {
  // 1) keep MQTT serviced: poll() handles keepalive + dispatches onMessage.
  //    MUST be called frequently (well within the keepalive window).
  if (gMqtt.connected()) gMqtt.poll();

  // 2) keep the connection alive (non-blocking reconnect w/ backoff).
  serviceConnection();

  // 3) inputs, feedback.
  serviceInputs();
  serviceFeedback();

  // 4) periodic NTP resync (R4 RTC drift ~2s/min).
  if (gWifiUp && millis() - gLastNtpMs >= NTP_RESYNC_MS) {
    if (syncNtp()) gLastNtpMs = millis();
    else gLastNtpMs = millis() - NTP_RESYNC_MS + 30000UL;  // retry in ~30s
  }

  // 5) heartbeat: re-publish state at least every HEARTBEAT_MS so the board
  //    stays "online" (< OFFLINE_TIMEOUT_S) and idle_ms keeps climbing for the
  //    backend's stuck derivation.
  static unsigned long lastBeat = 0;
  if (gMqtt.connected() && millis() - lastBeat >= HEARTBEAT_MS) {
    lastBeat = millis();
    publishState();
  }
}
