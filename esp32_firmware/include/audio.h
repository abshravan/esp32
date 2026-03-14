#ifndef AUDIO_H
#define AUDIO_H

#include <driver/i2s.h>
#include "config.h"

// ============================================================
// Ring buffer for playback audio received from server
// ============================================================
class RingBuffer {
public:
    bool init(size_t size) {
        bufSize = size;
        buf = (uint8_t*)heap_caps_malloc(size, MALLOC_CAP_8BIT);
        if (!buf) {
            Serial.println("[RingBuf] Allocation failed!");
            return false;
        }
        readIdx = writeIdx = count = 0;
        return true;
    }

    size_t write(const uint8_t* data, size_t len) {
        size_t written = 0;
        while (written < len && count < bufSize) {
            buf[writeIdx] = data[written];
            writeIdx = (writeIdx + 1) % bufSize;
            count++;
            written++;
        }
        return written;
    }

    size_t read(uint8_t* data, size_t len) {
        size_t readCount = 0;
        while (readCount < len && count > 0) {
            data[readCount] = buf[readIdx];
            readIdx = (readIdx + 1) % bufSize;
            count--;
            readCount++;
        }
        return readCount;
    }

    size_t available() const { return count; }
    size_t freeSpace() const { return bufSize - count; }
    void clear() { readIdx = writeIdx = count = 0; }

private:
    uint8_t* buf = nullptr;
    size_t bufSize = 0;
    volatile size_t readIdx = 0;
    volatile size_t writeIdx = 0;
    volatile size_t count = 0;
};

// ============================================================
// Audio driver wrapping I2S for mic and speaker
// ============================================================
class Audio {
public:
    RingBuffer playbackBuffer;

    bool beginMicrophone() {
        // INMP441 channel selection:
        //   L/R pin tied LOW  (GND) → mic outputs LEFT channel  → use I2S_CHANNEL_FMT_ONLY_LEFT
        //   L/R pin tied HIGH (3V3) → mic outputs RIGHT channel → use I2S_CHANNEL_FMT_ONLY_RIGHT
        // If you get silence, flip this to I2S_CHANNEL_FMT_ONLY_RIGHT.
        i2s_config_t mic_config = {
            .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
            .sample_rate = SAMPLE_RATE,
            .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
            .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_I2S,
            .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count = 8,
            .dma_buf_len = AUDIO_CHUNK_SAMPLES,
            .use_apll = false,
            .tx_desc_auto_clear = false,
            .fixed_mclk = 0,
        };

        i2s_pin_config_t mic_pins = {
            .bck_io_num = MIC_I2S_SCK,
            .ws_io_num = MIC_I2S_WS,
            .data_out_num = I2S_PIN_NO_CHANGE,
            .data_in_num = MIC_I2S_SD,
        };

        esp_err_t err = i2s_driver_install(MIC_I2S_PORT, &mic_config, 0, NULL);
        if (err != ESP_OK) {
            Serial.printf("[Audio] Mic I2S install failed: %d\n", err);
            return false;
        }
        err = i2s_set_pin(MIC_I2S_PORT, &mic_pins);
        if (err != ESP_OK) {
            Serial.printf("[Audio] Mic pin config failed: %d\n", err);
            return false;
        }
        i2s_zero_dma_buffer(MIC_I2S_PORT);
        Serial.println("[Audio] Microphone initialized");
        return true;
    }

    bool beginSpeaker() {
        i2s_config_t spk_config = {
            .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
            .sample_rate = SAMPLE_RATE,
            .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
            .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_I2S,
            .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count = 8,
            .dma_buf_len = AUDIO_CHUNK_SAMPLES,
            .use_apll = false,
            .tx_desc_auto_clear = true,   // Auto-clear on underflow
            .fixed_mclk = 0,
        };

        i2s_pin_config_t spk_pins = {
            .bck_io_num = SPK_I2S_BCLK,
            .ws_io_num = SPK_I2S_LRC,
            .data_out_num = SPK_I2S_DIN,
            .data_in_num = I2S_PIN_NO_CHANGE,
        };

        esp_err_t err = i2s_driver_install(SPK_I2S_PORT, &spk_config, 0, NULL);
        if (err != ESP_OK) {
            Serial.printf("[Audio] Speaker I2S install failed: %d\n", err);
            return false;
        }
        err = i2s_set_pin(SPK_I2S_PORT, &spk_pins);
        if (err != ESP_OK) {
            Serial.printf("[Audio] Speaker pin config failed: %d\n", err);
            return false;
        }
        i2s_zero_dma_buffer(SPK_I2S_PORT);

        // Allocate playback ring buffer (~2 seconds)
        if (!playbackBuffer.init(PLAYBACK_BUF_SIZE)) {
            return false;
        }

        Serial.println("[Audio] Speaker initialized");
        return true;
    }

    // Read a chunk of audio from the microphone
    // Returns number of bytes read
    size_t readMicrophone(uint8_t* buffer, size_t bufLen) {
        size_t bytesRead = 0;
        esp_err_t err = i2s_read(MIC_I2S_PORT, buffer, bufLen, &bytesRead, pdMS_TO_TICKS(100));
        if (err != ESP_OK) {
            Serial.printf("[Audio] Mic read error: %d\n", err);
            return 0;
        }

        // The INMP441 puts data in the upper 18 bits of a 32-bit word
        // with I2S_BITS_PER_SAMPLE_16BIT it maps correctly, but
        // we may need to amplify. Apply a simple gain.
        int16_t* samples = (int16_t*)buffer;
        size_t numSamples = bytesRead / 2;
        for (size_t i = 0; i < numSamples; i++) {
            int32_t val = samples[i];
            val = val * micGain / 100;
            // Clamp
            if (val > 32767) val = 32767;
            if (val < -32768) val = -32768;
            samples[i] = (int16_t)val;
        }

        return bytesRead;
    }

    // Feed audio from ring buffer to speaker DMA
    // Call this frequently from the main loop during playback
    void feedSpeaker() {
        if (playbackBuffer.available() < AUDIO_CHUNK_BYTES) return;

        uint8_t chunk[AUDIO_CHUNK_BYTES];
        size_t got = playbackBuffer.read(chunk, AUDIO_CHUNK_BYTES);
        if (got > 0) {
            size_t written = 0;
            i2s_write(SPK_I2S_PORT, chunk, got, &written, pdMS_TO_TICKS(50));
        }
    }

    void stopSpeaker() {
        i2s_zero_dma_buffer(SPK_I2S_PORT);
        playbackBuffer.clear();
    }

    // Silence the microphone DMA during playback to prevent echo feedback.
    void muteMicrophone() {
        i2s_stop(MIC_I2S_PORT);
    }

    // Re-enable the microphone and flush DMA buffers so any audio captured
    // while the speaker was playing does not get transcribed.
    void unmuteMicrophone() {
        i2s_start(MIC_I2S_PORT);
        i2s_zero_dma_buffer(MIC_I2S_PORT);
    }

    void setMicGain(int gainPercent) {
        micGain = gainPercent;
    }

    int getMicGain() const { return micGain; }

private:
    int micGain = 400;  // 4x amplification — INMP441 outputs low amplitude in 16-bit mode
};

#endif // AUDIO_H
