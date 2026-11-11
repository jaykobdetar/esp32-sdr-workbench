import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_padding_all_lengths_and_bounds():
    source = r"""
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
#include "ascii_frame.h"
int main(void){
 for(unsigned n=1;n<=1500;n++){
  char line[1503];memset(line,'x',sizeof(line));line[n-1]='\n';line[n]=0;
  size_t got=ascii_frame_pad(line,n,sizeof(line));assert(got==n+(n%64==0));assert(line[got-1]=='\n');assert(line[got]==0);
  assert(got%64!=0);for(unsigned j=0;j<n-1;j++)assert(line[j]=='x');
  if(n%64==0)assert(line[n-1]==' ');
 }
 char tiny[65];memset(tiny,'x',65);tiny[63]='\n';tiny[64]=0;assert(!ascii_frame_pad(tiny,64,65));assert(tiny[63]=='\n');
 assert(!ascii_frame_pad(tiny,0,65));assert(!ascii_frame_pad(tiny,65,65));
 return 0;
}
"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / 'test.c').write_text(source)
        subprocess.run(
            [
                'cc',
                '-O2',
                '-Wall',
                '-Wextra',
                '-Werror',
                '-fsanitize=undefined',
                '-I' + str(ROOT / 'main/targets/esp32'),
                str(p / 'test.c'),
                '-o',
                str(p / 'test'),
            ],
            check=True,
        )
        subprocess.run([str(p / 'test')], check=True)
