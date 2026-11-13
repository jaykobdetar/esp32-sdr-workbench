#pragma once
/* Optional sparse snapshots. One writer; packed pages remain immutable until
 * the last framed chunk is sent. Only the previous, CPU-owned copy is read. */
typedef struct {
    unsigned every,phase,produced,sent,skipped,errors,offset,cursor;
    bool busy,metadata,crc_ready,timing_committed;
    unsigned crc_offset,last_attempt;
    uint32_t packed_crc;
    uint64_t pack_us,crc_us;
    uint32_t generation;
    uint8_t frame[48];
} dstream_iq_t;
static dstream_iq_t dstream_iq;
static int dstream_iq_allocate(const uint32_t *raw) {
    if(!detpipe_safe_buffer(&dstream_iq,sizeof(dstream_iq))) return false;
    for(size_t left=DETPIPE_MAX_PACKED;left;) {
        unsigned page=detpipe_page_count;
        if(page>=DETPIPE_MAX_PAGES) return false;
        size_t n=left>DETPIPE_PAGE_BYTES?DETPIPE_PAGE_BYTES:left;
        uint8_t *p=heap_caps_malloc(n,DETPIPE_ALLOC_CAPS);
        if(!detpipe_safe_buffer(p,n)) {if(p) heap_caps_free(p);return false;}
        uintptr_t lo=(uintptr_t)p,hi=lo+n-1,base=(uintptr_t)raw;
        bool disjoint=hi<base || lo>base+MAX_SAMPLES*sizeof(uint32_t)-1;
        for(unsigned prev=0;prev<page;prev++) {
            uintptr_t other=(uintptr_t)detpipe_pages[prev];
            disjoint=disjoint && (hi<other || lo>other+detpipe_page_sizes[prev]-1);
        }
        /* Corrupt allocator: avoid alias/double frees, require reset. */
        if(!disjoint) return -1;
        detpipe_pages[page]=p;detpipe_page_sizes[page]=n;
        detpipe_page_count++;left-=n;
    }
    return true;
}
static void dstream_iq_crc(void) {
    uint32_t crc=esp_rom_crc32_le(0,dstream_iq.frame,44);
    memcpy(dstream_iq.frame+44,&crc,4);
}
static void dstream_iq_snapshot(detpipe_state_t *p) {
    if(!dstream_iq.every || !p->pending || p->generation==dstream_iq.last_attempt ||
        p->generation%dstream_iq.every!=dstream_iq.phase) return;
    dstream_iq.last_attempt=p->generation;
    if(dstream_iq.busy) {dstream_iq.skipped++;return;}
    int64_t started=esp_timer_get_time();
    bool packed=detpipe_pack(p->copy,p->n);
    dstream_iq.pack_us+=(uint64_t)(esp_timer_get_time()-started);
    if(!packed) {dstream_iq.errors++;return;}
    uint32_t words[12]={UINT32_C(0x31495344),p->generation,
        (uint32_t)p->trigger_device_us,(uint32_t)(p->trigger_device_us>>32),
        p->n,DETPIPE_MAX_PACKED,0,dstream_gain,p->observed_us,
        frequency_mhz,0,0};
    memcpy(dstream_iq.frame,words,48);
    dstream_iq.packed_crc=0;dstream_iq.crc_offset=0;
    dstream_iq.crc_ready=false;dstream_iq.timing_committed=false;
    dstream_iq.generation=p->generation;dstream_iq.offset=0;
    dstream_iq.cursor=0;dstream_iq.metadata=true;dstream_iq.busy=true;
    dstream_iq.produced++;
}
/* At most 2048 bytes per acquisition callback, no allocation/IO/registers.
 * Reads immutable packed pages only; pages were RF-aperture checked at setup. */
static void dstream_iq_crc_step(void) {
    if(!dstream_iq.busy || dstream_iq.crc_ready) return;
    int64_t started=esp_timer_get_time();
    unsigned budget=2048;
    while(budget && dstream_iq.crc_offset<DETPIPE_MAX_PACKED) {
        unsigned page=dstream_iq.crc_offset/DETPIPE_PAGE_BYTES;
        unsigned offset=dstream_iq.crc_offset%DETPIPE_PAGE_BYTES;
        unsigned n=detpipe_page_sizes[page]-offset;
        if(n>budget) n=budget;
        dstream_iq.packed_crc=esp_rom_crc32_le(dstream_iq.packed_crc,detpipe_pages[page]+offset,n);
        dstream_iq.crc_offset+=n;budget-=n;
    }
    if(dstream_iq.crc_offset==DETPIPE_MAX_PACKED) {
        memcpy(dstream_iq.frame+24,&dstream_iq.packed_crc,4);
        dstream_iq_crc();dstream_iq.crc_ready=true;
    }
    dstream_iq.crc_us+=(uint64_t)(esp_timer_get_time()-started);
}
static void dstream_iq_chunk(void) {
    memset(dstream_iq.frame,0,48);
    unsigned left=DETPIPE_MAX_PACKED-dstream_iq.offset;
    unsigned length=left>28?28:left;
    uint32_t header[4]={UINT32_C(0x31515344),dstream_iq.generation,dstream_iq.offset,length};
    memcpy(dstream_iq.frame,header,sizeof(header));
    for(unsigned i=0;i<length;i++) {
        unsigned at=dstream_iq.offset+i;
        dstream_iq.frame[16+i]=detpipe_pages[at/DETPIPE_PAGE_BYTES][at%DETPIPE_PAGE_BYTES];
    }
    dstream_iq_crc();
}
static unsigned dstream_iq_send(unsigned budget) {
    if(!dstream_iq.busy || !dstream_iq.crc_ready || !dstream_iq.timing_committed) return 0;
    unsigned left=48-dstream_iq.cursor;
    unsigned n=burst_serial_try_send(dstream_iq.frame+dstream_iq.cursor,left<budget?left:budget);
    dstream_iq.cursor+=n;
    if(dstream_iq.cursor==48) {
        dstream_iq.cursor=0;
        if(dstream_iq.metadata) dstream_iq.metadata=false;
        else {uint32_t length;memcpy(&length,dstream_iq.frame+12,4);dstream_iq.offset+=length;}
        if(dstream_iq.offset==DETPIPE_MAX_PACKED) {dstream_iq.busy=false;dstream_iq.sent++;}
        else dstream_iq_chunk();
    }
    return n;
}
