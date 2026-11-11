#include "diagnostic.h"
#include "nrf.h"
#include <stdio.h>
static void hex8(char *out,uint32_t v){const char *h="0123456789ABCDEF";for(unsigned i=0;i<8;i++)out[i]=h[(v>>((7-i)*4))&15];out[8]=0;}
void diagnostic_device(char *out,size_t capacity){
 char serial[17],crc[7][9];
 hex8(serial,NRF_FICR->DEVICEID[1]);hex8(serial+8,NRF_FICR->DEVICEID[0]);
 static const uint32_t regions[][2]={{0x00000000,0x1000},{0x00001000,0x22000},{0x000f4000,0x9800},{0x000fd800,0x800},{0x000ff000,0x1000}};
 for(unsigned i=0;i<5;i++)hex8(crc[i],diagnostic_crc32((volatile const uint8_t *)(uintptr_t)regions[i][0],regions[i][1]));
 /* Only documented non-reserved UICR words. No probing of reserved holes. */
 uint32_t named[38];for(unsigned i=0;i<32;i++)named[i]=NRF_UICR->CUSTOMER[i];
 named[32]=NRF_UICR->PSELRESET[0];named[33]=NRF_UICR->PSELRESET[1];named[34]=NRF_UICR->APPROTECT;
 named[35]=NRF_UICR->NFCPINS;named[36]=NRF_UICR->DEBUGCTRL;named[37]=NRF_UICR->REGOUT0;
 hex8(crc[5],diagnostic_crc32((volatile const uint8_t *)named,sizeof named));
 hex8(crc[6],diagnostic_crc32((volatile const uint8_t *)"123456789",9));
 snprintf(out,capacity,"{\"ok\":true,\"command\":\"DEVICE\",\"serial\":\"%s\",\"part\":%lu,\"variant\":%lu,\"package\":%lu,\"ram_kib\":%lu,\"flash_kib\":%lu,\"radio_mode_reg\":%lu,\"radio_frequency_reg\":%lu,\"radio_txpower_reg\":%lu,\"crc32_algorithm\":\"CRC-32/ISO-HDLC\",\"crc32_selftest\":\"%s\",\"mbr_crc32\":\"%s\",\"softdevice_crc32\":\"%s\",\"bootloader_code_crc32\":\"%s\",\"configuration_crc32\":\"%s\",\"settings_crc32\":\"%s\",\"uicr_crc32\":null,\"uicr_full_read_skipped\":\"reserved_addresses_not_read\",\"uicr_named_crc32\":\"%s\",\"uicr_named_word_count\":38}\n",serial,
 (unsigned long)NRF_FICR->INFO.PART,(unsigned long)NRF_FICR->INFO.VARIANT,(unsigned long)NRF_FICR->INFO.PACKAGE,(unsigned long)NRF_FICR->INFO.RAM,(unsigned long)NRF_FICR->INFO.FLASH,
 (unsigned long)NRF_RADIO->MODE,(unsigned long)NRF_RADIO->FREQUENCY,(unsigned long)NRF_RADIO->TXPOWER,
 crc[6],crc[0],crc[1],crc[2],crc[3],crc[4],crc[5]);
}
