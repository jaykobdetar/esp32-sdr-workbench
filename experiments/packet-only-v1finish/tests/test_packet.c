/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "packet.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
static uint32_t words[PKT_MAX_SAMPLES];
static pkt_workspace work;static pkt_result result;
static uint32_t rng=271828u;
static uint32_t random32(void){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
static unsigned make_packet(unsigned offset,uint32_t seq,int polarity,unsigned damage){
 uint8_t bytes[22]={0xef,0xcd,0xab,0x89,0xc3,16,'R','F','T','X'};
 for(unsigned j=0;j<4;j++)bytes[10+j]=(uint8_t)(seq>>(8*j));
 for(unsigned j=8;j<16;j++)bytes[6+j]=(uint8_t)(seq+j);
 if(damage==2)bytes[0]^=1;
 if(damage==3)bytes[14]^=1;
 unsigned bits[200];for(unsigned j=0;j<8;j++)bits[j]=j&1;
 uint16_t crc=0xffff;
 for(unsigned j=0;j<176;j++){
  unsigned b=(bytes[j/8]>>(j%8))&1;bits[8+j]=b;
  unsigned fb=((unsigned)crc>>15)^b;crc=(uint16_t)((uint32_t)crc<<1);if(fb&1)crc^=0x1021;
 }
 for(unsigned j=0;j<16;j++)bits[184+j]=(crc>>(15-j))&1;
 if(damage==1)bits[199]^=1;
 double phase=0;
 for(unsigned j=0;j<1600;j++){
  double f=125000.+polarity*(bits[j/8]?500000.:-500000.);phase+=6.2831853071795864769*f/16000000.;
  int32_t i=(int32_t)lround(400*cos(phase)),q=-(int32_t)lround(400*sin(phase));
  words[offset+j]=((uint32_t)i&1023u)|(((uint32_t)q&1023u)<<10);
 }
 return offset+1600;
}
int main(void){
 unsigned tests=0;
 for(unsigned phase=0;phase<8;phase++)for(int polarity=-1;polarity<=1;polarity+=2){
  memset(words,0,sizeof(words));unsigned n=make_packet(64+phase,123456789u,polarity,0)+64;
  assert(pkt_decode(words,n,&work,&result,64)==0);assert(result.count==1);assert(result.records[0].sequence==123456789u);tests++;
 }
 memset(words,0,sizeof(words));unsigned edge_n=make_packet(64,UINT32_MAX,1,0);
 edge_n=make_packet(edge_n+64,0,-1,0)+32;
 for(unsigned j=0;j<edge_n;j++)words[j]|=0xf0000000u;
 assert(pkt_decode(words,edge_n,&work,&result,64)==0 && result.count==2);
 assert(result.records[0].sequence==UINT32_MAX && result.records[1].sequence==0);tests++;
 for(unsigned damage=1;damage<=3;damage++){
  memset(words,0,sizeof(words));unsigned n=make_packet(64,777,1,damage)+64;
  assert(pkt_decode(words,n,&work,&result,64)==0);assert(!result.count);tests++;
 }
 memset(words,0,sizeof(words));unsigned n=0;
 for(unsigned j=0;j<7;j++)n=make_packet(n+32,100+j,1,0);
 assert(pkt_decode(words,n,&work,&result,64)==0);assert(result.count==7);
 assert(pkt_decode(words,n,&work,&result,2)==0);assert(result.count==2 && result.output_drops>0);tests++;
 assert(pkt_decode(words,n,&work,&result,0)==0);assert(!result.count && result.output_drops>0);tests++;
 words[n-1]=0xa55aa55au;assert(pkt_decode(words,n,&work,&result,64)==PKT_SENTINEL && !result.count);tests++;
 memset(words,0,sizeof(words));make_packet(64,111,1,0);
 assert(pkt_decode(words,1100,&work,&result,64)==0 && !result.count && result.incomplete);tests++;
 assert(pkt_decode(words,0,&work,&result,64)==PKT_ARGUMENT);
 assert(pkt_decode(words,PKT_MAX_SAMPLES+1,&work,&result,64)==PKT_ARGUMENT);
 assert(pkt_decode(words,1000,&work,&result,65)==PKT_ARGUMENT);
 assert(pkt_decode(NULL,1000,&work,&result,64)==PKT_ARGUMENT);
 assert(pkt_decode(words,1000,NULL,&result,64)==PKT_ARGUMENT);
 assert(pkt_decode(words,1000,&work,NULL,64)==PKT_ARGUMENT);tests+=6;
 for(unsigned j=0;j<1000;j++){
  for(unsigned k=0;k<PKT_MAX_SAMPLES;k++)words[k]=random32()&0xfffffu;
  assert(pkt_decode(words,PKT_MAX_SAMPLES,&work,&result,64)==0);assert(!result.count);tests++;
 }
 for(unsigned k=0;k<PKT_MAX_SAMPLES;k++)words[k]=(k&1)?0x7fdffu:0x80200u;
 assert(pkt_decode(words,PKT_MAX_SAMPLES,&work,&result,64)==0 && !result.count);tests++;
 printf("PASS %u cases; workspace=%zu result=%zu record=%zu; no malloc in decoder\n",tests,sizeof(work),sizeof(result),sizeof(pkt_record));
 return 0;
}
