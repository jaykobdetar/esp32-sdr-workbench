#pragma once
#include <stdint.h>
/* Exact-equivalent full-block alternatives to detector_energy v2.
 * Contract: n<=16380, aligned uint32_t words, I=bits0:9, transmitted -Q=10:19.
 * Higher metadata bits are ignored. All 64 samples of every complete block
 * are analyzed. n%64 tail remains excluded exactly as v2, not subsampled.
 * Sign of Q is immaterial for block energy but decoding remains signed10.
 * Select DETECTOR_ENERGY_CANDIDATE=0..7. Default0 is the v2 reference.
 * Optional DETECTOR_ENERGY_ATTR may be IRAM_ATTR, noinline, always_inline,
 * or a combination supplied by the integration site. No placement implied.
 * Arithmetic bounds/proof are in docs/energy-candidates.md.
 */
#ifndef DETECTOR_ENERGY_CANDIDATE
#define DETECTOR_ENERGY_CANDIDATE 0
#endif
#ifndef DETECTOR_ENERGY_ATTR
#define DETECTOR_ENERGY_ATTR
#endif
#if DETECTOR_ENERGY_CANDIDATE < 0 || DETECTOR_ENERGY_CANDIDATE > 7
#error "Unknown energy candidate (expected0..7)"
#endif

/* Helpers are forced inline to avoid accidental per-sample function calls. */
static inline __attribute__((always_inline)) int32_t energy_signed_xor(uint32_t v) {
    return (int32_t)((v & 1023u) ^ 512u) - 512;
}
static inline __attribute__((always_inline)) int32_t energy_signed_sub(uint32_t v) {
    return (int32_t)(v & 511u) - (int32_t)(v & 512u);
}
static inline __attribute__((always_inline)) void energy_accumulate(uint32_t w, int32_t *si, int32_t *sq, uint32_t *squares) {
    int32_t i, q;
#if DETECTOR_ENERGY_CANDIDATE == 2
    i=energy_signed_sub(w); q=energy_signed_sub(w>>10);
#elif DETECTOR_ENERGY_CANDIDATE == 3
    /* GCC/Xtensa contract: conversion and arithmetic shift of signed32.
     * No signed left shift occurs. Equivalent on pinned GCC and host GCC.
     * Candidate3 is target-specific, not claimed portable ISO C. */
    i=(int32_t)(w<<22)>>22; q=(int32_t)(w<<12)>>22;
#elif DETECTOR_ENERGY_CANDIDATE == 7 && defined(__XTENSA__)
    /* Xtensa LX6 has SEXT. Masking high bits is unnecessary for I's SEXT. */
    __asm__("sext %0, %1, 9" : "=r"(i) : "r"(w));
    uint32_t qbits=w>>10;
    __asm__("sext %0, %1, 9" : "=r"(q) : "r"(qbits));
#else
    i=energy_signed_xor(w); q=energy_signed_xor(w>>10);
#endif
    *si += i; *sq += q; *squares += (uint32_t)(i*i + q*q);
}

static DETECTOR_ENERGY_ATTR void detector_energy(const uint32_t *words, unsigned n, uint32_t *mean, uint32_t *peak) {
    uint32_t total=0, maximum=0;
    unsigned blocks=n/64;
    for (unsigned b=0;b<blocks;b++) {
        int32_t si=0,sq=0;
        uint32_t squares=0;
#if DETECTOR_ENERGY_CANDIDATE == 0
        /* Intentionally unchanged source-level v2 loop for fair comparison. */
        for (unsigned j=0;j<64;j++) {
            uint32_t w=words[b*64+j];
            int32_t i=(int32_t)(w&1023), q=(int32_t)((w>>10)&1023);
            if(i>=512)i-=1024;
            if(q>=512)q-=1024;
            si+=i;sq+=q;squares+=i*i+q*q;
        }
#else
        const uint32_t *p=words+b*64;
#if DETECTOR_ENERGY_CANDIDATE == 4
        const uint32_t *end=p+64;
        do {
            energy_accumulate(p[0],&si,&sq,&squares);
            energy_accumulate(p[1],&si,&sq,&squares);
            energy_accumulate(p[2],&si,&sq,&squares);
            energy_accumulate(p[3],&si,&sq,&squares);
            p+=4;
        } while(p!=end);
#elif DETECTOR_ENERGY_CANDIDATE == 5
        const uint32_t *end=p+64;
        do {
            energy_accumulate(p[0],&si,&sq,&squares);
            energy_accumulate(p[1],&si,&sq,&squares);
            energy_accumulate(p[2],&si,&sq,&squares);
            energy_accumulate(p[3],&si,&sq,&squares);
            energy_accumulate(p[4],&si,&sq,&squares);
            energy_accumulate(p[5],&si,&sq,&squares);
            energy_accumulate(p[6],&si,&sq,&squares);
            energy_accumulate(p[7],&si,&sq,&squares);
            p+=8;
        } while(p!=end);
#elif DETECTOR_ENERGY_CANDIDATE == 6
        int32_t si1=0,sq1=0;uint32_t squares1=0;
        const uint32_t *end=p+64;
        do {
            energy_accumulate(p[0],&si,&sq,&squares);
            energy_accumulate(p[1],&si1,&sq1,&squares1);
            p+=2;
        } while(p!=end);
        si+=si1;sq+=sq1;squares+=squares1;
#else
        const uint32_t *end=p+64;
        do {energy_accumulate(*p++,&si,&sq,&squares);} while(p!=end);
#endif
#endif
        uint32_t mean_square=(uint32_t)(si*si)+(uint32_t)(sq*sq);
        uint32_t energy=((squares<<6)-mean_square)>>12;
        total+=energy;if(energy>maximum)maximum=energy;
    }
    *mean=blocks?total/blocks:0;*peak=maximum;
}
