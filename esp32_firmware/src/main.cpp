/*
 * ESP32 Voice Assistant Firmware
 * 
 * State machine:
 *   IDLE → (trigger) → LISTENING → (trigger) → THINKING → SPEAKING → IDLE
 * 
 * Two trigger modes (both active simultaneously):
 *   1. Serial Monitor:  Type 's' + Enter → start listening
 *                        Type 'e' + Enter → stop listening & process
 *                        Type 'c' + Enter → cancel / interrupt playback
 *   2. BOOT Button:     Hold to record, release to process (fallback)
 * 
 * Audio streams in real-time over WebSocket as raw PCM (16kHz, 16-bit, mono).
 * Server responses stream back as PCM and play through the speaker.
 */

#include <Arduino.h>
#include <WiFi.h>
#include "config.h"
#include "audio.h"
#include "ws_client.h"
#include "display.h"

// ============================================================
// Global objects
// ============================================================
Audio audio;
WSClient wsClient;
Display display;

AssistantState currentState = STATE_IDLE;
bool buttonPressed = false;
unsigned long lastButtonCheck = 0;
unsigned long stateEnteredAt = 0;
bool audioEndReceived = false;

// Mic capture buffer (reused each loop iteration)
uint8_t micBuffer[AUDIO_CHUNK_BYTES];

// Forward declarations
void startListening();
void stopListening();
void cancelAction();

// ============================================================
// State transitions
// ============================================================
void setState(AssistantState newState) {
    if (newState == currentState) return;
    Serial.printf("[State] %d → %d\n", currentState, newState);
    currentState = newState;
    stateEnteredAt = millis();
    display.showState(currentState);
}

// ============================================================
// WiFi setup
// ============================================================
void setupWiFi() {
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    display.showMessage("Connecting WiFi...", WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
        display.showMessage("WiFi Connected", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\n[WiFi] Connection FAILED!");
        display.showMessage("WiFi FAILED!", "Check config.h");
        while (true) delay(1000); // Halt
    }
}

// ============================================================
// WebSocket callbacks
// ============================================================
void onWsConnection(bool connected) {
    if (connected) {
        Serial.println("[Main] WebSocket connected");
        setState(STATE_IDLE);
    } else {
        Serial.println("[Main] WebSocket disconnected");
        setState(STATE_CONNECTING);
    }
}

void onWsText(const char* type, const char* data) {
    Serial.printf("[WS Recv] type=%s data=%s\n", type, data);

    if (strcmp(type, "status") == 0) {
        if (strcmp(data, "thinking") == 0) {
            // Server-side override; it may not always be needed
        } else if (strcmp(data, "speaking") == 0) {
            setState(STATE_SPEAKING);
        }
    } else if (strcmp(type, "thinking") == 0) {
        setState(STATE_THINKING);
    } else if (strcmp(type, "speaking") == 0) {
        setState(STATE_SPEAKING);
    } else if (strcmp(type, "transcript") == 0) {
        display.showTranscript(data);
        delay(800); // Brief display of what was heard
    } else if (strcmp(type, "audio_end") == 0) {
        Serial.println("[Main] Audio response complete");
        audioEndReceived = true;
    } else if (strcmp(type, "error") == 0) {
        Serial.printf("[Main] Server error: %s\n", data);
        display.showMessage("Error:", data);
        delay(2000);
        setState(STATE_IDLE);
    }
}

void onWsBinary(const uint8_t* data, size_t len) {
    // Audio data from server → ring buffer → speaker
    size_t written = audio.playbackBuffer.write(data, len);
    if (written < len) {
        Serial.printf("[Audio] Playback buffer overflow, dropped %d bytes\n", len - written);
    }
}

// ============================================================
// Button handling (with debounce)
// ============================================================
bool readButton() {
    static bool lastReading = false;
    static unsigned long lastChange = 0;

    bool reading = (digitalRead(BTN_PIN) == LOW); // Active low

    if (reading != lastReading) {
        lastChange = millis();
    }
    lastReading = reading;

    if (millis() - lastChange > BTN_DEBOUNCE_MS) {
        return reading;
    }
    return buttonPressed; // Return previous stable state
}

void handleButton() {
    bool pressed = readButton();

    if (pressed && !buttonPressed) {
        // Button just pressed
        buttonPressed = true;
        Serial.println("[Button] PRESSED → Start listening");
        startListening();
    }
    else if (!pressed && buttonPressed) {
        // Button just released
        buttonPressed = false;
        Serial.println("[Button] RELEASED → Stop listening");
        stopListening();
    }
}

// ============================================================
// Main capture + stream loop during LISTENING
// ============================================================
void captureAndStreamAudio() {
    size_t bytesRead = audio.readMicrophone(micBuffer, AUDIO_CHUNK_BYTES);
    if (bytesRead > 0) {
        wsClient.sendAudio(micBuffer, bytesRead);
    }
}

// ============================================================
// Playback loop during SPEAKING
// ============================================================
void handlePlayback() {
    audio.feedSpeaker();

    // Check if playback is complete
    if (audioEndReceived && audio.playbackBuffer.available() < AUDIO_CHUNK_BYTES) {
        Serial.println("[Main] Playback finished");
        audio.stopSpeaker();
        setState(STATE_IDLE);
    }
}

// ============================================================
// Arduino setup
// ============================================================
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n\n=== ESP32 Voice Assistant ===\n");

    // Button
    pinMode(BTN_PIN, INPUT_PULLUP);

    // Display
    if (!display.begin()) {
        Serial.println("[FATAL] OLED init failed");
    }
    display.showMessage("Booting...");

    // WiFi
    setupWiFi();
    delay(500);

    // Audio
    if (!audio.beginMicrophone()) {
        display.showMessage("Mic init FAILED!");
        while (true) delay(1000);
    }
    if (!audio.beginSpeaker()) {
        display.showMessage("Speaker init FAILED!");
        while (true) delay(1000);
    }

    // WebSocket
    wsClient.onConnection(onWsConnection);
    wsClient.onText(onWsText);
    wsClient.onBinary(onWsBinary);
    wsClient.begin();
    setState(STATE_CONNECTING);

    Serial.println("[Main] Setup complete, entering main loop");
    Serial.println();
    Serial.println("╔══════════════════════════════════════════╗");
    Serial.println("║       Serial Monitor Commands            ║");
    Serial.println("╠══════════════════════════════════════════╣");
    Serial.println("║  s + Enter  →  Start listening (record)  ║");
    Serial.println("║  e + Enter  →  Stop listening (process)  ║");
    Serial.println("║  c + Enter  →  Cancel / interrupt         ║");
    Serial.println("║  BOOT btn   →  Hold=record, release=send ║");
    Serial.println("╚══════════════════════════════════════════╝");
    Serial.println();
}

