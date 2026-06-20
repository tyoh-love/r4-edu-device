// =============================================================================
// config.h — per-deployment + per-board constants for the R4 Swarm firmware.
//
// EDIT THIS FILE per classroom / per board, then flash. The device *id* is
// derived from the chip (WiFi MAC) at runtime, but the *seat assignment*
// (group / colour / seat number) is a human decision the board cannot infer,
// so it lives here as constants. (See docs/README.md §6.3 — meta payload.)
//
// Keep secrets out of version control in a real deployment: this header is the
// natural place to inject them from a build-time `-D` define or a gitignored
// copy. For the Phase-1 LAN demo, plain values are fine.
// =============================================================================
#ifndef R4_SWARM_CONFIG_H
#define R4_SWARM_CONFIG_H

// ---- WiFi (fixed classroom AP, per docs §7 provisioning) --------------------
#define WIFI_SSID       "classroom-ap"
#define WIFI_PASSWORD   "change-me"

// ---- MQTT broker (the teacher laptop running Mosquitto) ----------------------
#define BROKER_HOST     "192.168.1.10"   // laptop LAN IP (or mDNS name)
#define BROKER_PORT     1883             // 8883 when USE_TLS is enabled below

// Per-device broker credentials (production: allow_anonymous=false + ACL).
// Leave both empty ("") for the anonymous Phase-1 dev broker.
// In production the username MUST equal the device id (the ACL keys off %u ==
// device id; see infra/mosquitto/aclfile). Since the id is derived from the MAC
// at runtime, set MQTT_USER_IS_DEVICE_ID to use the runtime id as the username.
#define MQTT_USER_IS_DEVICE_ID  0        // 1 = username := derived "r4-XXXX"
#define MQTT_USERNAME   ""               // used only if the flag above is 0
#define MQTT_PASSWORD   ""

// ---- Site / activity --------------------------------------------------------
#define SITE            "site1"          // matches server/contract.py SITE
#define DEFAULT_ACTIVITY "color-quiz"
#define LAST_QUESTION   5                // q rolls 1..LAST_QUESTION then -> done

// ---- Seat identity (HUMAN ASSIGNMENT — set this per physical board) ----------
// These populate the retained `meta` payload the dashboard uses to place and
// colour the tile. The numeric device id (r4-XXXX) is independent of seat_no.
#define SEAT_GROUP_ID   "A"
#define SEAT_COLOR      "#f59e0b"        // CSS hex; dashboard tile accent
#define SEAT_NO         7

// ---- Timing (ms) ------------------------------------------------------------
// Heartbeat MUST be < OFFLINE_TIMEOUT_S (12s, contract.py) AND keep mqtt.poll()
// inside the keepalive window. 5s is the contract's recommended heartbeat.
#define HEARTBEAT_MS        5000UL
#define MQTT_KEEPALIVE_MS   15000UL      // library keepalive; poll() each loop
#define BUTTON_DEBOUNCE_MS  40UL         // physical debounce window
#define HELP_DEBOUNCE_MS    300UL        // help button needs a deliberate press

// Reconnect backoff (non-blocking, jittered exponential). ArduinoMqttClient has
// NO auto-reconnect, so we own this entirely.
#define RECONNECT_MIN_MS    1000UL
#define RECONNECT_MAX_MS    30000UL

// ---- NTP (for the `since` epoch field; R4 has no crystal -> ~2s/min drift) ---
#define NTP_SERVER      "pool.ntp.org"   // use the LAN NTP server in production
#define NTP_PORT        123
#define NTP_RESYNC_MS   600000UL         // re-sync every 10 min to fight drift
#define TZ_OFFSET_SEC   0                // store/contract use UTC epoch; keep 0

// ---- Pin map (see firmware/README.md for the wiring table) ------------------
// 4 answer buttons + 1 help button. Wired to GND with INPUT_PULLUP, so a press
// reads LOW. Use physical buttons >= 2cm (non-reader UX requirement, docs §4.2).
#define PIN_BTN_A1      2                // answer choice 1
#define PIN_BTN_A2      3                // answer choice 2
#define PIN_BTN_A3      4                // answer choice 3
#define PIN_BTN_A4      5                // answer choice 4
#define PIN_BTN_HELP    6                // help / "I'm stuck" button

#define PIN_LED         LED_BUILTIN      // simple status/feedback LED (D13)
#define PIN_BUZZER      9                // passive buzzer via tone() (PWM pin)

// Use the onboard 12x8 LED matrix for richer feedback instead of a single LED.
// Set to 1 to compile in Arduino_LED_Matrix usage (adds that dependency).
#define USE_LED_MATRIX  0

// ---- TLS (server-auth only; R4 supports TLS but NOT client-cert mTLS) --------
// Set to 1 to switch WiFiClient -> WiFiSSLClient on port 8883. R4's WiFiSSLClient
// can verify the broker (server-auth) but CANNOT present a client cert (mTLS is
// unsupported — Arduino renesas core issue #499). Compensate with per-device
// user/pass + ACL + VLAN (docs §6.5 / §7). Paste the broker CA below when on.
#define USE_TLS         0
static const char BROKER_CA_CERT[] =
    // ---- BEGIN broker CA (PEM) — paste your Mosquitto CA here when USE_TLS=1 ----
    "-----BEGIN CERTIFICATE-----\n"
    "...replace with your CA certificate...\n"
    "-----END CERTIFICATE-----\n";

#endif  // R4_SWARM_CONFIG_H
