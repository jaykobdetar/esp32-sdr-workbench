#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define PAUSED_PACKET_EXTRACT 1
#define CONFIG_IDF_TARGET_ESP32 1
#define RXBB_DC_BYTES 16
#define RXRF_DC_BYTES 136
typedef uintptr_t _lock_t;
static uint32_t mutex;
static _lock_t handle;
static bool held,busy,calibrated;
static unsigned tries,releases;
static unsigned char phy_rxbb_dc[16],phy_rxrf_dc[136],calibrated_rxbb_dc[16],calibrated_rxrf_dc[136];
static _lock_t phy_get_lock(void){return handle;}
static int _lock_try_acquire(_lock_t*l){assert(*l==handle);tries++;if(busy)return -1;assert(!held);held=true;return 0;}
static void _lock_release(_lock_t*l){assert(*l==handle&&held);held=false;releases++;}
static bool esp_ptr_in_dram(const void*p){return p!=NULL;}
#include "lease-under-test.inc"
int main(void){
 paused_calibration s={0};handle=(uintptr_t)&mutex;calibrated=true;
 assert(!paused_calibration_begin(NULL));assert(!paused_calibration_end(NULL));
 handle=0;assert(!paused_calibration_begin(&s));assert(tries==0);handle=(uintptr_t)&mutex;
 busy=true;assert(!paused_calibration_begin(&s));assert(!held&&tries==1&&releases==0);busy=false;
 calibrated=false;assert(!paused_calibration_begin(&s));assert(!held&&releases==1);calibrated=true;
 phy_rxbb_dc[2]=1;assert(!paused_calibration_begin(&s));assert(!held&&releases==2);phy_rxbb_dc[2]=0;
 assert(paused_calibration_begin(&s));assert(held);assert(!paused_calibration_begin(&s));assert(paused_calibration_end(&s));assert(!held&&!s.handle);assert(!paused_calibration_end(&s));
 assert(paused_calibration_begin(&s));phy_rxrf_dc[135]=1;assert(!paused_calibration_end(&s));assert(!held&&!s.handle&&s.after[151]==1);
 return 0;
}
