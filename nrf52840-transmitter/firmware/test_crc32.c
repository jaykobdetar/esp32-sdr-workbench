#include "diagnostic.h"
#include <assert.h>
#include <stdio.h>
int main(void){assert(diagnostic_crc32((volatile const uint8_t *)"123456789",9)==0xcbf43926);assert(diagnostic_crc32((volatile const uint8_t *)"",0)==0);puts("CRC32 standard vector and empty input passed");}
