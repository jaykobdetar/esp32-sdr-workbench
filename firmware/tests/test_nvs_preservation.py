"""Fault injection executes production startup without devices or persistent writes."""

import subprocess
from pathlib import Path

import pytest

RECEIVER = Path(__file__).parents[1] / 'main/targets/esp32/receiver.c'


@pytest.mark.parametrize('optimization', ['-O0', '-O2'])
def test_nvs_init_failures_preserve_storage_and_do_not_start_radio(tmp_path, optimization):
    startup = 'void app_main(void) {' + RECEIVER.read_text().split('void app_main(void) {', 1)[1]
    mocks = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
typedef int esp_err_t;
typedef int wifi_init_config_t;
#define ESP_OK 0
#define ESP_LOG_NONE 0
#define ESP_ERR_NVS_NO_FREE_PAGES 4353
#define ESP_ERR_NVS_NEW_VERSION_FOUND 4368
#define WIFI_STORAGE_RAM 0
#define WIFI_MODE_NULL 0
#define WIFI_PS_NONE 0
#define WIFI_SECOND_CHAN_NONE 0
#define WIFI_INIT_CONFIG_DEFAULT() 0
#define RX_GAIN 0
#define BIT(n) (1u<<(n))
static unsigned gain_max, init_calls, erase_calls, radio_calls, serial_calls, idle_delays;
static int init_result, fatal_error;
/* The failure path must idle forever. Let it repeat its notice three times, then
 * leave the otherwise endless loop so the test can inspect what happened. */
#define pdMS_TO_TICKS(ms) (ms)
static jmp_buf halted;
static void vTaskDelay(unsigned ticks){assert(ticks==5000);if(++idle_delays==3)longjmp(halted,2);}
static unsigned char storage[32];
static void esp_log_level_set(const char*a,int b){(void)a;(void)b;}
static int nvs_flash_init(void){init_calls++;return init_result;}
/* An erase would irreversibly destroy this mock calibration/settings image. */
int nvs_flash_erase(void){erase_calls++;memset(storage,0xff,sizeof(storage));return 0;}
#define ESP_ERROR_CHECK(call) do {int error=(call);if(error){fatal_error=error;longjmp(halted,1);}} while(0)
static int esp_event_loop_create_default(void){radio_calls++;return 0;}
static int esp_wifi_init(wifi_init_config_t*cfg){(void)cfg;radio_calls++;return 0;}
static int esp_wifi_set_storage(int x){(void)x;radio_calls++;return 0;}
static int esp_wifi_set_mode(int x){(void)x;radio_calls++;return 0;}
static int esp_wifi_start(void){radio_calls++;return 0;}
static int esp_wifi_set_ps(int x){(void)x;radio_calls++;return 0;}
static int esp_wifi_set_promiscuous(bool x){(void)x;radio_calls++;return 0;}
static int esp_wifi_set_channel(int x,int y){(void)x;(void)y;radio_calls++;return 0;}
static void prepare_rx(void){radio_calls++;}
#define REG_READ(addr) ((void)(addr),79u<<8)
#define REG_CLR_BIT(addr,bit) do{(void)(addr);(void)(bit);radio_calls++;}while(0)
static void burst_serial_init(void){serial_calls++;}
static void command(char*line){(void)line;}
static void burst_serial_serve(void(*handler)(char*)){assert(handler==command);serial_calls++;}
"""
    checks = r"""
int main(void){
 const int failures[]={ESP_ERR_NVS_NO_FREE_PAGES,ESP_ERR_NVS_NEW_VERSION_FOUND,123};
 unsigned char expected[32];memset(expected,0x42,sizeof(expected));
 for(volatile unsigned i=0;i<sizeof(failures)/sizeof(failures[0]);i++){
  memcpy(storage,expected,sizeof(storage));init_calls=erase_calls=radio_calls=serial_calls=0;
  init_result=failures[i];fatal_error=0;idle_delays=0;
  if(!setjmp(halted)){app_main();assert(!"Startup must fail closed");}
  /* It idles and repeats the notice; it never aborts, which would reboot in a loop. */
  assert(idle_delays==3 && fatal_error==0 && init_calls==1 && erase_calls==0);
  assert(radio_calls==0 && serial_calls==0 && !memcmp(storage,expected,sizeof(storage)));
 }
 init_result=0;init_calls=erase_calls=radio_calls=serial_calls=0;
 if(!setjmp(halted)){app_main();}else{assert(!"Normal boot must not abort");}
 assert(init_calls==1 && erase_calls==0 && radio_calls>0 && serial_calls==2);
 assert(!memcmp(storage,expected,sizeof(storage)));
}
"""
    source = tmp_path / 'startup.c'
    source.write_text(mocks + startup + checks)
    subprocess.run(
        [
            'cc',
            '-std=c11',
            optimization,
            '-Wall',
            '-Wextra',
            '-Werror',
            '-fsanitize=undefined',
            '-fno-sanitize-recover=all',
            str(source),
            '-o',
            str(tmp_path / 'test'),
        ],
        check=True,
    )
    result = subprocess.run([str(tmp_path / 'test')], check=True, capture_output=True, text=True)
    # Three injected failures, each repeating the notice three times before the mock stops it.
    notices = [line for line in result.stdout.splitlines() if line.startswith('ERR nvs_init ')]
    assert len(notices) == 9 and all('storage_preserved' in line for line in notices)
