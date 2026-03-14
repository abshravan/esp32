#ifndef CONFIG_H
#define CONFIG_H

// ============================================================
// WiFi Configuration
// ============================================================
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"

// ============================================================
// WebSocket Server
// ============================================================
#define WS_HOST         "192.168.1.100"   // PC IP address
#define WS_PORT         8765
#define WS_PATH         "/ws"

// ============================================================
// I2S Microphone (INMP441) Pins
// ============================================================
#define MIC_I2S_PORT    I2S_NUM_0
#define MIC_I2S_WS      25    // Word Select (LRCK)
#define MIC_I2S_SCK     33    // Serial Clock (BCLK)
#define MIC_I2S_SD      32    // Serial Data (DOUT)

// ============================================================
// I2S Speaker (MAX98357A) Pins
// ============================================================
#define SPK_I2S_PORT    I2S_NUM_1
#define SPK_I2S_BCLK    27    // Bit Clock
#define SPK_I2S_LRC     14    // Left/Right Clock
#define SPK_I2S_DIN     26    // Data In

// ============================================================
// OLED Display (SSD1306) - I2C
// ============================================================
#define OLED_SDA        21
#define OLED_SCL        22
#define OLED_WIDTH      128
#define OLED_HEIGHT     64
#define OLED_ADDR       0x3C

// ============================================================
// Push-to-Talk Button
// ============================================================
#define BTN_PIN         0     // BOOT button on most ESP32 boards
#define BTN_DEBOUNCE_MS 100   // Increased from 50ms — BOOT button bounces heavily
#define MIN_LISTEN_MS   500   // Ignore stop-tap within 500ms of starting (prevents bounce)

// ============================================================
// Audio Configuration
// ============================================================
#define SAMPLE_RATE       16000   // 16kHz for speech
#define BITS_PER_SAMPLE   16
#define MIC_CHANNELS      1       // Mono
#define SPK_CHANNELS      1

// Audio buffer: 512 samples = 32ms at 16kHz
// Good balance of latency vs overhead
#define AUDIO_CHUNK_SAMPLES  512
#define AUDIO_CHUNK_BYTES    (AUDIO_CHUNK_SAMPLES * (BITS_PER_SAMPLE / 8))

// Playback ring buffer: holds ~2 seconds of audio
#define PLAYBACK_BUF_SIZE    (SAMPLE_RATE * 2 * (BITS_PER_SAMPLE / 8))

// ============================================================
// Listening Behaviour
// ============================================================
// Maximum recording duration before auto-stop (seconds).
// Increase this if you need to speak for longer.
#define MAX_LISTEN_SECONDS   60

// ============================================================
// State Machine
// ============================================================
enum AssistantState {
    STATE_IDLE,
    STATE_CONNECTING,
    STATE_LISTENING,
    STATE_THINKING,
    STATE_SPEAKING
};

#endif // CONFIG_H
