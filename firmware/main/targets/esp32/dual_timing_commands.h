#pragma once
/* Strict bounded decimal arguments. No wrapping, signs or suffixes. */
static bool dual_arguments(const char *text, uint64_t *out, unsigned n) {
    for (unsigned i=0; i<n; i++) {
        if (*text++ != ' ') return false;
        uint64_t value=0;
        if (*text<'0' || *text>'9') return false;
        while (*text>='0' && *text<='9') {
            unsigned digit=*text++-'0';
            if (value>(UINT64_MAX-digit)/10) return false;
            value=value*10+digit;
        }
        out[i]=value;
    }
    return !*text;
}
static bool dual_timing_command(const char *line) {
    if (!strcmp(line,"CLOCK?")) {
        reply("CLOCK %" PRIu64 "\n", (uint64_t)esp_timer_get_time()); return true;
    }
    if (!strcmp(line,"TRACECLEAR")) {
        dual_trace_end(); dual_armed=false;
        if (dual_trace) heap_caps_free(dual_trace);
        dual_trace=NULL;dual_count=0;reply("OK\n");return true;
    }
    if (!strcmp(line,"TRACEGET")) {
        if (!dual_trace || !dual_count) {reply("ERR no_trace\n");return true;}
        uint32_t crc=esp_rom_crc32_le(0,(const uint8_t *)dual_trace,dual_count*4);
        reply("TRACE %u %" PRIu64 " %08" PRIx32 " %u %u %u %u\n",dual_count,dual_first,crc,
              (unsigned)dual_overflow,dual_late,dual_skipped,dual_period);
        burst_serial_send(dual_trace,dual_count*4);return true;
    }
    if (!strncmp(line,"TRACEARM",8)) {
        uint64_t a[3],now=esp_timer_get_time();
        if (!dual_arguments(line+8,a,3) || a[0]<now+10000 || a[0]>now+5000000 ||
            (a[1] && (a[1]<1600 || a[1]>10000)) || a[2]>31) {
            reply("ERR trace_args\n");return true;
        }
        dual_armed_deadline=a[0];dual_period=a[1];dual_yield_phase=a[2];dual_armed=true;
        reply("OK\n");return true;
    }
    if (!strncmp(line,"TIMEDCAP",8)) {
        uint64_t a[1],now=esp_timer_get_time();
        if (!dual_arguments(line+8,a,1) || a[0]<now+10000 || a[0]>now+5000000) {
            reply("ERR timedcap_args\n");return true;
        }
        if (dual_armed) {reply("ERR trace_armed\n");return true;}
        prepare_rx();dual_next=a[0];dual_period=0;unsigned elapsed=0;
        bool ok=acquire_iq(MAX_SAMPLES,0,0,&elapsed);dual_next=0;
        if (ok) {
            reply("TIMEDCAP %" PRIu64 "\n",capture_trigger_device_us);
            burst_send_capture(MAX_SAMPLES,20,elapsed);
        }
        return true;
    }
    return false;
}
