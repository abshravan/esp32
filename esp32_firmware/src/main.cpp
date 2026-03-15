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

// Guard flag for onWsBinary().  Set to true only when actively in
// STATE_SPEAKING; cleared to false BEFORE audio.stopSpeaker() so that any
// concurrent WebSocket background task sees the rejection immediately —
// even if the state variable hasn't been updated yet.
volatile bool acceptPlaybackAudio = false;
unsigned long lastButtonCheck = 0;
unsigned long stateEnteredAt = 0;
bool audioEndReceived = false;
unsigned long thinkingTimeoutAt = 0;   // Timestamp when the timeout message was shown
bool thinkingTimedOut = false;         // Boolean guard — avoids millis()==0 sentinel ambiguity
unsigned long playbackEndedAt = 0;     // For post-speak echo cooldown (reset each session)
unsigned long transcriptUntil = 0;    // Show transcript display until this timestamp (non-blocking)
unsigned long errorUntil = 0;         // Show error display until this timestamp, then go IDLE

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

    if (newState == STATE_THINKING) {
        thinkingTimedOut = false;
        thinkingTimeoutAt = 0;
        transcriptUntil = 0;
        errorUntil = 0;
    }

    // Mute mic while speaker is active to prevent echo feedback.
    // Flush DMA buffers on unmute so captured speaker audio is discarded.
    if (newState == STATE_SPEAKING) {
        acceptPlaybackAudio = true;
        audio.muteMicrophone();
        playbackEndedAt = 0;  // Reset cooldown timer for this new playback session.
    } else if (newState == STATE_LISTENING) {
        audio.unmuteMicrophone();
    }

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

    if (strcmp(type, "thinking") == 0) {
        setState(STATE_THINKING);
    } else if (strcmp(type, "speaking") == 0) {
        setState(STATE_SPEAKING);
    } else if (strcmp(type, "transcript") == 0) {
        display.showTranscript(data);
        transcriptUntil = millis() + 800;  // Replaced delay(800) — main loop guards display update
    } else if (strcmp(type, "audio_end") == 0) {
        Serial.println("[Main] Audio response complete");
        audioEndReceived = true;
    } else if (strcmp(type, "error") == 0) {
        Serial.printf("[Main] Server error: %s\n", data);
        display.showMessage("Error:", data);
        errorUntil = millis() + 2000;  // Replaced delay(2000)+setState — main loop handles transition
    }
}

void onWsBinary(const uint8_t* data, size_t len) {
    // Audio data from server → ring buffer → speaker.
    // Use acceptPlaybackAudio (not currentState) because the WebSocket library
    // may call this from a background task — checking a volatile bool is safe
    // across tasks; reading the shared currentState variable is not.
    // The flag is cleared *before* stopSpeaker() in startListening/cancelAction
    // so even in-flight callbacks are rejected before the buffer is cleared.
    if (!acceptPlaybackAudio) return;

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

    // Tap-to-talk: act only on press (rising edge), ignore release.
    // First tap → start listening. Second tap → stop and process.
    if (pressed && !buttonPressed) {
        buttonPressed = true;
        if (currentState == STATE_LISTENING) {
            // Guard: ignore tap if we just started listening (catches button bounce)
            if (millis() - stateEnteredAt > MIN_LISTEN_MS) {
                Serial.println("[Button] TAP → Stop listening");
                stopListening();
            } else {
                Serial.println("[Button] TAP ignored — too soon after start (bounce?)");
            }
        } else if (currentState == STATE_IDLE) {
            Serial.println("[Button] TAP → Start listening");
            startListening();
        } else if (currentState == STATE_SPEAKING) {
            Serial.println("[Button] TAP ignored — TTS playing, wait for IDLE");
        }
    } else if (!pressed && buttonPressed) {
        buttonPressed = false;  // Track release for next edge detection only
    }
}

