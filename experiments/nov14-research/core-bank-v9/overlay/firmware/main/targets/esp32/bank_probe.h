#pragma once
/* Isolated finite map diagnostic. Both IDF-identified MAC pools, 64 KiB plus instruction aliases
 * are reserved, including the complete production aperture. Never read live SRAM.
 * No changing an ownership mode while enabled. No persistent/NVS writes. */

#include "bank_bench.h"
static bool bank_live_command(const char *line) {
    if(strncmp(line,"BANKLIVE",8)) return false;
    uint64_t a[1];
    if(!bank_arguments(line+8,a,1) || (a[0]!=1 && a[0]!=2)) {reply("ERR bank_args\n");return true;}
    unsigned mode=(unsigned)a[0];
    prepare_rx();REG_WRITE(DUMP_CTRL,0);
    volatile uint32_t *all=(volatile uint32_t *)0x3ffe8000;
    unsigned bank=mode==1?1:0;
    volatile uint32_t *active=all+8192*bank,*inactive=all+8192*(1-bank);
    for(unsigned i=0;i<8192;i++){active[i]=SENTINEL;inactive[i]=UINT32_C(0x5a000000)^i;}
    filter_apply();
    uint32_t adc=DPORT_REG_READ(ADC_CTRL)&ADC_ON_FORCE;
    DPORT_REG_WRITE(ADC_CTRL,DPORT_REG_READ(ADC_CTRL)|ADC_ON_FORCE);esp_rom_delay_us(2);
    uint32_t own=DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG),bytes=REG_READ(DUMP_BYTES);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,(own&~DPORT_MAC_DUMP_MODE_M)|(mode<<DPORT_MAC_DUMP_MODE_S));
    REG_WRITE(DUMP_BYTES,0x03020100);REG_WRITE(DUMP_CTRL,8188|BIT(16)|BIT(31));
    int64_t start=esp_timer_get_time();REG_SET_BIT(DUMP_CTRL,BIT(19));REG_CLR_BIT(DUMP_CTRL,BIT(19));
    bool done_before=!!(REG_READ(DUMP_CTRL)&BIT(18));
    unsigned read_bad=0;
    for(unsigned i=0;i<8192;i++) if(inactive[i]!=(UINT32_C(0x5a000000)^i))read_bad++;
    unsigned read_us=esp_timer_get_time()-start;
    for(unsigned i=0;i<8192;i++)inactive[i]=UINT32_C(0x6b000000)^i;
    unsigned work_us=esp_timer_get_time()-start;
    while(!(REG_READ(DUMP_CTRL)&BIT(18)) && esp_timer_get_time()-start<20000) {}
    uint32_t ctrl=REG_READ(DUMP_CTRL),status=REG_READ(DUMP_STATUS);unsigned elapsed=esp_timer_get_time()-start;
    REG_WRITE(DUMP_CTRL,0);esp_rom_delay_us(10);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,own);REG_WRITE(DUMP_BYTES,bytes);
    DPORT_REG_WRITE(ADC_CTRL,(DPORT_REG_READ(ADC_CTRL)&~ADC_ON_FORCE)|adc);filter_restore();
    unsigned final_bad=0,active_bad=0;
    for(unsigned i=0;i<8192;i++) {
        if(inactive[i]!=(UINT32_C(0x6b000000)^i))final_bad++;
        if(i<8188?(active[i]==SENTINEL):(active[i]!=SENTINEL))active_bad++;
    }
    reply("BANKLIVE %u %u %u %u %u %u %u %u %u %u\n",mode,!!(ctrl&BIT(18)),status&0x7fff,done_before,read_bad,final_bad,active_bad,read_us,work_us,elapsed);
    return true;
}
static bool bank_probe_command(const char *line) {
    if(bank_bench_command(line))return true;
    if(bank_live_command(line))return true;
    if(strncmp(line,"BANKPROBE",9)) return false;
    uint64_t a[2];
    if(!bank_arguments(line+9,a,2) || a[0]>3 || a[1]<256 || a[1]>8188) {
        reply("ERR bank_args\n");return true;
    }
    unsigned mode=(unsigned)a[0],n=(unsigned)a[1];
    prepare_rx();
    volatile uint32_t *all=(volatile uint32_t *)0x3ffe8000;
    REG_WRITE(DUMP_CTRL,0);
    for(unsigned i=0;i<16384;i++) all[i]=SENTINEL;
    filter_apply();
    uint32_t adc=DPORT_REG_READ(ADC_CTRL)&ADC_ON_FORCE;
    DPORT_REG_WRITE(ADC_CTRL,DPORT_REG_READ(ADC_CTRL)|ADC_ON_FORCE);
    esp_rom_delay_us(2);
    uint32_t own=DPORT_REG_READ(DPORT_IRAM_DRAM_AHB_SEL_REG),bytes=REG_READ(DUMP_BYTES);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,(own&~DPORT_MAC_DUMP_MODE_M)|(mode<<DPORT_MAC_DUMP_MODE_S));
    REG_WRITE(DUMP_BYTES,0x03020100);
    REG_WRITE(DUMP_CTRL,n|BIT(16)|BIT(31));
    int64_t start=esp_timer_get_time();
    REG_SET_BIT(DUMP_CTRL,BIT(19));REG_CLR_BIT(DUMP_CTRL,BIT(19));
    while(!(REG_READ(DUMP_CTRL)&BIT(18)) && esp_timer_get_time()-start<2000) {}
    uint32_t ctrl=REG_READ(DUMP_CTRL),status=REG_READ(DUMP_STATUS);
    unsigned elapsed=esp_timer_get_time()-start;
    REG_WRITE(DUMP_CTRL,0);esp_rom_delay_us(10);
    DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG,own);REG_WRITE(DUMP_BYTES,bytes);
    DPORT_REG_WRITE(ADC_CTRL,(DPORT_REG_READ(ADC_CTRL)&~ADC_ON_FORCE)|adc);filter_restore();
    unsigned changed[2]={0},first[2]={8192,8192},last[2]={0};
    for(unsigned i=0;i<16384;i++) if(all[i]!=SENTINEL){unsigned b=i/8192,j=i%8192;changed[b]++;if(j<first[b])first[b]=j;last[b]=j+1;}
    reply("BANKPROBE %u %u %u %u %u\n",mode,n,!!(ctrl&BIT(18)),status&0x7fff,elapsed);
    for(unsigned b=0;b<2;b++) reply("BANK %u %u %u %u\n",b,changed[b],first[b],last[b]);
    reply("BANKEND\n");
    return true;
}
