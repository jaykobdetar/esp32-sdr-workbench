#pragma once
/* Only exact candidate3, same body/attributes as reviewed runtime dispatcher. */
#define DETECTOR_ENERGY_CANDIDATE 3
#define DETECTOR_ENERGY_ATTR __attribute__((noinline,noclone,noipa))
#define detector_energy pipeline_energy_flash_3
#define energy_signed_xor pipeline_energy_flash_3_signed_xor
#define energy_signed_sub pipeline_energy_flash_3_signed_sub
#define energy_accumulate pipeline_energy_flash_3_accumulate
#include "pipeline_energy_body.inc"
#undef energy_accumulate
#undef energy_signed_sub
#undef energy_signed_xor
#undef detector_energy
#undef DETECTOR_ENERGY_ATTR
#undef DETECTOR_ENERGY_CANDIDATE
