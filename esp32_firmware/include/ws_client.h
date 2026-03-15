#ifndef WS_CLIENT_H
#define WS_CLIENT_H

#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "config.h"

// Callback types for different message kinds
typedef void (*TextMessageCallback)(const char* type, const char* data);
typedef void (*BinaryMessageCallback)(const uint8_t* data, size_t len);
typedef void (*ConnectionCallback)(bool connected);

class WSClient {
public:
    void begin() {
        ws.begin(WS_HOST, WS_PORT, WS_PATH);
        ws.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
            handleEvent(type, payload, length);
        });
        ws.setReconnectInterval(3000);
        // Enable binary streaming for audio
        ws.enableHeartbeat(15000, 3000, 2);
        Serial.printf("[WS] Connecting to %s:%d%s\n", WS_HOST, WS_PORT, WS_PATH);
    }

    void loop() {
        ws.loop();
    }

    bool isConnected() const {
        return connected;
    }

    // Send raw audio bytes
    bool sendAudio(const uint8_t* data, size_t len) {
        if (!connected) return false;
        return ws.sendBIN(data, len);
    }

    // Send a JSON control message
    bool sendControl(const char* type, const char* extra = nullptr) {
        if (!connected) return false;
        StaticJsonDocument<256> doc;
        doc["type"] = type;
        if (extra) doc["data"] = extra;
        char buf[256];
        serializeJson(doc, buf, sizeof(buf));
        return ws.sendTXT(buf);
    }

    void onText(TextMessageCallback cb) { textCb = cb; }
    void onBinary(BinaryMessageCallback cb) { binaryCb = cb; }
    void onConnection(ConnectionCallback cb) { connCb = cb; }

private:
    WebSocketsClient ws;
    bool connected = false;
    TextMessageCallback textCb = nullptr;
    BinaryMessageCallback binaryCb = nullptr;
    ConnectionCallback connCb = nullptr;

    void handleEvent(WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {
            case WStype_DISCONNECTED:
                Serial.println("[WS] Disconnected");
                connected = false;
                if (connCb) connCb(false);
                break;

            case WStype_CONNECTED:
                // Use length-bounded print — payload is not guaranteed null-terminated.
                Serial.printf("[WS] Connected to %.*s\n", (int)length, (char*)payload);
                connected = true;
                if (connCb) connCb(true);
                break;

            case WStype_TEXT: {
                // Parse JSON text messages.
                // 1024 bytes gives ~980 chars of usable text — enough for a 60 s transcript
                // at typical Whisper output density without hitting heap pressure.
                StaticJsonDocument<1024> doc;
                DeserializationError err = deserializeJson(doc, payload, length);
                if (err) {
                    Serial.printf("[WS] JSON parse error: %s\n", err.c_str());
                    break;
                }
                const char* msgType = doc["type"] | "unknown";
                const char* msgData = doc["text"] | "";
                if (textCb) textCb(msgType, msgData);
                break;
            }

            case WStype_BIN:
                // Binary = audio data from server
                if (binaryCb) binaryCb(payload, length);
                break;

            case WStype_PING:
            case WStype_PONG:
                break;

            case WStype_ERROR:
                Serial.println("[WS] Error");
                break;

            default:
                break;
        }
    }
};

#endif // WS_CLIENT_H
