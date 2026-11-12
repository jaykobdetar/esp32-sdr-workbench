"""Exercise diagnostic lifetime, parser, overflow and schedule code under UBSan."""

import importlib.util
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('state', HERE / 'test_adaptive_pipeline_state.py')
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


def test_dual_timing_state(tmp_path):
    source = state.SOURCE.split('int main(void){')[0]
    source = source.replace('return now;', 'return now++;')
    root = HERE.parent / 'main/targets/esp32'
    source = (
        source.replace('ENERGY_HEADER', str(root / 'detector_energy.h'))
        .replace('BACKGROUND_HEADER', str(root / 'detector_background.h'))
        .replace('PIPE_HEADER', str(root / 'detector_pipeline.h'))
    )
    source += '\nstatic bool acquire_iq(unsigned n,unsigned s,unsigned c,unsigned *us){return acquire_iq_with_work(n,s,c,us,NULL,NULL);}\n'
    source += 'static bool burst_send_capture(unsigned n,unsigned f,unsigned us){(void)n;(void)f;(void)us;return true;}\n'
    source += f'#include "{root / "dual_timing_commands.h"}"\n'
    source += r"""
int main(void){
 uint64_t a[3];
 assert(dual_arguments(" 123 0 16",a,3));assert(a[0]==123&&a[1]==0&&a[2]==16);
 const char *bad[]={"123 0 16"," -1 0 16"," +1 0 16"," 18446744073709551616 0 16"," 123 0 16x"," 123 0 16 "," 123 0"," 123  0 16"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++)assert(!dual_arguments(bad[i],a,3));
 assert(dual_timing_command("TRACEARM 100000 1800 16"));assert(dual_armed);
 assert(dual_timing_command("TRACEARM 1 1800 16"));assert(dual_armed_deadline==100000);
 assert(dual_trace_begin());assert(active_allocations==1&&!dual_armed&&dual_active);
 dual_wait_trigger();assert(now>=100000&&dual_next==101800);
 for(unsigned i=0;i<DUAL_TRACE_CAPACITY;i++)dual_trace_record(100000+i*1800);
 assert(dual_count==DUAL_TRACE_CAPACITY&&!dual_overflow);
 dual_trace_record(9000000);assert(dual_overflow&&dual_count==DUAL_TRACE_CAPACITY);
 dual_trace_end();assert(!dual_active&&!dual_next);
 assert(dual_timing_command("TRACECLEAR"));assert(!dual_trace&&active_allocations==0);
 dual_armed=true;alloc_fail=allocs+1;
 assert(!dual_trace_begin());assert(!dual_active&&!dual_armed&&!active_allocations);
 alloc_fail=0;dual_armed=true;dual_armed_deadline=now+10000;
 assert(dual_trace_begin());dual_trace_record(100);dual_trace_record(1500);dual_trace_end();
 wire_len=0;assert(dual_timing_command("TRACEGET"));assert(wire_len==8);
 assert(dual_timing_command("TRACECLEAR"));assert(!active_allocations);
 return 0;
}
"""
    (tmp_path / 'esp_memory_utils.h').write_text(
        'static bool esp_ptr_internal(const void*p){return p!=NULL;}\n'
        'static bool esp_ptr_in_dram(const void*p){return p!=NULL;}\n'
        'static bool esp_ptr_byte_accessible(const void*p){return p!=NULL;}\n'
    )
    (tmp_path / 'test.c').write_text(source)
    for opt in ('-O0', '-O2'):
        subprocess.run(
            [
                'cc',
                '-std=c11',
                opt,
                '-Wall',
                '-Wextra',
                '-Werror',
                '-Wno-unused-function',
                '-fsanitize=undefined',
                '-fno-sanitize-recover=all',
                '-I' + str(tmp_path),
                str(tmp_path / 'test.c'),
                '-o',
                str(tmp_path / 'test'),
            ],
            check=True,
        )
        subprocess.run([str(tmp_path / 'test')], check=True, timeout=10)
