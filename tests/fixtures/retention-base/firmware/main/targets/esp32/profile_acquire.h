#pragma once
#include "profile_stats.h"
/* Instrumented sibling: original acquisition and DET1 code remain untouched. */
static void profile_prepare(uint32_t *row) {
    int64_t a = esp_timer_get_time();
    bool needs_prepare = !rx_ready;
    if (!needs_prepare) {
        int64_t check = esp_timer_get_time();
        needs_prepare = rx_recalibration_stale();
        row[P_CAL_CHECK] += esp_timer_get_time() - check;
    }
    if (needs_prepare) {
        int64_t c = esp_timer_get_time();
        tune_rx(frequency_mhz); /* Shares the original cached calibration state. */
        row[P_TUNE_CAL] += esp_timer_get_time() - c;
        rx_ready = true;
    }
    int64_t b = esp_timer_get_time();
    rom_pbus_workmode();
    rom_pbus_xpd_tx_off();
    rom_pbus_xpd_rx_on(1);
    rom_set_rxclk_en(1);
    row[P_RX_PREP] += esp_timer_get_time() - b;
    b = esp_timer_get_time();
    apply_gain();
    row[P_GAIN] += esp_timer_get_time() - b;
    b = esp_timer_get_time();
    if (rx_lo_select(rx_lo_plan(frequency_mhz).alternate)) esp_rom_delay_us(3000);
    row[P_RX_PREP] += esp_timer_get_time() - b;
    row[P_PREPARE] += esp_timer_get_time() - a;
}
static bool profile_acquire(unsigned n, unsigned source, unsigned clock, unsigned *capture_us, uint32_t *row) {
    int64_t acquire_start = esp_timer_get_time(), a;
    if (n < 256 || n > MAX_SAMPLES || source > 3 || clock > 2) { reply("ERR args\n"); return false; }
    a = esp_timer_get_time();
    bool stale = rx_recalibration_stale();
    row[P_CAL_CHECK] += esp_timer_get_time() - a;
    row[P_PREPARE] += row[P_CAL_CHECK];
    if (stale) profile_prepare(row);
    a = esp_timer_get_time();
    REG_WRITE(DUMP_CTRL, 0);
    row[P_REG_SETUP] += esp_timer_get_time() - a;
    a = esp_timer_get_time();
    for (unsigned j = 0; j < CAPACITY; j++) samples[j] = SENTINEL;
    row[P_CLEAR] = esp_timer_get_time() - a;
    a = esp_timer_get_time();
    filter_apply();
    row[P_FILTER_APPLY] = esp_timer_get_time() - a;
    a = esp_timer_get_time();
    uint32_t adc_on = DPORT_REG_READ(ADC_CTRL) & ADC_ON_FORCE;
    DPORT_REG_WRITE(ADC_CTRL, DPORT_REG_READ(ADC_CTRL) | ADC_ON_FORCE);
    esp_rom_delay_us(2);
    uint32_t owner = DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG);
    uint32_t byte_select = REG_READ(DUMP_BYTES);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,
                    (owner & ~DPORT_MAC_DUMP_MODE_M) | (3 << DPORT_MAC_DUMP_MODE_S));
    REG_WRITE(DUMP_BYTES, 0x03020100);
    uint32_t ctrl = n | (source << 20) | ((clock == 0) << 16) | ((clock == 2) << 15);
    REG_WRITE(DUMP_CTRL, ctrl | BIT(31));
    row[P_REG_SETUP] += esp_timer_get_time() - a;
    int64_t start = esp_timer_get_time();
    REG_SET_BIT(DUMP_CTRL, BIT(19));
    REG_CLR_BIT(DUMP_CTRL, BIT(19));
    while (!(REG_READ(DUMP_CTRL) & BIT(18)) && esp_timer_get_time() - start < 20000) {}
    uint32_t result = REG_READ(DUMP_CTRL), status = REG_READ(DUMP_STATUS);
    unsigned elapsed = esp_timer_get_time() - start;
    row[P_TRIGGER] = elapsed;
    a = esp_timer_get_time();
    REG_WRITE(DUMP_CTRL, 0);
    esp_rom_delay_us(10);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);
    REG_WRITE(DUMP_BYTES, byte_select);
    DPORT_REG_WRITE(ADC_CTRL, (DPORT_REG_READ(ADC_CTRL) & ~ADC_ON_FORCE) | adc_on);
    row[P_REG_RESTORE] = esp_timer_get_time() - a;
    a = esp_timer_get_time();
    filter_restore();
    row[P_FILTER_RESTORE] = esp_timer_get_time() - a;
    if (!(result & BIT(18)) || (status & 0x7fff) != n) {
        row[P_ACQUIRE] = esp_timer_get_time() - acquire_start;
        reply("ERR capture_timeout\n"); return false;
    }
    a = esp_timer_get_time();
    for (unsigned j = 0; j < CAPACITY; j++) {
        if ((j < n && samples[j] == SENTINEL) || (j >= n && samples[j] != SENTINEL)) {
            row[P_VALIDATE] = esp_timer_get_time() - a;
            row[P_ACQUIRE] = esp_timer_get_time() - acquire_start;
            reply("ERR capture_memory %u\n", j); return false;
        }
    }
    row[P_VALIDATE] = esp_timer_get_time() - a;
    *capture_us = elapsed;
    row[P_ACQUIRE] = esp_timer_get_time() - acquire_start;
    return true;
}
