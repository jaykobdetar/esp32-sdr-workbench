/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "packet_decimated_dfa.h"
#include <string.h>
#include "prefix_dfa.h"
static uint16_t crc_bit(uint16_t crc,unsigned bit){
 unsigned fb=((unsigned)crc>>15)^bit;
 crc=(uint16_t)((uint32_t)crc<<1);
 if(fb&1u)crc^=0x1021u;
 return crc;
}
static void shift_bit(uint32_t s[3],unsigned bit){
 s[2]=((s[2]<<1)|(s[1]>>31))&0xffffu;
 s[1]=(s[1]<<1)|(s[0]>>31);s[0]=(s[0]<<1)|bit;
}
static int32_t signed10(uint32_t x){return (int32_t)(x&1023u)-(int32_t)((x&512u)<<1);}
/* Explicit floor division avoids implementation-defined right shift of a
 * negative signed operand. All intermediates fit int32_t for10bit IQ. */
static int32_t floor1024(int32_t x){
#if ((-1) >> 1) == -1
 /* On these GCC targets signed right shift is arithmetic, hence exact floor.
  * Keep the defined-portable fallback on implementations with logical shift. */
 return x >> 10;
#else
 return x>=0?x/1024:-(((-x)+1023)/1024);
#endif
}
static void complete(pkt_lane * restrict l,pkt_result * restrict r,unsigned phase,int polarity,unsigned cap){
 uint32_t seq=(uint32_t)l->payload[4]|((uint32_t)l->payload[5]<<8)|((uint32_t)l->payload[6]<<16)|((uint32_t)l->payload[7]<<24);
 for(unsigned k=8;k<16;k++)if(l->payload[k]!=(uint8_t)(seq+k)){r->payload_rejects++;return;}
 if(l->received_crc!=l->crc){r->crc_rejects++;return;}
 r->valid_hypotheses++;
 for(unsigned k=0;k<r->count;k++){
  const pkt_record *p=&r->records[k];uint32_t d=p->address_start_sample>l->start?p->address_start_sample-l->start:l->start-p->address_start_sample;
  if(p->sequence==seq && d<=16){r->duplicates++;return;}
 }
 if(r->count>=cap){r->output_drops++;return;}
 pkt_record *p=&r->records[r->count++];p->sequence=seq;p->address_start_sample=l->start;
 memcpy(p->payload,l->payload,16);p->air_crc=l->crc;p->phase=(uint8_t)phase;p->polarity=(int8_t)polarity;
}
int pkt_decode(const uint32_t * restrict words,size_t n,pkt_workspace * restrict w,pkt_result * restrict r,unsigned cap){
 if(!r)return PKT_ARGUMENT;
 memset(r,0,sizeof(*r));
 if(!w || !words || n<8 || n>PKT_MAX_SAMPLES || cap>PKT_MAX_RESULTS){r->status=PKT_ARGUMENT;return PKT_ARGUMENT;}
 memset(w,0,sizeof(*w));
 int32_t running_sum=0;
 const uint8_t prefix[10]={0xef,0xcd,0xab,0x89,0xc3,16,'R','F','T','X'};
 w->prefix_crc=0xffff;
 for(unsigned j=0;j<10;j++)for(unsigned k=0;k<8;k++){
  unsigned b=(prefix[j]>>k)&1u;shift_bit(w->sync,b);w->prefix_crc=crc_bit(w->prefix_crc,b);
 }
 int32_t pi=signed10(words[0])+signed10(words[1]),pq=-signed10(words[0]>>10)-signed10(words[1]>>10);
 if(words[0]==0xa55aa55au || words[1]==0xa55aa55au){r->status=PKT_SENTINEL;return PKT_SENTINEL;}
 /* Sum each adjacent raw pair with an unnormalized two-tap box filter.
  * Pair components have magnitude<=1024. Cross/dot magnitude<=2097152,
  * 32-value sums<=67108864, and101*dot<=211812352: all int32-safe. All original
  * words are still sentinel-checked. Input offsets remain raw16MS/s indices.
  * Classify32 decimated differences (64 raw sample periods). Side channels
  * have cross-dominant phasor sums; rotate the classified +/-2MHz increment
  * by -/+pi/2, then discriminate the residual125kHz with coefficient101.
  * This is only a known center/+/-2MHz experiment, not general decimation. */
 if((n&1u) && words[n-1]==0xa55aa55au){r->status=PKT_SENTINEL;return PKT_SENTINEL;}
 unsigned decimated=(unsigned)(n/2);
 for(unsigned first=1;first<decimated;first+=32){
  unsigned length=decimated-first;if(length>32)length=32;
  int32_t sc=0,sd=0;
  for(unsigned j=0;j<length;j++){
   unsigned raw_index=2*(first+j);uint32_t word=words[raw_index];
   if(word==0xa55aa55au || words[raw_index+1]==0xa55aa55au){w->sum=running_sum;memset(r,0,sizeof(*r));r->status=PKT_SENTINEL;return PKT_SENTINEL;}
   int32_t i=signed10(word)+signed10(words[raw_index+1]),q=-signed10(word>>10)-signed10(words[raw_index+1]>>10);
   int32_t cross=q*pi-i*pq,dot=i*pi+q*pq;pi=i;pq=q;
   w->cross_block[j]=cross;w->dot_block[j]=dot;sc+=cross;sd+=dot;
  }
  int32_t ac=sc<0?-sc:sc,ad=sd<0?-sd:sd;
  int side=ac>ad?(sc>0?1:-1):0;
  for(unsigned j=0;j<length;j++){
  unsigned n0=first+j;
  int32_t cross=w->cross_block[j],dot=w->dot_block[j];
  int32_t rotated_cross=side>0?-dot:side<0?dot:cross;
  int32_t rotated_dot=side>0?cross:side<0?-cross:dot;
  int32_t d=rotated_cross-floor1024(rotated_dot*101);
  unsigned ring=(n0-1)&3u;running_sum+=d-w->ring[ring];w->ring[ring]=d;
  if(n0<4)continue;
  unsigned phase=n0&3u;
  for(unsigned polarity=0;polarity<2;polarity++){
   unsigned bit=polarity?running_sum<0:running_sum>0;pkt_lane *l=&w->lane[phase*2+polarity];
   unsigned transition=prefix_dfa[2u*l->sync_state+bit];
   l->sync_state=(uint8_t)(transition&127u);
   if(l->active){
    unsigned at=l->collected++;
    if(at<96){l->payload[4+at/8]|=(uint8_t)(bit<<(at%8));l->crc=crc_bit(l->crc,bit);}
    else l->received_crc=(uint16_t)(((uint32_t)l->received_crc<<1)|bit);
    if(l->collected==112){complete(l,r,phase*2,polarity?-1:1,cap);l->active=0;}
   }
   if(n0>=320 && (transition&128u)){
    r->sync_hits++;
    if(l->active){r->busy_syncs++;continue;}
    l->active=1;l->start=2*(n0-320);l->collected=0;l->crc=w->prefix_crc;l->received_crc=0;
    memset(l->payload,0,sizeof(l->payload));memcpy(l->payload,"RFTX",4);
   }
  }
 }
 }
 w->sum=running_sum;
 r->samples_processed=decimated-1;
 r->differential_products=5*(decimated-1);
 r->symbol_decisions=2*(decimated-4);
 for(unsigned j=0;j<8;j++)r->incomplete+=w->lane[j].active!=0;
 return PKT_OK;
}
size_t pkt_workspace_size(void){return sizeof(pkt_workspace);}
size_t pkt_result_size(void){return sizeof(pkt_result);}
