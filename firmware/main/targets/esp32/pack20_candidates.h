#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#if !defined(__BYTE_ORDER__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "pack20_words8 requires a little-endian target"
#endif
#define PACK20_MAX_SAMPLES 16380u
#define PACK20_PAGE_BYTES 4096u
#ifndef PACK20_ATTR
#define PACK20_ATTR __attribute__((noinline,noclone,noipa))
#endif
/* Contract: src has n immutable uint32_t words, CPU-owned and disjoint from all
 * destinations. Each page starts at a 4-byte-aligned allocation; full pages have
 * 4096 writable bytes and last has >=ceil(n*20/8)%4096 (4096 if remainder zero).
 * Pages are disjoint malloc-like storage permitting uint32_t stores, and remain
 * exclusively owned. Caller supplies ceil(ceil(n*20/8)/4096) pointers.
 * Checks below are argument checks, NOT allocation/range/ownership verification.
 * Source upper12 metadata bits discarded. Exact CAP20 little-endian output.
 * Every full-group store is 4-byte aligned and never straddles a page boundary.
 */
static inline void pack20_store(uint32_t *const pages[],unsigned word,uint32_t value){
 pages[word>>10][word&1023u]=value;
}
static inline void pack20_byte(uint32_t *const pages[],unsigned at,uint8_t value){
 ((uint8_t*)pages[at>>12])[at&4095u]=value;
}
static PACK20_ATTR bool pack20_words8(const uint32_t *src,unsigned n,uint32_t *const pages[]){
 if(n>PACK20_MAX_SAMPLES)return false;
 if(!n)return true;
 if(!src||!pages||((uintptr_t)src&3u))return false;
 unsigned bytes=(n*20u+7u)/8u,count=(bytes+4095u)/4096u;
 for(unsigned p=0;p<count;p++)if(!pages[p]||((uintptr_t)pages[p]&3u))return false;
 unsigned j=0,out=0;
 for(;j+8<=n;j+=8,out+=5){
  uint32_t a=src[j]&0xfffffu,b=src[j+1]&0xfffffu,c=src[j+2]&0xfffffu,d=src[j+3]&0xfffffu;
  uint32_t e=src[j+4]&0xfffffu,f=src[j+5]&0xfffffu,g=src[j+6]&0xfffffu,h=src[j+7]&0xfffffu;
  pack20_store(pages,out,a|(b<<20));
  pack20_store(pages,out+1,(b>>12)|(c<<8)|(d<<28));
  pack20_store(pages,out+2,(d>>4)|(e<<16));
  pack20_store(pages,out+3,(e>>16)|(f<<4)|(g<<24));
  pack20_store(pages,out+4,(g>>8)|(h<<12));
 }
 /* At most7 samples. Before insertion bits<=7, so at most27 live bits;
  * all shifts unsigned and <32. Final partial byte has zero high padding. */
 unsigned at=out*4,bits=0;uint32_t pending=0;
 for(;j<n;j++){
  pending|=(src[j]&0xfffffu)<<bits;bits+=20;
  while(bits>=8){pack20_byte(pages,at++,(uint8_t)pending);pending>>=8;bits-=8;}
 }
 if(bits)pack20_byte(pages,at,(uint8_t)pending);
 return true;
}
