#pragma once
/* GENERATED compile-all entry points for one-build, same-IQ hardware ranking.
 * Include in exactly one translation unit. No peripheral/flash operations.
 * Runtime lookup happens before timing. FLASH names mean default text placement;
 * verify actual ELF mapping. IRAM defaults to .iram1.energy_candidates (IDF).
 * Override ENERGY_RUNTIME_IRAM_ATTR before include to use platform IRAM_ATTR.
 * Macros DETECTOR_ENERGY_* and helper aliases must not be defined by caller.
 */
#include <stdbool.h>
#include <stdint.h>
#ifndef ENERGY_RUNTIME_IRAM_ATTR
#define ENERGY_RUNTIME_IRAM_ATTR __attribute__((section(".iram1.energy_candidates")))
#endif
#define ENERGY_CANDIDATE_COUNT 8

#define DETECTOR_ENERGY_CANDIDATE 0
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_0
#define energy_signed_xor energy_candidate_flash_0_signed_xor
#define energy_signed_sub energy_candidate_flash_0_signed_sub
#define energy_accumulate energy_candidate_flash_0_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 1
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_1
#define energy_signed_xor energy_candidate_flash_1_signed_xor
#define energy_signed_sub energy_candidate_flash_1_signed_sub
#define energy_accumulate energy_candidate_flash_1_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 2
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_2
#define energy_signed_xor energy_candidate_flash_2_signed_xor
#define energy_signed_sub energy_candidate_flash_2_signed_sub
#define energy_accumulate energy_candidate_flash_2_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 3
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_3
#define energy_signed_xor energy_candidate_flash_3_signed_xor
#define energy_signed_sub energy_candidate_flash_3_signed_sub
#define energy_accumulate energy_candidate_flash_3_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 4
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_4
#define energy_signed_xor energy_candidate_flash_4_signed_xor
#define energy_signed_sub energy_candidate_flash_4_signed_sub
#define energy_accumulate energy_candidate_flash_4_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 5
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_5
#define energy_signed_xor energy_candidate_flash_5_signed_xor
#define energy_signed_sub energy_candidate_flash_5_signed_sub
#define energy_accumulate energy_candidate_flash_5_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 6
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_6
#define energy_signed_xor energy_candidate_flash_6_signed_xor
#define energy_signed_sub energy_candidate_flash_6_signed_sub
#define energy_accumulate energy_candidate_flash_6_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 7
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) 
#define detector_energy energy_candidate_flash_7
#define energy_signed_xor energy_candidate_flash_7_signed_xor
#define energy_signed_sub energy_candidate_flash_7_signed_sub
#define energy_accumulate energy_candidate_flash_7_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 0
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_0
#define energy_signed_xor energy_candidate_iram_0_signed_xor
#define energy_signed_sub energy_candidate_iram_0_signed_sub
#define energy_accumulate energy_candidate_iram_0_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 1
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_1
#define energy_signed_xor energy_candidate_iram_1_signed_xor
#define energy_signed_sub energy_candidate_iram_1_signed_sub
#define energy_accumulate energy_candidate_iram_1_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 2
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_2
#define energy_signed_xor energy_candidate_iram_2_signed_xor
#define energy_signed_sub energy_candidate_iram_2_signed_sub
#define energy_accumulate energy_candidate_iram_2_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 3
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_3
#define energy_signed_xor energy_candidate_iram_3_signed_xor
#define energy_signed_sub energy_candidate_iram_3_signed_sub
#define energy_accumulate energy_candidate_iram_3_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 4
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_4
#define energy_signed_xor energy_candidate_iram_4_signed_xor
#define energy_signed_sub energy_candidate_iram_4_signed_sub
#define energy_accumulate energy_candidate_iram_4_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 5
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_5
#define energy_signed_xor energy_candidate_iram_5_signed_xor
#define energy_signed_sub energy_candidate_iram_5_signed_sub
#define energy_accumulate energy_candidate_iram_5_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 6
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_6
#define energy_signed_xor energy_candidate_iram_6_signed_xor
#define energy_signed_sub energy_candidate_iram_6_signed_sub
#define energy_accumulate energy_candidate_iram_6_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

