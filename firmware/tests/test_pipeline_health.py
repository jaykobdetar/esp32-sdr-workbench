"""Opt-in telemetry using the live integrated pipeline under UBSan, no hardware."""

import importlib.util
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'pipeline_state', HERE / 'test_adaptive_pipeline_state.py'
)
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


def test_pipeline_health():
    source = state.SOURCE
    source = source.replace(
        '#define MAX_SAMPLES',
        """
#define DETPIPE_HEALTH 1
#define ESP_OK 0
#define ESP_ERR_NO_MEM 257
#define MALLOC_CAP_DEFAULT 8
static unsigned monitor_starts, monitor_stops;
static int start_error, stop_error;
static bool monitoring, short_default_heap, send_fail;
static size_t local_min, lifetime_min=1000, stack_min=6000;
static int heap_caps_monitor_local_minimum_free_size_start(void){
 assert(!monitoring);monitor_starts++;
 if(start_error)return start_error;
 monitoring=true;local_min=200000;return 0;
}
static int heap_caps_monitor_local_minimum_free_size_stop(void){
 assert(monitoring);monitor_stops++;monitoring=false;return stop_error;
}
static size_t heap_caps_get_minimum_free_size(int caps){(void)caps;return monitoring?local_min:lifetime_min;}
static size_t uxTaskGetStackHighWaterMark(void*task){assert(!task);return stack_min;}
#define MAX_SAMPLES""",
        1,
    )
    source = source.replace(
        'vsnprintf(output+strlen(output),sizeof(output)-strlen(output),fmt,ap);',
        'char chunk[256];int length=vsnprintf(chunk,sizeof(chunk),fmt,ap);assert(length>=0 && (size_t)length<sizeof(chunk));strcat(output,chunk);',
    )
    source = source.replace('return 250000;', 'return 250000-active_allocations*4096;')
    source = source.replace(
        'return 72000;', 'return caps==MALLOC_CAP_DEFAULT && short_default_heap?0:72000;'
    )
    source = source.replace(
        '(void)source;(void)clock;calls++;',
        """
 /* A trough between all boundary samples. Check stack units are not multiplied. */
 if(monitoring){local_min=12345;stack_min=2345;}
 (void)source;(void)clock;calls++;""",
    )
    source = source.replace(
        'return true;}\n#include "ENERGY_HEADER"', 'return !send_fail;}\n#include "ENERGY_HEADER"'
    )
    source = source.replace(
        ' if(det_retained){',
        ' assert(!monitoring);assert(monitor_starts==monitor_stops);\n if(det_retained){',
        1,
    )
    source = source.replace(
        'int main(void){',
        """int main(void){
 assert(detector_pipeline_command("DETPIPEHEALTH?"));
 assert(strstr(output,"\\\"run_valid\\\":false"));
 assert(strstr(output,"\\\"run_min_bytes\\\":null"));
 assert(strstr(output,"\\\"free_before_bytes\\\":null"));
 reset(0,0);
 assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 1"));
 assert(!monitoring && detpipe_health.valid && detpipe_health.run_id==1);
 assert(detpipe_health.local_min==12345 && detpipe_health.lifetime_before==1000);
 assert(detpipe_health.before==250000 && detpipe_health.allocated==241808);
 assert(detpipe_health.drained==241808 && detpipe_health.after==245904);
 assert(detpipe_health.stack_before==6000 && detpipe_health.stack_after==2345);
 assert(detpipe_health.lifetime_after==1000);
 output[0]=0;assert(detector_pipeline_command("DETPIPEHEALTH?"));
 assert(strstr(output,"\\\"run_valid\\\":true"));
 assert(strstr(output,"\\\"run_min_bytes\\\":12345"));
 assert(strstr(output,"\\\"stack_after_bytes\\\":2345"));
 unsigned id=detpipe_health.run_id;
 assert(detector_pipeline_command("DETPIPE1 invalid"));assert(detpipe_health.run_id==id);
 assert(detector_pipeline_command("DETPIPECLEAR"));
 assert(detpipe_health.run_id==id && detpipe_health.after==245904);
 assert(heap_caps_get_free_size(DETPIPE_ALLOC_CAPS)==250000);
 reset(0,1);assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 1"));
 assert(!detpipe_health.valid && !monitoring && detpipe_health.allocated==SIZE_MAX);
 reset(0,0);send_fail=true;
 assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 1"));
 assert(!detpipe_health.valid && !monitoring);send_fail=false;
 reset(0,0);short_default_heap=true;unsigned starts=monitor_starts;
 assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 0"));
 assert(!detpipe_health.valid && !monitoring && monitor_starts==starts);
 assert(detpipe_health.start_error==ESP_ERR_NO_MEM && detpipe_health.local_min==SIZE_MAX);
 short_default_heap=false;
 reset(0,0);start_error=42;
 assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 0"));
 assert(!detpipe_health.valid && !monitoring && detpipe_health.start_error==42);
 monitor_starts--;start_error=0; /* Failed mock start owns nothing to stop. */
 reset(0,0);stop_error=43;
 assert(detector_pipeline_command("DETPIPE1 20 256 6 4000 0"));
 assert(!detpipe_health.valid && !monitoring && detpipe_health.stop_error==43);
 stop_error=0;
""",
        1,
    )
    source = (
        source.replace('ENERGY_HEADER', str(state.ROOT / 'main/targets/esp32/detector_energy.h'))
        .replace('PIPE_HEADER', str(state.ROOT / 'main/targets/esp32/detector_pipeline.h'))
        .replace('BACKGROUND_HEADER', str(state.ROOT / 'main/targets/esp32/detector_background.h'))
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / 'esp_memory_utils.h').write_text(
            'static bool esp_ptr_internal(const void*p){return p!=NULL;}\n'
            'static bool esp_ptr_in_dram(const void*p){return p!=NULL&&!((uintptr_t)p>=reject_lo&&(uintptr_t)p<=reject_hi);}\n'
            'static bool esp_ptr_byte_accessible(const void*p){return p!=NULL;}\n'
        )
        (p / 'test.c').write_text(source)
        for opt in ('-O0', '-O2'):
            subprocess.run(
                [
                    'cc',
                    '-std=c11',
                    opt,
                    '-Wall',
                    '-Wextra',
                    '-Werror',
                    '-fsanitize=undefined',
                    '-fno-sanitize-recover=all',
                    '-I' + td,
                    str(p / 'test.c'),
                    '-o',
                    str(p / 'test'),
                ],
                check=True,
            )
            subprocess.run([str(p / 'test')], check=True)


if __name__ == '__main__':
    test_pipeline_health()
