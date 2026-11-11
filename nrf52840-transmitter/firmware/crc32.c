#include "diagnostic.h"
/* CRC-32/ISO-HDLC: reflected poly 0xedb88320, initial/final xor 0xffffffff. */
uint32_t diagnostic_crc32(volatile const uint8_t *data,size_t length){
 uint32_t crc=0xffffffff;
 for(size_t i=0;i<length;i++){
  crc^=data[i];
  for(unsigned bit=0;bit<8;bit++)crc=(crc>>1)^((0u-(crc&1u))&0xedb88320u);
 }
 return crc^0xffffffff;
}
