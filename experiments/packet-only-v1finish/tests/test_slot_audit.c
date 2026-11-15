#include "slot_audit.h"
#include <assert.h>
int main(void) {
 pkt_slot_audit s;uint32_t i;uint64_t t;
 assert(!pkt_slot_init(&s,UINT64_MAX-1,10000000,128));
 assert(!pkt_slot_init(&s,0,1875000,3));
 assert(!pkt_slot_init(&s,0,10000000,129));
 assert(pkt_slot_init(&s,1000000,10000000,4));
 assert(pkt_slot_poll(&s,0,&i,&t)==PKTSLOT_WAIT && t==1000000);
 assert(pkt_slot_poll(&s,1000000,&i,&t)==PKTSLOT_READY && i==0);
 assert(!pkt_slot_close(&s));
 assert(pkt_slot_poll(&s,1000001,&i,&t)==PKTSLOT_INVALID);
 assert(pkt_slot_complete(&s,true,1000000));
 assert(pkt_slot_poll(&s,21500000,&i,&t)==PKTSLOT_WAIT && s.skipped==2);
 assert(pkt_slot_poll(&s,31000000,&i,&t)==PKTSLOT_READY && i==3);
 assert(pkt_slot_complete(&s,true,31000100));
 assert(s.max_gap_ns==28976350 && s.gap_ns==28976350);
 assert(pkt_slot_poll(&s,50000000,&i,&t)==PKTSLOT_DONE);
 assert(pkt_slot_close(&s) && s.completed==2 && s.skipped==2);
 assert(pkt_slot_init(&s,0,10000000,4));
 assert(pkt_slot_poll(&s,0,&i,&t)==PKTSLOT_READY);
 assert(pkt_slot_complete(&s,false,0));
 assert(pkt_slot_close(&s) && s.capture_faults==1 && s.cancelled==3);
 return 0;
}
