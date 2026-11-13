/* Original ESP32 RX-only backend for the ESP-SDR burst protocol.
 * Register sequence derived from ESP-IDF's ESP32 librftest.a: adctrig/mac_init.
 */
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_freertos_hooks.h"
#include "burst_serial.h"
#include "burst_gpio.h"
#include "burst_version.h"
#include "spectrum.h"
#include "rx_recalibration.h"
#include "rx_tuning.h"
#include "rx_lo.h"
#include "rx_bandwidth.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_rom_crc.h"
#include "esp_heap_caps.h"
#include "nvs_flash.h"
#include "soc/soc.h"
#include "soc/rtc.h"
#include "soc/dport_reg.h"
#include "soc/dport_access.h"
#include "heap_memory_layout.h"

/* Reserve both SRAM banks, including their instruction aliases. Mode 2 only
 * exposes 32 KiB to MAC; mode 3 exposes the entire 64 KiB capture aperture. */
SOC_RESERVE_MEMORY_REGION(0x3ffe8000, 0x3fff8000, esp32_rf_dump);
#define DUMP_CTRL   0x60033d90u
#define DUMP_STATUS 0x60033d94u
#define DUMP_BYTES  0x60033dc4u
#define RX_GAIN     0x3ff5c02cu
#define ADC_CTRL    0x3ff460a0u
#define ADC_ON_FORCE (BIT(9) | BIT(8)) /* Force-enable and ADC-on value. */
#define CAPACITY    16384u
#define MAX_SAMPLES (CAPACITY - 4)
#define SENTINEL    0xa55aa55au
static uint32_t *const samples = (void *)0x3ffe8000;
#include "validate_candidates.h"
static unsigned acquisition_option, clear_option;
static unsigned gain_max, gain_code = 40;
static bool hardware_agc = true;
/* Device monotonic microseconds sampled immediately before the dump trigger
 * register write. Not a calibrated RF arrival timestamp or host clock. */
static uint64_t capture_trigger_device_us;
/* Setup excludes dual_wait_trigger scheduling wait. Reset for each DSTREAM. */
static uint64_t capture_pretrigger_max_us;
static unsigned frequency_mhz = 2412;
/* Original ESP32 BBTOP RX filter: registers 1/2, seven-bit capacitor DAC.
 * Preserve bit 7 and restore PHY calibration before any retune or transfer. */
static int rx_filter = -1;
extern unsigned rom_chip_i2c_readReg(unsigned, unsigned, unsigned);
extern void rom_chip_i2c_writeReg(unsigned, unsigned, unsigned, unsigned);
static unsigned filter_saved[2];
static void filter_apply(void) {
    for (unsigned j = 0; j < 2; j++) {
        filter_saved[j] = rom_chip_i2c_readReg(0x67, 1, 1 + j);
        if (rx_filter >= 0)
            rom_chip_i2c_writeReg(0x67, 1, 1 + j, (filter_saved[j] & ~127u) | (unsigned)rx_filter);
    }
    esp_rom_delay_us(10);
}
static void filter_restore(void) {
    if (rx_filter >= 0)
        for (unsigned j = 0; j < 2; j++) rom_chip_i2c_writeReg(0x67, 1, 1 + j, filter_saved[j]);
}
extern void rom_pbus_workmode(void);
extern void rom_pbus_xpd_rx_on(int);
extern void rom_pbus_xpd_tx_off(void);
extern void rom_set_rxclk_en(int);

/* Stream acquisition errors are deferred until the current telemetry frame is complete. */
static bool deferred_reply;
static char deferred_error[256];
static void reply(const char *fmt, ...) {
    char text[256];
    va_list ap;
    va_start(ap, fmt);
    int length = vsnprintf(text, sizeof(text), fmt, ap);
    va_end(ap);
    if (deferred_reply) {
        if (!deferred_error[0]) snprintf(deferred_error, sizeof(deferred_error), "%s", text);
        return;
    }
    if (length > 0) burst_serial_send(text, length < sizeof(text) ? length : sizeof(text) - 1);
}

#include "dual_timing.h"

