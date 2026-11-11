#pragma once
#include <stdint.h>
#include <limits.h>
#define VALIDATE_CAPACITY 16384u
#define VALIDATE_SENTINEL 0xa55aa55au
/* All candidates enforce the SAME original full-aperture guard predicate.
 * Caller must have restored CPU ownership and stopped the dump writer.
 * A returned UINT_MAX means valid; otherwise first failing word index. */
static unsigned validate_original(const uint32_t *words,unsigned n) {
 for(unsigned j=0;j<VALIDATE_CAPACITY;j++)
  if((j<n && words[j]==VALIDATE_SENTINEL)||(j>=n && words[j]!=VALIDATE_SENTINEL))return j;
 return UINT_MAX;
}
static unsigned validate_split(const uint32_t *words,unsigned n) {
 for(unsigned j=0;j<n;j++)if(words[j]==VALIDATE_SENTINEL)return j;
 for(unsigned j=n;j<VALIDATE_CAPACITY;j++)if(words[j]!=VALIDATE_SENTINEL)return j;
 return UINT_MAX;
}
static unsigned validate_aggregate(const uint32_t *words,unsigned n) {
 uint32_t bad=0;
 for(unsigned j=0;j<n;j++)bad|=(words[j]==VALIDATE_SENTINEL);
 for(unsigned j=n;j<VALIDATE_CAPACITY;j++)bad|=words[j]^VALIDATE_SENTINEL;
 return bad?validate_split(words,n):UINT_MAX;
}
static unsigned validate_unroll4(const uint32_t *words,unsigned n) {
 uint32_t bad=0;unsigned j=0;
 for(;j+4<=n;j+=4){bad|=(words[j]==VALIDATE_SENTINEL);bad|=(words[j+1]==VALIDATE_SENTINEL);bad|=(words[j+2]==VALIDATE_SENTINEL);bad|=(words[j+3]==VALIDATE_SENTINEL);}
 for(;j<n;j++)bad|=(words[j]==VALIDATE_SENTINEL);
 for(;j+4<=VALIDATE_CAPACITY;j+=4){bad|=words[j]^VALIDATE_SENTINEL;bad|=words[j+1]^VALIDATE_SENTINEL;bad|=words[j+2]^VALIDATE_SENTINEL;bad|=words[j+3]^VALIDATE_SENTINEL;}
 for(;j<VALIDATE_CAPACITY;j++)bad|=words[j]^VALIDATE_SENTINEL;
 return bad?validate_split(words,n):UINT_MAX;
}
static void clear_original(uint32_t *words) {for(unsigned j=0;j<VALIDATE_CAPACITY;j++)words[j]=VALIDATE_SENTINEL;}
static void clear_unroll8(uint32_t *words) {
 for(unsigned j=0;j<VALIDATE_CAPACITY;j+=8){words[j]=VALIDATE_SENTINEL;words[j+1]=VALIDATE_SENTINEL;words[j+2]=VALIDATE_SENTINEL;words[j+3]=VALIDATE_SENTINEL;words[j+4]=VALIDATE_SENTINEL;words[j+5]=VALIDATE_SENTINEL;words[j+6]=VALIDATE_SENTINEL;words[j+7]=VALIDATE_SENTINEL;}
}