#define DETECTOR_ENERGY_CANDIDATE 7
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa)) ENERGY_RUNTIME_IRAM_ATTR
#define detector_energy energy_candidate_iram_7
#define energy_signed_xor energy_candidate_iram_7_signed_xor
#define energy_signed_sub energy_candidate_iram_7_signed_sub
#define energy_accumulate energy_candidate_iram_7_accumulate
#include "energy_kernel_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE

typedef void (*energy_candidate_fn)(const uint32_t *, unsigned, uint32_t *, uint32_t *);
static const char *const energy_candidate_names[ENERGY_CANDIDATE_COUNT] = {
    "v2-baseline", "xor-sign", "subtract-sign", "gcc-shift-sign",
    "xor-unroll4", "xor-unroll8", "xor-dual-lane", "xtensa-sext"
};
static energy_candidate_fn energy_candidate_select(unsigned index, bool iram) {
    static const energy_candidate_fn flash_functions[ENERGY_CANDIDATE_COUNT] = {
energy_candidate_flash_0, energy_candidate_flash_1, energy_candidate_flash_2, energy_candidate_flash_3, energy_candidate_flash_4, energy_candidate_flash_5, energy_candidate_flash_6, energy_candidate_flash_7};
    static const energy_candidate_fn iram_functions[ENERGY_CANDIDATE_COUNT] = {
energy_candidate_iram_0, energy_candidate_iram_1, energy_candidate_iram_2, energy_candidate_iram_3, energy_candidate_iram_4, energy_candidate_iram_5, energy_candidate_iram_6, energy_candidate_iram_7};
    return index < ENERGY_CANDIDATE_COUNT ? (iram ? iram_functions[index] : flash_functions[index]) : (energy_candidate_fn)0;
}
/* Independent wide-integer reference, for verification outside timed region. */
static void energy_candidate_reference64(const uint32_t *words,unsigned n,uint32_t *mean,uint32_t *peak) {
    uint64_t total=0;uint32_t maximum=0;unsigned blocks=n/64;
    for(unsigned b=0;b<blocks;b++) {
        int64_t si=0,sq=0;uint64_t squares=0;
        for(unsigned j=0;j<64;j++) {
            uint32_t w=words[b*64+j];int64_t i=w&1023u,q=(w>>10)&1023u;
            if(i>=512)i-=1024;
            if(q>=512)q-=1024;
            si+=i;sq+=q;squares+=(uint64_t)(i*i+q*q);
        }
        uint32_t energy=(uint32_t)((squares*64-(uint64_t)(si*si)-(uint64_t)(sq*sq))/4096);
        total+=energy;if(energy>maximum)maximum=energy;
    }
    *mean=blocks?(uint32_t)(total/blocks):0;*peak=maximum;
}
/* Returns a mismatch bitmask: bit0..7=flash, bit8..15=IRAM. Both arrays receive
 * individual results, enabling per-candidate diagnostics without re-running RF.
 * n must satisfy the kernel's contract (<=16380); returns UINT32_MAX otherwise.
 */
typedef struct { uint32_t mean,peak; } energy_candidate_result;
static uint32_t energy_candidates_compare(const uint32_t *words,unsigned n,
        energy_candidate_result *reference,energy_candidate_result flash_results[8],
        energy_candidate_result iram_results[8]) {
    if(n>16380)return UINT32_MAX;
    energy_candidate_reference64(words,n,&reference->mean,&reference->peak);
    uint32_t mismatch=0;
    for(unsigned i=0;i<ENERGY_CANDIDATE_COUNT;i++) {
        energy_candidate_select(i,false)(words,n,&flash_results[i].mean,&flash_results[i].peak);
        energy_candidate_select(i,true)(words,n,&iram_results[i].mean,&iram_results[i].peak);
        if(flash_results[i].mean!=reference->mean||flash_results[i].peak!=reference->peak)mismatch|=1u<<i;
        if(iram_results[i].mean!=reference->mean||iram_results[i].peak!=reference->peak)mismatch|=1u<<(i+8);
    }
    return mismatch;
}