static void tune_rx(unsigned mhz);
static void apply_gain(void);
static bool rx_ready;
static void prepare_rx(void) {
    if (!rx_ready || rx_recalibration_stale()) {
        tune_rx(frequency_mhz);
        rx_ready = true;
    }
    rom_pbus_workmode();
    rom_pbus_xpd_tx_off();
    rom_pbus_xpd_rx_on(1);
    rom_set_rxclk_en(1);
    /* PBUS work-mode setup releases a forced RX gain; apply it afterwards. */
    apply_gain();
    if (rx_lo_select(rx_lo_plan(frequency_mhz).alternate)) esp_rom_delay_us(3000);
}

/* Clock selectors: 0=16 MS/s, 1=80 MS/s, 2=40 MS/s. Hardware sampling,
 * not software decimation. Rates inferred from capture-duration slopes. */
/* Experimental work uses only a prior validated non-aperture copy. */
static bool acquire_iq_with_validation(unsigned n, unsigned source, unsigned clock, unsigned *capture_us,
                                 void (*during_wait)(void *), void *context,
                                 unsigned (*validate_copy)(void *, unsigned), void *validation_context) {
    if (n < 256 || n > MAX_SAMPLES || source > 3 || clock > 2) {
        reply("ERR args\n");
        return false;
    }
    int64_t setup_start = esp_timer_get_time();
    if (rx_recalibration_stale()) prepare_rx();
    REG_WRITE(DUMP_CTRL, 0);
    if (!clear_option) {
        for (unsigned j = 0; j < CAPACITY; j++) samples[j] = SENTINEL;
    } else clear_unroll8(samples);
    filter_apply();
    /* RX clock forcing alone does not keep the ADC on. PHY gating otherwise
     * inserts short runs of the inactive converter's fixed I/Q value. */
    uint32_t adc_on = DPORT_REG_READ(ADC_CTRL) & ADC_ON_FORCE;
    DPORT_REG_WRITE(ADC_CTRL, DPORT_REG_READ(ADC_CTRL) | ADC_ON_FORCE);
    esp_rom_delay_us(2);
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    uint32_t byte_select = REG_READ(DUMP_BYTES);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,
                    (owner & ~DPORT_MAC_DUMP_MODE_M) | (3 << DPORT_MAC_DUMP_MODE_S));
    REG_WRITE(DUMP_BYTES, 0x03020100); /* Four distinct bytes, as in mac_init. */
    uint32_t ctrl = n | (source << 20) | ((clock == 0) << 16) | ((clock == 2) << 15);
    REG_WRITE(DUMP_CTRL, ctrl | BIT(31));
    uint64_t setup_us = (uint64_t)(esp_timer_get_time() - setup_start);
    if (setup_us > capture_pretrigger_max_us) capture_pretrigger_max_us = setup_us;
    dual_wait_trigger();
    int64_t start = esp_timer_get_time();
    capture_trigger_device_us = (uint64_t)start;
    REG_SET_BIT(DUMP_CTRL, BIT(19));
    REG_CLR_BIT(DUMP_CTRL, BIT(19));
    if (during_wait) during_wait(context);
    while (!(REG_READ(DUMP_CTRL) & BIT(18)) && esp_timer_get_time() - start < 20000) {}
    uint32_t result = REG_READ(DUMP_CTRL), status = REG_READ(DUMP_STATUS);
    unsigned elapsed = esp_timer_get_time() - start;
    REG_WRITE(DUMP_CTRL, 0);
    esp_rom_delay_us(10);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    REG_WRITE(DUMP_BYTES, byte_select);
    DPORT_REG_WRITE(ADC_CTRL, (DPORT_REG_READ(ADC_CTRL) & ~ADC_ON_FORCE) | adc_on);
    filter_restore();
    if (!(result & BIT(18)) || (status & 0x7fff) != n || (during_wait && elapsed >= 20000)) {
        reply("ERR capture_timeout\n");
        return false;
    }
    if (validate_copy) {
        unsigned bad = validate_copy(validation_context, n);
        if (bad != UINT_MAX) { reply("ERR capture_memory %u\n", bad); return false; }
    } else if (!acquisition_option) {
        for (unsigned j = 0; j < CAPACITY; j++) {
            if ((j < n && samples[j] == SENTINEL) || (j >= n && samples[j] != SENTINEL)) {
                reply("ERR capture_memory %u\n", j);
                return false;
            }
        }
    } else {
        unsigned bad = acquisition_option == 1 ? validate_split(samples,n) :
                       acquisition_option == 2 ? validate_aggregate(samples,n) : validate_unroll4(samples,n);
        if (bad != UINT_MAX) { reply("ERR capture_memory %u\n",bad);return false; }
    }
    *capture_us = elapsed;
    return true;
}