// ============================================================
// Shared trigger actions (used by both button and serial)
// ============================================================
void startListening() {
    if (currentState == STATE_SPEAKING) {
        // Interrupt current playback
        audio.stopSpeaker();
        wsClient.sendControl("cancel");
    }
    setState(STATE_LISTENING);
    wsClient.sendControl("start_listening");
}

void stopListening() {
    if (currentState == STATE_LISTENING) {
        wsClient.sendControl("stop_listening");
        setState(STATE_THINKING);
        audioEndReceived = false;
    }
}

void cancelAction() {
    if (currentState == STATE_SPEAKING) {
        audio.stopSpeaker();
        wsClient.sendControl("cancel");
        Serial.println("[Cancel] Playback interrupted");
        setState(STATE_IDLE);
    } else if (currentState == STATE_LISTENING) {
        wsClient.sendControl("cancel");
        Serial.println("[Cancel] Listening cancelled");
        setState(STATE_IDLE);
    } else if (currentState == STATE_THINKING) {
        wsClient.sendControl("cancel");
        Serial.println("[Cancel] Thinking cancelled");
        setState(STATE_IDLE);
    }
}

// ============================================================
// Serial Monitor command handler
// ============================================================
void handleSerial() {
    while (Serial.available()) {
        char c = Serial.read();

        // Ignore newline/carriage return
        if (c == '\n' || c == '\r') continue;

        switch (c) {
            case 's':
            case 'S':
                if (currentState == STATE_IDLE || currentState == STATE_SPEAKING) {
                    Serial.println("\n[Serial] >>> START LISTENING");
                    startListening();
                } else {
                    Serial.println("[Serial] Cannot start — not idle. Current state: " + String(currentState));
                }
                break;

            case 'e':
            case 'E':
                if (currentState == STATE_LISTENING) {
                    Serial.println("[Serial] >>> STOP LISTENING → Processing...");
                    stopListening();
                } else {
                    Serial.println("[Serial] Not listening, nothing to stop.");
                }
                break;

            case 'c':
            case 'C':
                Serial.println("[Serial] >>> CANCEL");
                cancelAction();
                break;

            case 'h':
            case 'H':
            case '?':
                Serial.println();
                Serial.println("Commands: s=start, e=end, c=cancel, h=help");
                Serial.printf("State: %d | WS: %s | Buf: %d bytes\n",
                    currentState,
                    wsClient.isConnected() ? "connected" : "disconnected",
                    audio.playbackBuffer.available());
                break;

            default:
                Serial.printf("[Serial] Unknown command '%c'. Type 'h' for help.\n", c);
                break;
        }
    }
}

// ============================================================
// Arduino main loop
// ============================================================
void loop() {
    // Always service WebSocket
    wsClient.loop();

    // Button handling (hardware fallback)
    handleButton();

    // Serial Monitor commands (primary control)
    handleSerial();

    // State-specific work
    switch (currentState) {
        case STATE_IDLE:
            // Animate OLED occasionally
            if (millis() % 500 < 10) {
                display.showState(STATE_IDLE);
            }
            break;

        case STATE_CONNECTING:
            display.showState(STATE_CONNECTING);
            break;

        case STATE_LISTENING:
            captureAndStreamAudio();
            display.showState(STATE_LISTENING);
            break;

        case STATE_THINKING:
            display.showState(STATE_THINKING);
            // Timeout after 30 seconds
            if (millis() - stateEnteredAt > 30000) {
                Serial.println("[Main] Thinking timeout!");
                display.showMessage("Timeout", "Try again");
                delay(1500);
                setState(STATE_IDLE);
            }
            break;

        case STATE_SPEAKING:
            handlePlayback();
            display.showState(STATE_SPEAKING);
            break;
    }

    // Small yield to prevent WDT
    yield();
}
