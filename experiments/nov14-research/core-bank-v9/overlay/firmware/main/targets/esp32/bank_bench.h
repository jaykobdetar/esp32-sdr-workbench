#pragma once
#include "esp_memory_utils.h"
#include "pipeline_energy3.h"
#include "bank_energy_clear.h"
#include "dstream_idle.h"
#include "dstream_idle_wake.h"
typedef struct {uint64_t trigger;uint32_t mean,peak;} bank_row_t;
_Static_assert(sizeof(bank_row_t)==16,"bank trace wire size");
static uint32_t *bank_keep;
static bool bank_keep_valid;
static uint64_t bank_keep_trigger;
static void bank_release_other_retention(void);
static void bank_discard(void) {
    if(bank_keep)heap_caps_free(bank_keep);
    bank_keep=NULL;bank_keep_valid=false;bank_keep_trigger=0;
}
/* Strict decimal parser: no signed, wrapping, suffixed or extra arguments. */
static bool bank_arguments(const char *text,uint64_t *out,unsigned count) {
    for(unsigned i=0;i<count;i++) {
        if(*text++!=' ')return false;
        uint64_t value=0;
        if(*text<'0'||*text>'9')return false;
        while(*text>='0'&&*text<='9') {
            unsigned digit=*text++-'0';
            if(value>(UINT64_MAX-digit)/10)return false;
            value=value*10+digit;
        }
        out[i]=value;
    }
    return !*text;
}
static bool bank_ptr_ok(void *p,size_t n) {
    uintptr_t a=(uintptr_t)p,b=a+n-1;
    return p && b>=a && esp_ptr_in_dram(p) && esp_ptr_in_dram((void *)b) &&
        (b<0x3ffe8000 || a>=0x3fff8000);
}
static bool bank_process(uint32_t *w,unsigned fused,bank_row_t *row) {
    if(fused)return bank_energy_clear(w,&row->mean,&row->peak);
    uint32_t bad=0;
    for(unsigned j=0;j<8188;j++)bad|=w[j]==SENTINEL;
    for(unsigned j=8188;j<8192;j++)bad|=w[j]^SENTINEL;
    if(bad)return false;
    pipeline_energy_flash_3(w,8188,&row->mean,&row->peak);
    for(unsigned j=0;j<8192;j++)w[j]=SENTINEL;
    return true;
}
static bool bank_bench_command(const char *line) {
    if(!strcmp(line,"BANKSTATUS?")) {
        unsigned caps=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT|MALLOC_CAP_DMA;
        reply("BANKSTATUS {\"version\":1,\"retained_valid\":%s,\"retained_bytes\":%u,\"free_dma_bytes\":%u,\"largest_dma_bytes\":%u}\n",
              bank_keep_valid?"true":"false",bank_keep?8188u*4:0u,
              (unsigned)heap_caps_get_free_size(caps),(unsigned)heap_caps_get_largest_free_block(caps));
        return true;
    }
    if(!strcmp(line,"BANKGET")) {
        if(!bank_keep_valid){reply("ERR bank_empty\n");return true;}
        uint32_t crc=esp_rom_crc32_le(0,(void *)bank_keep,8188*4);
        reply("BANKDATA 8188 %08lx %" PRIu64 "\n",(unsigned long)crc,bank_keep_trigger);
        burst_serial_send(bank_keep,8188*4);bank_discard();return true;
    }
    if(!strcmp(line,"BANKDROP")){bank_discard();reply("OK\n");return true;}
    bool scheduled=!strncmp(line,"BANKAT",6);
    if(!scheduled && strncmp(line,"BANKRUN",7))return false;
    uint64_t a[4]={0},now=esp_timer_get_time();
    bool parsed=bank_arguments(line+(scheduled?6:7),a,scheduled?4:2);
    if(!parsed || a[0]<2 || a[0]>1024 || a[1]>1 || dual_armed || dual_next ||
       (scheduled && (a[3]<750000 || a[3]>2000000 || a[2]<now+1000 || a[2]>now+2000000))) {
        reply("ERR bank_args\n");return true;
    }
    unsigned count=(unsigned)a[0],fused=(unsigned)a[1],period_ns=scheduled?(unsigned)a[3]:0;
    uint64_t deadline=scheduled?a[2]:0;
    /* A new acquisition owns retention. Release ordinary detector pages before
     * bank allocation, and vice versa through the detpipe clear hook. */
    bank_release_other_retention();
    bank_keep_valid=false;
    if(!bank_keep)bank_keep=heap_caps_malloc(8188*4,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT|MALLOC_CAP_DMA);
    bank_row_t *rows=heap_caps_malloc(count*sizeof(bank_row_t),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT|MALLOC_CAP_DMA);
    if(!bank_ptr_ok(bank_keep,8188*4)||!bank_ptr_ok(rows,count*sizeof(bank_row_t))) {if(rows)heap_caps_free(rows);bank_discard();reply("ERR bank_memory\n");return true;}
    dstream_idle_t idle={0};if(!dstream_wake_begin(&idle)){heap_caps_free(rows);bank_discard();reply("ERR bank_idle\n");return true;}
    prepare_rx();REG_WRITE(DUMP_CTRL,0);for(unsigned j=0;j<16384;j++)samples[j]=SENTINEL;
    unsigned status=0,completed=0,processed=0,max_work=0;uint64_t start=esp_timer_get_time();
    for(unsigned k=0;k<count;k++) {
        /* Do not use an unvalidated pending bank across a recalibration. */
        if(rx_recalibration_stale()){status=5;break;}
        uint64_t target=scheduled?deadline+(uint64_t)k*period_ns/1000:0;
        while(target && (uint64_t)esp_timer_get_time()+2000<target) {
            if(burst_serial_stop_requested()){status=3;break;}
            vTaskDelay(1);
        }
        if(status)break;
        unsigned bank=k&1u,mode=bank?1:2;
        filter_apply();uint32_t adc=DPORT_REG_READ(ADC_CTRL)&ADC_ON_FORCE;
        DPORT_REG_WRITE(ADC_CTRL,DPORT_REG_READ(ADC_CTRL)|ADC_ON_FORCE);esp_rom_delay_us(2);
        uint32_t own=DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG),bytes=REG_READ(DUMP_BYTES);
        DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,(own&~DPORT_MAC_DUMP_MODE_M)|(mode<<DPORT_MAC_DUMP_MODE_S));
        REG_WRITE(DUMP_BYTES,0x03020100);REG_WRITE(DUMP_CTRL,8188|BIT(16)|BIT(31));
        while(target && (uint64_t)esp_timer_get_time()<target) {}
        uint64_t trigger=esp_timer_get_time();rows[k].trigger=trigger;
        REG_SET_BIT(DUMP_CTRL,BIT(19));REG_CLR_BIT(DUMP_CTRL,BIT(19));
        bool valid=true;
        if(k) {valid=bank_process(samples+8192*(1-bank),fused,&rows[k-1]);if(valid)processed++;}
        unsigned work=esp_timer_get_time()-trigger;if(work>max_work)max_work=work;
        while(!(REG_READ(DUMP_CTRL)&BIT(18)) && esp_timer_get_time()-trigger<20000) {}
        uint32_t ctrl=REG_READ(DUMP_CTRL),dump_status=REG_READ(DUMP_STATUS);
        unsigned elapsed=esp_timer_get_time()-trigger;
        REG_WRITE(DUMP_CTRL,0);esp_rom_delay_us(10);
        DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,own);REG_WRITE(DUMP_BYTES,bytes);
        DPORT_REG_WRITE(ADC_CTRL,(DPORT_REG_READ(ADC_CTRL)&~ADC_ON_FORCE)|adc);filter_restore();
        if(!valid){status=2;break;}
        if(!(ctrl&BIT(18)) || (dump_status&0x7fff)!=8188 || elapsed>=20000){status=1;break;}
        completed++;
        if(burst_serial_stop_requested()){status=3;break;}
        dstream_wake_service(&idle);
        if(esp_timer_get_time()-start>5000000){status=4;break;}
    }
    dstream_wake_end(&idle);
    /* Keep an immutable copy of the last capture. It is still checked over its
     * entire bank before any successful BANKGET becomes available. */
    if(!status && completed==count) {
        uint32_t *last=samples+8192*((count-1)&1u);
        memcpy(bank_keep,last,8188*4);
        if(!bank_process(last,fused,&rows[count-1]))status=2;
        else {processed++;bank_keep_valid=true;bank_keep_trigger=rows[count-1].trigger;}
    }
    uint64_t end=esp_timer_get_time();
    if(status || processed!=count){heap_caps_free(rows);bank_discard();reply("ERR bank_run %u %u %u\n",status,completed,processed);return true;}
    uint32_t crc=esp_rom_crc32_le(0,(void *)rows,count*sizeof(bank_row_t));
    reply("BANKRUN %u 8188 %08lx %" PRIu64 " %" PRIu64 " %u %u %u\n",count,(unsigned long)crc,start,end,max_work,idle.observed,idle.fallbacks);
    bool sent=burst_serial_send(rows,count*sizeof(bank_row_t));heap_caps_free(rows);
    if(sent) (void)burst_serial_finish("BANKEND\n",8);
    return true;
}
