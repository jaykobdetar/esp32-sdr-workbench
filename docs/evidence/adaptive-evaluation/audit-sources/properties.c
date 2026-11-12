#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "firmware/main/targets/esp32/detector_energy.h"
#include "firmware/main/targets/esp32/pipeline_energy3.h"
#include "firmware/main/targets/esp32/detector_background.h"
#include "firmware/main/targets/esp32/detector_retention.h"
#include "firmware/main/targets/esp32/pack20_candidates.h"
static uint32_t rng=0x83219;
static uint32_t next(void){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
static uint32_t words[16380];
static void oracle(unsigned n,uint32_t*m,uint32_t*p){
 uint64_t sum=0;*p=0;
 for(unsigned b=0;b<n/64;b++){
 int64_t si=0,sq=0;uint64_t ss=0;
 for(unsigned j=0;j<64;j++){
 uint32_t w=words[b*64+j];int64_t i=(int)(w&1023),q=(int)((w>>10)&1023);
 if(i>=512)i-=1024;
 if(q>=512)q-=1024;
 si+=i;sq+=q;ss+=(uint64_t)(i*i+q*q);
 }
 uint32_t e=(uint32_t)((ss*64-si*si-sq*sq)/4096);sum+=e;if(e>*p)*p=e;
 }*m=n/64?(uint32_t)(sum/(n/64)):0;
}
int main(void){
 unsigned energies=0,crops=0,packings=0,steps=0,rank_cases=0,rank_mismatches=0;
 for(unsigned n=0;n<=16380;n++){
  for(unsigned j=0;j<n;j++)words[j]=next();
  uint32_t m,p,a,b,c,d;oracle(n,&m,&p);detector_energy(words,n,&a,&b);pipeline_energy_flash_3(words,n,&c,&d);
  assert(m==a&&p==b&&a==c&&b==d);energies++;
  unsigned crop=detector_crop_length(n);unsigned off=detector_crop_offset(words,n,crop);
  assert(crop<=n&&crop<=5120&&!(crop&7)&&off+crop<=n&&!(off&7));
  unsigned expected_block=0;uint32_t mx=0;
  for(unsigned k=0;k<n/64;k++){uint32_t x,y;detector_energy(words+k*64,64,&x,&y);if(y>mx){mx=y;expected_block=k*64;}}
  unsigned expected=expected_block+32>crop/2?expected_block+32-crop/2:0;
  if(expected>n-crop)expected=n-crop;
  expected&=~7u;assert(off==expected);crops++;
  unsigned bytes=(n*20+7)/8, np=(bytes+4095)/4096;uint32_t*pages[10]={0};
  for(unsigned j=0;j<np;j++){unsigned amount=bytes-j*4096;if(amount>4096)amount=4096;pages[j]=malloc(amount);assert(pages[j]);memset(pages[j],0xa5,amount);}
  assert(pack20_words8(words,n,pages));
  for(unsigned j=0;j<n;j++){
   unsigned bit=j*20;uint32_t w=0;
   for(unsigned k=0;k<20;k++){unsigned at=(bit+k)/8;w|=((((uint8_t*)pages[at/4096])[at%4096]>>((bit+k)%8))&1u)<<k;}
   assert(w==(words[j]&0xfffff));
  }
  if(n&1){unsigned at=bytes-1;assert(!(((uint8_t*)pages[at/4096])[at%4096]&0xf0));}
  for(unsigned j=0;j<np;j++)free(pages[j]);
  packings++;
 }
 for(unsigned trial=0;trial<128;trial++){
 detector_background_t s={0};uint64_t q=0,sum=0;
 for(unsigned k=0;k<4096;k++){
 uint32_t m=next()%524289,p=next()%524289;if(p<m)p=m;
 if(trial%4==0)m=p=k<16?0:524288;
 if(trial%4==1)m=p=k<16?524288:0;
 unsigned ratio=1000+next()%999001,score;bool actual=detector_background_step(&s,m,p,ratio,&score),expected=false;
 uint64_t sample=(uint64_t)m*65536;unsigned expected_score=0;
 if(k<16){sum+=sample;q=sum/(k+1);if(!q)q=1;}
 else{if(!q)q=1;__uint128_t scaled=(__uint128_t)p*1000*65536;expected=scaled>(__uint128_t)q*ratio;__uint128_t sr=scaled/q;expected_score=sr>UINT_MAX?UINT_MAX:(unsigned)sr;unsigned divisor=expected?256:64;q=((__uint128_t)q*(divisor-1)+sample+divisor/2)/divisor;if(!q)q=1;}
 assert(actual==expected&&score==expected_score&&q==s.q16);assert(q>=1&&q<=UINT64_C(524288)*65536);steps++;
 }}
 // Exhaustive short score streams: reference order is descending score, earlier generation first.
 for(unsigned encoded=0;encoded<4096;encoded++){
 detector_candidate_t cs[3]={{0}};unsigned scores[6],code=encoded;
 for(unsigned g=0;g<6;g++){
 scores[g]=100+(code%4)*100;code/=4;unsigned slot=detector_candidate_slot(cs,3,scores[g]);
 if(slot<3)cs[slot]=(detector_candidate_t){.samples=256,.generation=g+1,.score_milli=scores[g]};
 }
 unsigned selected=0,expected=0,order[6]={0,1,2,3,4,5};
 for(unsigned a=0;a<6;a++)for(unsigned b=a+1;b<6;b++)if(scores[order[b]]>scores[order[a]]||(scores[order[b]]==scores[order[a]]&&order[b]<order[a])){unsigned t=order[a];order[a]=order[b];order[b]=t;}
 for(unsigned j=0;j<3;j++){selected|=1u<<(cs[j].generation-1);expected|=1u<<order[j];}
 if(selected!=expected)rank_mismatches++;
 rank_cases++;
 }
 printf("PASS energy cases=%u, crop cases=%u, exact CAP20 lengths=%u, Q16 steps=%u\n",energies,crops,packings,steps);
 printf("RESULT earlier-tie policy mismatch streams=%u/%u\n",rank_mismatches,rank_cases);
 detector_candidate_t cs[3]={{.samples=256,.generation=17,.score_milli=100},{.samples=256,.generation=18,.score_milli=100},{.samples=256,.generation=19,.score_milli=100}};
 unsigned slot=detector_candidate_slot(cs,3,200);printf("REPRO generations 17,18,19 scores 100,100,100 then generation20 score200: replaces slot%u generation%u; stable earlier-tie policy requires generation19\n",slot,cs[slot].generation);
 return 0;
}
