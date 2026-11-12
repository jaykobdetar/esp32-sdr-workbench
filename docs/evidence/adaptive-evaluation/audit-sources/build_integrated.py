import ast
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description="Generate host-only integrated sweep from this checkout")
parser.add_argument("--root",type=Path,required=True)
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args()
root=args.root.resolve()
out=args.output.resolve()
out.mkdir(parents=True,exist_ok=True)
tree=ast.parse((root/'firmware/tests/test_adaptive_pipeline_state.py').read_text())
source=next(ast.literal_eval(x.value) for x in tree.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE' for t in x.targets))
for key,file in [('ENERGY_HEADER','detector_energy.h'),('BACKGROUND_HEADER','detector_background.h'),('PIPE_HEADER','detector_pipeline.h')]:
 source=source.replace(key,str(root/'firmware/main/targets/esp32'/file))
source=source.replace('int main(void){','int baseline_main(void){').replace('reset(0,0);puts("pipeline candidate state, drain, retention, range, allocation-failure tests passed");','reset(0,0);puts("pipeline candidate state, drain, retention, range, allocation-failure tests passed"); return 0;')
source+=r'''
int main(void){
 assert(baseline_main()==0);
 unsigned allocation_cases=0,retention_cases=0,failure_cases=0;
 for(unsigned n=256;n<=16380;n++){
  reset(0,0);assert(detector_pipeline_command("PIPEKEEP 3"));char command[100];snprintf(command,sizeof(command),"DETPIPE1 1 %u 6 4000 1",n);assert(detector_pipeline_command(command));
  unsigned crop=n&~7u;if(crop>5120)crop=5120;unsigned bytes=crop*20/8, pages=(bytes+4095)/4096;
  assert(detpipe_keep==1&&detpipe_run_keep==3&&detpipe_page_count==3*pages&&active_allocations==3*pages);
  unsigned allocated=0;for(unsigned j=0;j<detpipe_page_count;j++)allocated+=detpipe_page_sizes[j];assert(allocated==3*bytes);assert(strstr(output,"\"status\":0"));allocation_cases++;
 }
 const unsigned lengths[]={256,257,263,264,1637,1638,1639,3276,3277,3278,4915,4916,5119,5120,5121,8191,8192,16319,16320,16379,16380};
 for(unsigned j=0;j<sizeof(lengths)/sizeof(*lengths);j++)for(unsigned kernel=0;kernel<=3;kernel+=3)for(unsigned fused=0;fused<=1;fused++){
  reset(0,0);detpipe_kernel=kernel;detpipe_copy_option=fused;detector_pipeline_command("PIPEKEEP 3");char command[100];snprintf(command,sizeof(command),"DETPIPE1 20 %u 6 4000 1",lengths[j]);detector_pipeline_command(command);
  assert(strstr(output,"\"status\":0,\"captures\":20,\"processed_captures\":20"));
  for(unsigned slot=0;slot<3;slot++){detector_candidate_t*c=&detpipe_candidates[slot];assert(c->samples==detector_crop_length(lengths[j])&&c->offset_samples+c->samples<=lengths[j]);assert(c->generation==17||c->generation==19||c->generation==20);assert(c->trigger_device_us==(c->generation-1)*1000+1);}
  retention_cases++;
 }
 for(unsigned failure=1;failure<=25;failure++)for(unsigned kernel=0;kernel<=3;kernel+=3)for(unsigned fused=0;fused<=1;fused++){
  reset(failure,0);detpipe_kernel=kernel;detpipe_copy_option=fused;detector_pipeline_command("PIPEKEEP 3");detector_pipeline_command("DETPIPE1 25 16380 6 4000 1");char expected[100];snprintf(expected,sizeof(expected),"\"status\":1,\"captures\":%u,\"processed_captures\":%u",failure-1,failure-1);assert(strstr(output,expected));
  for(unsigned slot=0;slot<3;slot++)if(detpipe_candidates[slot].samples)assert(detpipe_candidates[slot].generation<failure);
  failure_cases++;
 }
 reset(0,0);printf("PASS additional integrated allocation lengths=%u, retention combinations=%u, acquisition-failure combinations=%u; zero live allocations at finish\n",allocation_cases,retention_cases,failure_cases);
 return 0;
}
'''
(out/'integrated.c').write_text(source)
(out/'esp_memory_utils.h').write_text('static bool esp_ptr_internal(const void*p){return p!=NULL;}\nstatic bool esp_ptr_in_dram(const void*p){return p!=NULL&&!((uintptr_t)p>=reject_lo&&(uintptr_t)p<=reject_hi);}\nstatic bool esp_ptr_byte_accessible(const void*p){return p!=NULL;}\n')