static bool acquire_iq_with_work(unsigned n, unsigned source, unsigned clock, unsigned *capture_us,
                                 void (*during_wait)(void *), void *context) {
    return acquire_iq_with_validation(n, source, clock, capture_us, during_wait, context, NULL, NULL);
}

static bool acquire_iq(unsigned n, unsigned source, unsigned clock, unsigned *capture_us) {
    return acquire_iq_with_work(n, source, clock, capture_us, NULL, NULL);
}

#include "profile_acquire.h"

static bool spectrum_acquire(unsigned n, unsigned rate, const uint32_t **data, unsigned *elapsed) {
    unsigned clock = rate == 6 ? 0 : rate == 1 ? 2 : 1;
    bool ok = acquire_iq(n, 0, clock, elapsed);
    *data = samples;
    return ok;
}

#include "ring_probe.h"

static void apply_gain(void) {
    uint32_t gain = REG_READ(RX_GAIN);
    if (hardware_agc)
        REG_CLR_BIT(RX_GAIN, BIT(23));
    else
        REG_WRITE(RX_GAIN, (gain & 0x7fffff) | (gain_code << 24) | BIT(23));
}

extern void set_chanfreq(unsigned mhz, unsigned mode);
extern void rom_set_rf_freq_offset(unsigned crystal, unsigned mhz, int offset);

static void tune_rx(unsigned mhz) {
    static unsigned calibrated_mhz;
    if (calibrated_mhz != mhz || rx_recalibration_stale()) {
        rx_recalibrate(mhz);
        calibrated_mhz = mhz;
    }
    rx_lo_plan_t plan = rx_lo_plan(mhz);
    rx_lo_select(false);
    bool channel = (mhz >= 2412 && mhz <= 2472 && (mhz - 2412) % 5 == 0) || mhz == 2484;
    /* Calibrate on a real channel before bypassing the channel-number mapping.
     * Use the PHY entry point even for repeated requests: the Wi-Fi API can
     * skip a channel it thinks is already selected after a direct PLL retune. */
    set_chanfreq(channel ? mhz : 2412, 0);
    if (!channel) {
        unsigned xtal = rtc_clk_xtal_freq_get();
        /* Channel setup pins its capacitor code. Release it before the ROM
         * retune, otherwise the SDM changes but the PLL can remain unlocked. */
        unsigned cap = ram_chip_i2c_readReg(0x62, 1, 0);
        ram_chip_i2c_writeReg(0x62, 1, 0, cap & ~0x80u);
        /* This ROM uses 1/1024 MHz offsets, unlike the newer kHz API. */
        int offset = (plan.offset_khz * 1024 + 500) / 1000;
        rom_set_rf_freq_offset(xtal == 26 ? 1 : xtal == 24 ? 2 : 0, plan.mhz, offset);
    }
}

#define IQ_BUFFER  samples
#define IQ_WORDS   MAX_SAMPLES
#define send_bytes burst_serial_send
#include "burst_capture.h"

/* Rate codes 0, 1 and 6 (80, 40 and 16 MS/s) are dump clocks 1, 2 and 0. */
static bool capture(unsigned n, unsigned rate, unsigned format) {
    unsigned elapsed;
    if (rate != 0 && rate != 1 && rate != 6) {
        reply("ERR rate\n");
        return false;
    }
    if (!acquire_iq(n, 0, rate == 0 ? 1 : rate == 1 ? 2 : 0, &elapsed)) return false;
    return burst_send_capture(n, format, elapsed);
}

#define frequency_valid rx_frequency_valid
#define BURST_ID        "ESP32SDR"
#define BURST_MAX_RATE  6
#include "burst_commands.h"
#include "detector_experiment.h"
#include "ascii_frame.h"
#include "detector_pipeline.h"
#include "pipeline_acquisition_options.h"
#include "calibration_hash.h"

#include "dual_timing_commands.h"
#include "detector_stream.h"

