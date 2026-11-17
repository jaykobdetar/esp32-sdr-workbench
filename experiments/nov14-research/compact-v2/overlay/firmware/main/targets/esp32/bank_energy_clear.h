#pragma once
#include <stdint.h>
#include <stdbool.h>
/* Fixed half-bank contract. Same 64-sample DC-removed arithmetic and 60-sample
 * unused tail as the exact reference. All 8192 integrity words checked, all
 * 8188 payload words reset. Outputs are unpublished unless return is true. */
static bool bank_energy_clear(uint32_t *w,uint32_t *mean,uint32_t *peak) {
    uint32_t bad=0,total=0,maximum=0;
    for(unsigned b=0;b<127;b++) {
        int32_t si=0,sq=0;uint32_t squares=0;
        for(unsigned j=0;j<64;j++) {
            unsigned at=b*64+j;uint32_t v=w[at];bad|=v==UINT32_C(0xa55aa55a);
            int32_t i=(int32_t)(v<<22)>>22,q=(int32_t)(v<<12)>>22;
            si+=i;sq+=q;squares+=(uint32_t)(i*i+q*q);w[at]=UINT32_C(0xa55aa55a);
        }
        uint32_t e=((squares<<6)-((uint32_t)(si*si)+(uint32_t)(sq*sq)))>>12;
        total+=e;if(e>maximum)maximum=e;
    }
    for(unsigned j=8128;j<8188;j++){bad|=w[j]==UINT32_C(0xa55aa55a);w[j]=UINT32_C(0xa55aa55a);}
    for(unsigned j=8188;j<8192;j++)bad|=w[j]^UINT32_C(0xa55aa55a);
    *mean=total/127;*peak=maximum;return !bad;
}
