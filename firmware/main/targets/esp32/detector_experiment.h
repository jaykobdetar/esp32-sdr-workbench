#pragma once
/* Experimental DET1 protocol; finite runs only, no spontaneous output. */
#include "detector_energy.h"
#include "detector_background.h"
static uint32_t *det_retained;
static unsigned det_retained_n, det_retained_capture_us;

static bool detector_command(const char *line) {
    if (!strcmp(line, "DETINFO?")) {
        reply("DETINFO 1 5000 16 64\n");
        return true;
    }
    if (!strcmp(line, "DETGET")) {
        if (!det_retained_n) reply("ERR no_retained_event\n");
        else {
            memcpy(samples, det_retained, det_retained_n * sizeof(uint32_t));
            burst_send_capture(det_retained_n, 20, det_retained_capture_us);
        }
        return true;
    }
    if (strncmp(line, "DET1", 4)) return false;
    unsigned ms, n, rate, ratio, retain;
    char extra;
    if (sscanf(line, "DET1 %u %u %u %u %u %c", &ms, &n, &rate, &ratio, &retain, &extra) != 5 ||
        ms < 1 || ms > 5000 || n < 256 || n > MAX_SAMPLES ||
        (rate != 0 && rate != 1 && rate != 6) || ratio < 1000 || ratio > 1000000 || retain > 1) {
        reply("ERR detector_args\n");
        return true;
    }
    det_retained_n = 0;
    if (det_retained) { heap_caps_free(det_retained); det_retained = NULL; }
    if (retain) {
        det_retained = heap_caps_malloc(n * sizeof(uint32_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        if (!det_retained) { reply("ERR detector_memory\n"); return true; }
    }
    prepare_rx();
    uint32_t gain_register_start = REG_READ(RX_GAIN);
    uint64_t retained_trigger_us = 0, first_trigger_us = 0, last_trigger_us = 0;
    unsigned retained_generation = 0;
    reply("DET1 BEGIN %u %u %u %u %u %u\n", ms, n, rate, ratio, retain, frequency_mhz);
    unsigned captures = 0, events = 0, best_ratio = 0, status = 0;
    detector_background_t background = detector_background_start(detector_background_policy);
    uint64_t trigger_us = 0, acquisition_us = 0, analysis_us = 0, retain_us = 0;
    int64_t start = esp_timer_get_time();
    while (esp_timer_get_time() - start < (int64_t)ms * 1000) {
        unsigned captured_us;
        int64_t a = esp_timer_get_time();
        if (!acquire_iq(n, 0, rate == 0 ? 1 : rate == 1 ? 2 : 0, &captured_us)) { status = 1; break; }
        int64_t b = esp_timer_get_time();
        acquisition_us += b - a; trigger_us += captured_us;
        uint32_t mean, peak;
        detector_energy(samples, n, &mean, &peak);
        captures++;
        if (!first_trigger_us) first_trigger_us = capture_trigger_device_us;
        last_trigger_us = capture_trigger_device_us;
        unsigned score;
        if (detector_background_step(&background, mean, peak, ratio, &score)) {
            events++;
            if (score > best_ratio) {
                best_ratio = score;
                if (retain) {
                    int64_t c = esp_timer_get_time();
                    memcpy(det_retained, samples, n * sizeof(uint32_t));
                    det_retained_n = n; det_retained_capture_us = captured_us;
                    retained_trigger_us = capture_trigger_device_us;
                    retained_generation = captures;
                    retain_us += esp_timer_get_time() - c;
                }
            }
        }
        analysis_us += esp_timer_get_time() - b;
        /* Yield deliberately, included in elapsed time, to avoid watchdog starvation. */
        if ((captures & 31) == 0) vTaskDelay(1);
    }
    uint64_t elapsed = esp_timer_get_time() - start;
    char summary[1600];
    int length = snprintf(summary, sizeof(summary),
        "DET1 END {\"version\":1,\"status\":%u,\"captures\":%u,\"detections\":%u,"
        "\"background_policy\":%u,\"background_q16\":%" PRIu64 ",\"background_adc2\":%u,\"best_ratio_milli\":%u,\"wall_elapsed_us\":%" PRIu64 ","
        "\"trigger_to_done_us\":%" PRIu64 ",\"acquire_call_us\":%" PRIu64 ","
        "\"processing_us\":%" PRIu64 ",\"retention_copy_us\":%" PRIu64 ","
        "\"retained_samples\":%u,\"frequency_mhz\":%u,\"total_samples\":%" PRIu64 ","
        "\"analyzed_samples\":%" PRIu64 ",\"sample_rate_hz\":%u,\"errors\":%u,\"warmup_captures\":%u,\"acquisition_option\":%u,\"clear_option\":%u,\"gain_register_start\":%" PRIu32 ",\"gain_register_end\":%" PRIu32 ",\"hardware_agc\":%u,\"gain_index_requested\":%u,\"first_trigger_device_us\":%" PRIu64 ",\"last_trigger_device_us\":%" PRIu64 ",\"retained_trigger_device_us\":%" PRIu64 ",\"retained_generation\":%u}\n",
        status, captures, events, detector_background_state_policy(&background), background.q16, (unsigned)(background.q16 / DETECTOR_BACKGROUND_SCALE), best_ratio, elapsed, trigger_us, acquisition_us,
        analysis_us - retain_us, retain_us, det_retained_n, frequency_mhz,
        (uint64_t)captures * n, (uint64_t)captures * (n / 64) * 64,
        rate == 0 ? 80000000u : rate == 1 ? 40000000u : 16000000u,
        status ? 1u : 0u, captures < 16 ? captures : 16u,acquisition_option,clear_option, gain_register_start, (uint32_t)REG_READ(RX_GAIN),
        (unsigned)hardware_agc, gain_code, first_trigger_us, last_trigger_us, retained_trigger_us, retained_generation);
    if (length > 0 && length < sizeof(summary)) burst_serial_send(summary, length);
    else reply("ERR detector_summary\n");
    return true;
}
