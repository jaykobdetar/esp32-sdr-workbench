#pragma once
#include <stdint.h>
#include <limits.h>
#include <string.h>
#define VC_CAPACITY 16384u
#define VC_MAX_SAMPLES 16380u
#define VC_SENTINEL UINT32_C(0xa55aa55a)
#define VC_INVALID_ARGUMENT (UINT_MAX-1u)
#define VC_CANDIDATE_COUNT 4u
#ifndef VC_FUNCTION_ATTR
#define VC_FUNCTION_ATTR __attribute__((noinline,noclone,noipa))
#endif
/* All src[0..16383] must be stable and CPU-owned. dst[0..n-1] must be writable,
 * uint32-aligned, disjoint from the entire source aperture, and exclusively owned.
 * Caller verifies pointer/range/ownership contracts before entering timed calls.
 * n in 0..16380 supported. n>16380 returns VC_INVALID_ARGUMENT without access.
 * UINT_MAX means valid and exact copy complete. Otherwise earliest invalid index.
 * On failure dst may be unchanged, partial, or fully written; NEVER publish it.
 * Every guard word is checked; only requested n words are copied, including tails
 * and upper metadata bits. Source is never modified. */
static inline unsigned vc_first_bad(const uint32_t *src,unsigned n){
    for(unsigned j=0;j<n;j++)if(src[j]==VC_SENTINEL)return j;
    for(unsigned j=n;j<VC_CAPACITY;j++)if(src[j]!=VC_SENTINEL)return j;
    return UINT_MAX;
}
static inline unsigned vc_validate_unroll4(const uint32_t *src,unsigned n){
    uint32_t bad=0;unsigned j=0;
    for(;j+4<=n;j+=4){bad|=(src[j]==VC_SENTINEL);bad|=(src[j+1]==VC_SENTINEL);bad|=(src[j+2]==VC_SENTINEL);bad|=(src[j+3]==VC_SENTINEL);}
    for(;j<n;j++)bad|=(src[j]==VC_SENTINEL);
    for(;j+4<=VC_CAPACITY;j+=4){bad|=src[j]^VC_SENTINEL;bad|=src[j+1]^VC_SENTINEL;bad|=src[j+2]^VC_SENTINEL;bad|=src[j+3]^VC_SENTINEL;}
    for(;j<VC_CAPACITY;j++)bad|=src[j]^VC_SENTINEL;
    return bad?vc_first_bad(src,n):UINT_MAX;
}
static VC_FUNCTION_ATTR unsigned vc_separate(const uint32_t *src,uint32_t *dst,unsigned n){
    if(n>VC_MAX_SAMPLES)return VC_INVALID_ARGUMENT;
    unsigned bad=vc_validate_unroll4(src,n);
    if(bad==UINT_MAX)memcpy(dst,src,n*sizeof(uint32_t));
    return bad;
}
static VC_FUNCTION_ATTR unsigned vc_fused_scalar(const uint32_t *src,uint32_t *dst,unsigned n){
    if(n>VC_MAX_SAMPLES)return VC_INVALID_ARGUMENT;
    uint32_t bad=0;
    for(unsigned j=0;j<n;j++){uint32_t w=src[j];bad|=(w==VC_SENTINEL);dst[j]=w;}
    for(unsigned j=n;j<VC_CAPACITY;j++)bad|=src[j]^VC_SENTINEL;
    return bad?vc_first_bad(src,n):UINT_MAX;
}
static VC_FUNCTION_ATTR unsigned vc_fused_unroll4(const uint32_t *src,uint32_t *dst,unsigned n){
    if(n>VC_MAX_SAMPLES)return VC_INVALID_ARGUMENT;
    uint32_t bad=0;unsigned j=0;
    for(;j+4<=n;j+=4){
        uint32_t a=src[j],b=src[j+1],c=src[j+2],d=src[j+3];
        bad|=(a==VC_SENTINEL);bad|=(b==VC_SENTINEL);bad|=(c==VC_SENTINEL);bad|=(d==VC_SENTINEL);
        dst[j]=a;dst[j+1]=b;dst[j+2]=c;dst[j+3]=d;
    }
    for(;j<n;j++){uint32_t w=src[j];bad|=(w==VC_SENTINEL);dst[j]=w;}
    for(;j+4<=VC_CAPACITY;j+=4){bad|=src[j]^VC_SENTINEL;bad|=src[j+1]^VC_SENTINEL;bad|=src[j+2]^VC_SENTINEL;bad|=src[j+3]^VC_SENTINEL;}
    for(;j<VC_CAPACITY;j++)bad|=src[j]^VC_SENTINEL;
    return bad?vc_first_bad(src,n):UINT_MAX;
}
static VC_FUNCTION_ATTR unsigned vc_fused_unroll8(const uint32_t *src,uint32_t *dst,unsigned n){
    if(n>VC_MAX_SAMPLES)return VC_INVALID_ARGUMENT;
    uint32_t bad=0;unsigned j=0;
    for(;j+8<=n;j+=8){
        uint32_t a=src[j],b=src[j+1],c=src[j+2],d=src[j+3];
        uint32_t e=src[j+4],f=src[j+5],g=src[j+6],h=src[j+7];
        bad|=(a==VC_SENTINEL);bad|=(b==VC_SENTINEL);bad|=(c==VC_SENTINEL);bad|=(d==VC_SENTINEL);
        bad|=(e==VC_SENTINEL);bad|=(f==VC_SENTINEL);bad|=(g==VC_SENTINEL);bad|=(h==VC_SENTINEL);
        dst[j]=a;dst[j+1]=b;dst[j+2]=c;dst[j+3]=d;
        dst[j+4]=e;dst[j+5]=f;dst[j+6]=g;dst[j+7]=h;
    }
    for(;j<n;j++){uint32_t w=src[j];bad|=(w==VC_SENTINEL);dst[j]=w;}
    for(;j+8<=VC_CAPACITY;j+=8){
        bad|=src[j]^VC_SENTINEL;bad|=src[j+1]^VC_SENTINEL;bad|=src[j+2]^VC_SENTINEL;bad|=src[j+3]^VC_SENTINEL;
        bad|=src[j+4]^VC_SENTINEL;bad|=src[j+5]^VC_SENTINEL;bad|=src[j+6]^VC_SENTINEL;bad|=src[j+7]^VC_SENTINEL;
    }
    for(;j<VC_CAPACITY;j++)bad|=src[j]^VC_SENTINEL;
    return bad?vc_first_bad(src,n):UINT_MAX;
}
typedef unsigned (*vc_candidate_fn)(const uint32_t *,uint32_t *,unsigned);
static const char *const vc_candidate_names[VC_CANDIDATE_COUNT]={"validate4-memcpy","fused-scalar","fused-unroll4","fused-unroll8"};
static vc_candidate_fn vc_candidate_select(unsigned id){
    static const vc_candidate_fn functions[VC_CANDIDATE_COUNT]={vc_separate,vc_fused_scalar,vc_fused_unroll4,vc_fused_unroll8};
    return id<VC_CANDIDATE_COUNT?functions[id]:(vc_candidate_fn)0;
}
