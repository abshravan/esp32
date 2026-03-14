#ifndef DISPLAY_H
#define DISPLAY_H

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "config.h"

class Display {
public:
    bool begin() {
        Wire.begin(OLED_SDA, OLED_SCL);
        if (!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
            Serial.println("[OLED] Init failed!");
            return false;
        }
        oled.clearDisplay();
        oled.setTextColor(SSD1306_WHITE);
        oled.display();
        Serial.println("[OLED] Initialized");
        return true;
    }

    void showState(AssistantState state) {
        if (state == lastState && millis() - lastAnimUpdate < 150) return;
        lastState = state;
        lastAnimUpdate = millis();
        animFrame = (animFrame + 1) % 4;

        oled.clearDisplay();

        // Title bar
        oled.setTextSize(1);
        oled.setCursor(0, 0);
        oled.print("Voice Assistant");
        oled.drawLine(0, 10, OLED_WIDTH, 10, SSD1306_WHITE);

        // State icon + text in center
        oled.setTextSize(1);
        switch (state) {
            case STATE_IDLE:
                drawCenteredText("Ready", 28);
                drawMicIcon(56, 18, false);
                drawCenteredText("Tap button to talk", 52);
                break;

            case STATE_CONNECTING:
                drawCenteredText("Connecting...", 28);
                drawSpinner(60, 44);
                break;

            case STATE_LISTENING:
                drawCenteredText("Listening...", 28);
                drawMicIcon(56, 18, true);
                drawSoundWave(20, 50);
                break;

            case STATE_THINKING:
                drawCenteredText("Thinking...", 28);
                drawBrain(52, 16);
                drawDots(48, 52);
                break;

            case STATE_SPEAKING:
                drawCenteredText("Speaking...", 28);
                drawSpeaker(52, 16);
                drawSoundWave(20, 50);
                break;
        }
        oled.display();
    }

    void showMessage(const char* line1, const char* line2 = nullptr) {
        oled.clearDisplay();
        oled.setTextSize(1);
        oled.setCursor(0, 0);
        oled.print("Voice Assistant");
        oled.drawLine(0, 10, OLED_WIDTH, 10, SSD1306_WHITE);

        drawCenteredText(line1, 28);
        if (line2) {
            drawCenteredText(line2, 44);
        }
        oled.display();
    }

    void showTranscript(const char* text) {
        oled.clearDisplay();
        oled.setTextSize(1);
        oled.setCursor(0, 0);
        oled.print("You said:");
        oled.drawLine(0, 10, OLED_WIDTH, 10, SSD1306_WHITE);

        // Word-wrap the transcript
        oled.setCursor(0, 14);
        oled.setTextWrap(true);
        // Truncate long text to fit display
        char buf[120];
        strncpy(buf, text, sizeof(buf) - 1);
        buf[sizeof(buf) - 1] = '\0';
        oled.print(buf);
        oled.display();
    }

private:
    Adafruit_SSD1306 oled{OLED_WIDTH, OLED_HEIGHT, &Wire, -1};
    AssistantState lastState = STATE_IDLE;
    unsigned long lastAnimUpdate = 0;
    uint8_t animFrame = 0;

    void drawCenteredText(const char* text, int y) {
        int16_t x1, y1;
        uint16_t w, h;
        oled.getTextBounds(text, 0, 0, &x1, &y1, &w, &h);
        oled.setCursor((OLED_WIDTH - w) / 2, y);
        oled.print(text);
    }

    void drawMicIcon(int x, int y, bool active) {
        // Simple microphone shape
        oled.drawRoundRect(x, y, 16, 24, 6, SSD1306_WHITE);
        oled.drawLine(x + 8, y + 24, x + 8, y + 30, SSD1306_WHITE);
        oled.drawLine(x + 4, y + 30, x + 12, y + 30, SSD1306_WHITE);
        if (active) {
            // Pulsing circles around mic
            int r = 4 + animFrame;
            oled.drawCircle(x + 8, y + 12, r, SSD1306_WHITE);
        }
    }

    void drawSpeaker(int x, int y) {
        oled.fillTriangle(x, y + 12, x + 10, y + 6, x + 10, y + 18, SSD1306_WHITE);
        oled.fillRect(x + 10, y + 6, 6, 12, SSD1306_WHITE);
        // Sound waves
        for (int i = 0; i <= animFrame; i++) {
            oled.drawCircle(x + 20, y + 12, 4 + i * 4, SSD1306_WHITE);
        }
    }

    void drawBrain(int x, int y) {
        // Simple brain as overlapping circles
        oled.drawCircle(x + 8, y + 10, 8, SSD1306_WHITE);
        oled.drawCircle(x + 16, y + 10, 8, SSD1306_WHITE);
        oled.drawCircle(x + 12, y + 6, 6, SSD1306_WHITE);
    }

    void drawSoundWave(int x, int y) {
        for (int i = 0; i < 10; i++) {
            int h = 2 + (((i + animFrame) % 4) * 3);
            oled.drawLine(x + i * 9, y - h, x + i * 9, y + h, SSD1306_WHITE);
        }
    }

    void drawSpinner(int x, int y) {
        for (int i = 0; i < 4; i++) {
            int bright = ((i + animFrame) % 4 == 0) ? 1 : 0;
            int dx = (i == 0) ? 6 : (i == 2) ? -6 : 0;
            int dy = (i == 1) ? 6 : (i == 3) ? -6 : 0;
            if (bright)
                oled.fillCircle(x + dx, y + dy, 3, SSD1306_WHITE);
            else
                oled.drawCircle(x + dx, y + dy, 3, SSD1306_WHITE);
        }
    }

    void drawDots(int x, int y) {
        for (int i = 0; i < 3; i++) {
            if (i <= animFrame % 4)
                oled.fillCircle(x + i * 12, y, 3, SSD1306_WHITE);
            else
                oled.drawCircle(x + i * 12, y, 3, SSD1306_WHITE);
        }
    }
};

#endif // DISPLAY_H
