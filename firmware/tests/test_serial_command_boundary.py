"""Exercise raw UART bytes through production serial framing and SPEC parsing."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

root = Path(__file__).resolve().parents[2]
common = root / 'firmware/main/common'
spec = importlib.util.spec_from_file_location(
    'tests_spec', root / 'firmware/tests/test_spectrum_arguments.py'
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize('opt', ['-O0', '-O2'])
def test_serial_rejects_nul_before_command_dispatch(tmp_path, opt):
    work = tmp_path
    headers = dict(m.STUBS)
    headers.update(
        {
            'esp_attr.h': '#define IRAM_ATTR\n',
            'esp_check.h': '#include <assert.h>\n#define ESP_OK 0\n#define ESP_ERROR_CHECK(x) assert((x)==0)\n',
            'sdkconfig.h': '#define CONFIG_ESP_SDR_UART_ENABLED 1\n#define CONFIG_ESP_SDR_UART_TX_PIN 1\n#define CONFIG_ESP_SDR_UART_RX_PIN 3\n',
            'soc/soc_caps.h': '#define SOC_USB_SERIAL_JTAG_SUPPORTED 0\n',
            'freertos/FreeRTOS.h': '#define pdMS_TO_TICKS(x) (x)\n',
            'driver/uart.h': """#include <stddef.h>
    #include <stdint.h>
    #define UART_NUM_0 0
    #define UART_DATA_8_BITS 8
    #define UART_PARITY_DISABLE 0
    #define UART_STOP_BITS_1 1
    #define UART_HW_FLOWCTRL_DISABLE 0
    #define UART_SCLK_DEFAULT 0
    #define UART_PIN_NO_CHANGE -1
    typedef struct {int baud_rate,data_bits,parity,stop_bits,flow_ctrl,source_clk;} uart_config_t;
    int uart_wait_tx_done(int,int);
    int uart_set_baudrate(int,unsigned);
    int uart_flush_input(int);
    int uart_param_config(int,const uart_config_t*);
    int uart_set_pin(int,int,int,int,int);
    int uart_driver_install(int,int,int,int,void*,int);
    int uart_read_bytes(int,void*,size_t,int);
    int uart_tx_chars(int,const char*,size_t);
    """,
        }
    )
    for name, content in headers.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    h = m.HARNESS

    def strip_fn(text, name):
        import re

        match = re.search(r'^[^\n]+\b' + name + r'\([^;]*?\)\s*\{', text, re.M)
        assert match, name
        start = match.start()
        end = match.end()
        depth = 1
        while depth:
            if text[end] == '{':
                depth += 1
            elif text[end] == '}':
                depth -= 1
            end += 1
        return text[:start] + text[end:]

    for name in [
        'burst_serial_port',
        'burst_serial_send',
        'burst_serial_try_send',
        'burst_serial_stop_requested',
        'main',
    ]:
        h = strip_fn(h, name)
    h = h.replace(
        'initialized, acquired, stops, stats_initialized',
        'initialized, acquired, stats_initialized',
    )
    h = h.replace(
        'static unsigned expected_n, expected_rate;',
        'static unsigned expected_n=256, expected_rate=6;',
    )
    h = h.replace('static const char *fault;', 'static const char *fault="acquire";')
    h += """
    #include "driver/uart.h"
    static const unsigned char *rx;
    static size_t rx_length, rx_pos;
    void burst_gpio_init(void) {}
    int uart_wait_tx_done(int a,int b){(void)a;(void)b;return 0;}
    int uart_set_baudrate(int a,unsigned b){(void)a;(void)b;return 0;}
    int uart_flush_input(int a){(void)a;return 0;}
    int uart_param_config(int a,const uart_config_t*b){(void)a;(void)b;return 0;}
    int uart_set_pin(int a,int b,int c,int d,int e){(void)a;(void)b;(void)c;(void)d;(void)e;return 0;}
    int uart_driver_install(int a,int b,int c,int d,void*e,int f){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;return 0;}
    int uart_read_bytes(int port,void *buffer,size_t size,int wait){
        (void)port;(void)wait;
        size_t n=rx_length-rx_pos;if(n>size)n=size;
        memcpy(buffer,rx+rx_pos,n);rx_pos+=n;return (int)n;
    }
    int uart_tx_chars(int port,const char *data,size_t n){
        (void)port;assert(output_size+n<sizeof(output));
        memcpy(output+output_size,data,n);output_size+=n;output[output_size]=0;return (int)n;
    }
    static void check(const char *name,const unsigned char *bytes,size_t length,int expected_status,bool expected_acquire){
        rx=bytes;rx_length=length;rx_pos=0;output_size=0;output[0]=0;acquired=0;initialized=0;
        char line[128];int status=burst_serial_poll_line(line,sizeof(line));
        while(status==0 && rx_pos<rx_length) status=burst_serial_poll_line(line,sizeof(line));
        assert(status==expected_status);
        if(status==1) assert(spectrum_command(line,2412,acquire));
        else assert(initialized==0 && acquired==0);
        printf("%s: acquired=%u, output=%s",name,acquired,output);
        assert((acquired!=0)==expected_acquire);
    }
    int main(void){
        const unsigned char bad[]="SPEC 0 1 1 0 6 256 garbage\\n";
        const unsigned char nul[]="SPEC 0 1 1 0 6 256\\0 garbage\\n";
        const unsigned char nul_stats[]="SPEC 0 1 1 0 6 256 1\\0 0\\n";
        check("ordinary malformed stats",bad,sizeof(bad)-1,1,false);
        check("NUL before malformed stats",nul,sizeof(nul)-1,-1,false);
        check("NUL before excess field",nul_stats,sizeof(nul_stats)-1,-1,false);
        const unsigned char leading[]="\\0SPEC 0 1 1 0 6 256\\n";
        const unsigned char valid[]="SPEC 1 1 1 0 6 256 0\\r\\n";
        check("leading NUL",leading,sizeof(leading)-1,-1,false);
        check("valid command after rejected lines",valid,sizeof(valid)-1,1,true);
        return 0;
    }
    """
    source = work / 'serial_spec.c'
    source.write_text(h)
    binary = work / ('serial_spec' + opt)
    cmd = [
        'cc',
        '-std=gnu11',
        opt,
        '-Wall',
        '-Wextra',
        '-Werror',
        '-fsanitize=undefined',
        '-fno-sanitize-recover=all',
        '-DCONFIG_IDF_TARGET_ESP32=1',
        '-I',
        str(work),
        '-I',
        str(common),
        str(source),
        str(common / 'spectrum.c'),
        str(common / 'burst_serial.c'),
        '-lm',
        '-o',
        str(binary),
    ]
    subprocess.run(cmd, check=True)
    subprocess.run([str(binary)], check=True)