// ============================================================
// Main capture + stream loop during LISTENING
// ============================================================
void captureAndStreamAudio() {
    size_t bytesRead = audio.readMicrophone(micBuffer, AUDIO_CHUNK_BYTES);
    if (bytesRead > 0) {
        // Track peak amplitude and log every ~1.6s (50 chunks × 32ms each)
        // so you can verify the mic is producing signal in the serial monitor.
        static uint32_t chunkCount = 0;
        static int16_t peakAmplitude = 0;

        int16_t* samples = (int16_t*)micBuffer;
        size_t numSamples = bytesRead / 2;
        for (size_t i = 0; i < numSamples; i++) {
            int16_t s = samples[i] < 0 ? -samples[i] : samples[i];
            if (s > peakAmplitude) peakAmplitude = s;
        }

        if (++chunkCount % 50 == 0) {
            Serial.printf("[Mic] Peak amplitude: %d (gain=%d)\n", peakAmplitude, audio.getMicGain());
            if (peakAmplitude < 50) {
                Serial.println("[Mic] WARNING: near-zero signal — check wiring or try ONLY_RIGHT channel in audio.h");
            }
            peakAmplitude = 0;
        }

        wsClient.sendAudio(micBuffer, bytesRead);
    }
}

// ============================================================
// Playback loop during SPEAKING
// ============================================================
void handlePlayback() {
    audio.feedSpeaker();

    // Once the server signals audio_end AND the ring buffer is fully drained
    // (available() == 0), wait POST_SPEAK_SILENCE_MS for room echo to die down
    // before returning to IDLE.  We wait for 0, not < AUDIO_CHUNK_BYTES, so the
    // last partial chunk is fed to the I2S DMA before we stop.
    if (audioEndReceived && audio.playbackBuffer.available() == 0) {
        if (playbackEndedAt == 0) {
            Serial.println("[Main] Audio stream done, muting mic for echo cooldown...");
            acceptPlaybackAudio = false;
            audio.stopSpeaker();
            playbackEndedAt = millis();
        } else if (millis() - playbackEndedAt > POST_SPEAK_SILENCE_MS) {
            Serial.println("[Main] Echo cooldown complete, returning to IDLE");
            playbackEndedAt = 0;
            setState(STATE_IDLE);
        }
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
    Serial.println("║  r + Enter  →  Reset ESP32               ║");
    Serial.println("║  BOOT btn   →  Tap=start, tap again=send ║");
    Serial.println("╚══════════════════════════════════════════╝");
    Serial.println();
}

// ============================================================
// Shared trigger actions (used by both button and serial)
// ============================================================
void startListening() {
    if (currentState == STATE_SPEAKING) {
        // Stop accepting audio FIRST so onWsBinary rejects any concurrent
        // callbacks before we clear the buffer.
        acceptPlaybackAudio = false;
        audio.stopSpeaker();
        wsClient.sendControl("cancel");
    }
    audioEndReceived = false;
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
        acceptPlaybackAudio = false;
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

            case 'r':
            case 'R':
                Serial.println("[Serial] >>> RESTARTING...");
                delay(100);  // Flush serial buffer before reset
                ESP.restart();
                break;

            case 'h':
            case 'H':
            case '?':
                Serial.println();
                Serial.println("Commands: s=start, e=end, c=cancel, r=reset, h=help");
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
            // Auto-stop after MAX_LISTEN_SECONDS to prevent runaway recording
            if (millis() - stateEnteredAt > MAX_LISTEN_SECONDS * 1000UL) {
                Serial.printf("[Main] Max listen time (%ds) reached, auto-stopping\n", MAX_LISTEN_SECONDS);
                stopListening();
            }
            break;

        case STATE_THINKING:
            // Error recovery: keep error message on screen for 2 s then return to IDLE.
            // errorUntil is set by onWsText so the callback never blocks.
            if (errorUntil > 0) {
                if (millis() > errorUntil) {
                    errorUntil = 0;
                    setState(STATE_IDLE);
                }
                break;  // Don't overwrite the error display until the timer fires
            }

            // Timeout after 30 seconds — non-blocking: show message then wait 1.5s before reset.
            // Uses a boolean flag rather than a 0-sentinel so that millis() wrapping to 0
            // at 49 days cannot falsely reset the timer.
            if (millis() - stateEnteredAt > 30000) {
                if (!thinkingTimedOut) {
                    Serial.println("[Main] Thinking timeout!");
                    display.showMessage("Timeout", "Try again");
                    thinkingTimeoutAt = millis();
                    thinkingTimedOut = true;
                } else if (millis() - thinkingTimeoutAt > 1500) {
                    setState(STATE_IDLE);
                }
            } else if (millis() < transcriptUntil) {
                // Transcript is being shown — don't overwrite with the thinking animation yet
            } else {
                display.showState(STATE_THINKING);
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
