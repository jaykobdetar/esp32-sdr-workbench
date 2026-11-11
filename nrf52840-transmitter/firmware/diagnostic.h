#ifndef RF_DIAGNOSTIC_H
#define RF_DIAGNOSTIC_H
#include <stddef.h>
#include <stdint.h>
uint32_t diagnostic_crc32(volatile const uint8_t *data,size_t length);
void diagnostic_device(char *out,size_t capacity);
#endif