static void command(char *line) {
    if (detector_stream_command(line)) return;
    if (dual_timing_command(line)) return;
    if (calibration_hash_command(line)) return;
    if (pipeline_acquisition_options_command(line)) return;
    if (detector_pipeline_command(line)) return;
    if (!strncmp(line, "DET1 ", 5)) detpipe_clear();
    if (detector_command(line)) return;
    if (burst_version_command(line)) return;
    if (burst_gpio_command(line)) return;
#ifdef RING_PROBE
    if (ring_probe_command(line)) return;
#endif
    if (spectrum_command(line, frequency_mhz, spectrum_acquire)) return;
    if (burst_common_command(line)) return;
    unsigned n;
    char extra;
    if (!strcmp(line, "CAPS"))
        reply(
            "CAPS DSTREAMIDLEWAKE DSTREAMIDLE DSTREAMIQ DSTREAM DUALTIMING BGPOLICY CALHASH " DETPIPE_HEALTH_CAPABILITY "PIPEKEEP PIPECOPY ACQOPT CLEAROPT PIPEKERNEL DET1 VERSION GPIO SPEC SPECN SPECCAPS SPECSTAT DCT "
#if !CONFIG_ESP_SDR_CP2102_VIEWER_COMPAT
            "UARTBAUD "
#endif
            "RXLIMITS SERIALLEASE TUNEEXT RX40 RX16 LPFANA GAIN HWAGC IQ8\n");
    else if (sscanf(line, "BANDWIDTH %u %c", &n, &extra) == 1 &&
             (!n || (n >= RX_BANDWIDTH_MIN && n <= RX_BANDWIDTH_MAX))) {
        rx_filter = rx_bandwidth_dcap(n);
        reply("OK\n");
    } else if (!strcmp(line, "LPF AUTO")) {
        rx_filter = -1;
        reply("OK\n");
    } else if (sscanf(line, "LPF %u %c", &n, &extra) == 1 && n <= 127) {
        rx_filter = n;
        reply("OK\n");
    } else if (!strcmp(line, "LPF?"))
        reply("LPF %d %u %u\n", rx_filter, rom_chip_i2c_readReg(0x67, 1, 1),
              rom_chip_i2c_readReg(0x67, 1, 2));
    else if (!strcmp(line, "LIMITS?")) {
        reply(
            "LIMITS {\"gain\":[0,%u,1],\"bandwidth\":[%u,%u,1,0],\"rates\":[80000000,40000000,16000000],\"bits\":[8,10]}\n",
            gain_max, RX_BANDWIDTH_MIN, RX_BANDWIDTH_MAX);
    } else if (!strcmp(line, "GAIN?"))
        reply("GAIN %s %d 0 %u %u\n", hardware_agc ? "HARDWARE" : "MANUAL",
              hardware_agc ? -1 : (int)gain_code, gain_max, (unsigned)((REG_READ(RX_GAIN) >> 23) & 1));
    else if (!strcmp(line, "GAIN HARDWARE")) {
        hardware_agc = true;
        apply_gain();
        reply("OK\n");
    } else if (sscanf(line, "GAIN MANUAL %u %c", &n, &extra) == 1 && n <= gain_max) {
        hardware_agc = false;
        gain_code = n;
        apply_gain();
        reply("OK\n");
    } else
        reply("ERR command\n");
}

void app_main(void) {
    esp_log_level_set("*", ESP_LOG_NONE);
    /* NVS may contain device calibration and owner settings. Never erase it
     * to recover from incompatible/full/corrupt storage. Fail before radio
     * initialization; recovery requires a separately reviewed backup/migration. */
    esp_err_t e = nvs_flash_init();
    if (e != ESP_OK) {
        /* Idle instead of aborting: an abort reboots immediately under the
         * release panic configuration and would repeat this failure in a loop.
         * Repeat the notice so a host that connects later still sees it. */
        for (;;) {
            printf("ERR nvs_init %d storage_preserved; review a private backup/migration before recovery\n", (int)e);
            fflush(stdout);
            vTaskDelay(pdMS_TO_TICKS(5000));
        }
    }
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    ESP_ERROR_CHECK(esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE));
    prepare_rx();
    gain_max = (REG_READ(RX_GAIN) >> 8) & 127;
    REG_CLR_BIT(RX_GAIN, BIT(23)); /* Hardware AGC is the default. */
    fflush(stdout);
    burst_serial_init();
    burst_serial_serve(command);
}
