#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include <string.h>
#include "firmware/main/targets/esp32/detector_energy.h"
#include "firmware/main/targets/esp32/detector_retention.h"
static uint32_t words[16380];
int main(void){
 (void)detector_candidate_slot;
 const unsigned n=16380,frame=4672;
 for(unsigned mode=0;mode<4;mode++){
 unsigned total=0,contained=0;
 for(unsigned start=0;start+frame<=n;start+=8){
 memset(words,0,sizeof(words));
 for(unsigned j=start;j<start+frame;j++){unsigned amp=100;
 if(mode){unsigned peak=start+(mode==1?0:mode==2?frame/2:frame-64);peak=peak/64*64;if(j>=peak&&j<peak+64)amp=500;}
 int val=(j&1)?(int)amp:-(int)amp;words[j]=((unsigned)val&1023)|(((unsigned)val&1023)<<10);
 }
 unsigned crop=detector_crop_length(n),off=detector_crop_offset(words,n,crop);
 assert(off+crop<=n);total++;contained+=off<=start&&off+crop>=start+frame;
 }
 printf("synthetic frame length 4672 (292us at 16MS/s), mode=%s, fully contained %u/%u (%.3f%%)\n",mode==0?"uniform alternating energy":mode==1?"high-energy first block":mode==2?"high-energy center block":"high-energy last block",contained,total,100.0*contained/total);
 }
 puts("Synthetic crop-policy sensitivity only; no RF packet recall, SNR, gain, or hardware claim.");return 0;
}
