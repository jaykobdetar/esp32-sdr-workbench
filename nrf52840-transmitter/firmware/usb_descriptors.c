#include "tusb.h"
#include "nrf.h"
tusb_desc_device_t const dev = { .bLength=sizeof(tusb_desc_device_t), .bDescriptorType=TUSB_DESC_DEVICE, .bcdUSB=0x0200, .bDeviceClass=TUSB_CLASS_MISC, .bDeviceSubClass=MISC_SUBCLASS_COMMON, .bDeviceProtocol=MISC_PROTOCOL_IAD, .bMaxPacketSize0=64, .idVendor=0x2886, .idProduct=0xf010, .bcdDevice=0x0100, .iManufacturer=1, .iProduct=2, .iSerialNumber=3, .bNumConfigurations=1 };
uint8_t const *tud_descriptor_device_cb(void) {return (const uint8_t*)&dev;}
static const uint8_t cfg[]={TUD_CONFIG_DESCRIPTOR(2,0,TUD_CONFIG_DESC_LEN+TUD_CDC_DESC_LEN,0,100),TUD_CDC_DESCRIPTOR(0,4,0x81,8,0x02,0x82,64)};
uint8_t const *tud_descriptor_configuration_cb(uint8_t i){(void)i;return cfg;}
uint16_t const *tud_descriptor_string_cb(uint8_t i){
 static uint16_t out[40]; static char serial[17]; const char *s;
 const char *hex="0123456789ABCDEF";
 for(int j=0;j<16;j++) serial[j]=hex[(NRF_FICR->DEVICEID[1-j/8] >> ((7-j%8)*4))&15];
 if(i==0){out[0]=0x0304;out[1]=0x0409;return out;}
 switch(i){case 1:s="Experimental RF Lab";break;case 2:s="nRF52840 RF Test TX";break;case 3:s=serial;break;case 4:s="RF commands";break;default:return NULL;}
 unsigned n=0;while(s[n]&&n<39){out[n+1]=s[n];n++;}out[0]=0x0300|(2*n+2);return out;
}
