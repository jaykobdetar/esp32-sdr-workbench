"""Exact v1/v2 arithmetic equivalence across valid lengths, tails and extremes."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DetectorEnergyV2(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'Host C compiler unavailable')
    def test_exact_v1_equivalence_under_ubsan(self):
        source = r"""
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#define detector_energy energy_v1
#include "tests/fixtures/detector_energy_v1.h"
#undef detector_energy
#define detector_energy energy_v2
#include "main/targets/esp32/detector_energy.h"
#undef detector_energy
static uint32_t state=0xdeadbeef;
static uint32_t random_word(void){state^=state<<13;state^=state>>17;state^=state<<5;return state;}
static uint32_t words[16380];
static unsigned checks;
static void compare(unsigned n){
 uint32_t a,b,c,d;
 energy_v1(words,n,&a,&b);energy_v2(words,n,&c,&d);
 assert(a==c && b==d);assert(a<=524288 && b<=524288);
 /* Trailing samples must not influence either output. */
 for(unsigned j=(n/64)*64;j<n;j++)words[j]=random_word();
 energy_v2(words,n,&c,&d);assert(a==c && b==d);
 energy_v1(words,n,&c,&d);assert(a==c && b==d);
 checks++;
}
int main(void){
 const unsigned lengths[]={0,1,2,63,64,65,127,128,129,255,256,257,511,512,513,1023,1024,2047,2048,4095,4096,8191,8192,16319,16320,16321,16379,16380};
 const int extremes[]={-512,-511,-1,0,1,510,511};
 for(unsigned i=0;i<7;i++)for(unsigned q=0;q<7;q++){
  uint32_t w=((uint32_t)extremes[i]&1023)|(((uint32_t)extremes[q]&1023)<<10);
  for(unsigned k=0;k<28;k++){
   for(unsigned j=0;j<16380;j++)words[j]=w|0xfff00000;
   compare(lengths[k]);
   uint32_t a,b;energy_v2(words,lengths[k],&a,&b);assert(a==0 && b==0);
  }
 }
 /* Alternating extremes maximize variance; cross-block DC offsets vary. */
 for(unsigned k=0;k<28;k++){
  for(unsigned j=0;j<16380;j++){
   int i=(j&1)?511:-512,q=(j&2)?511:-512;
   words[j]=((uint32_t)i&1023)|(((uint32_t)q&1023)<<10);
  }
  compare(lengths[k]);
 }
 /* Complete and partial captures; metadata bits exercised and ignored. */
 for(unsigned trial=0;trial<4096;trial++){
  for(unsigned j=0;j<16380;j++)words[j]=random_word();
  unsigned n=trial%4 ? random_word()%16381:16380;
  compare(n);
 }
 printf("%u exact v1/v2 comparisons passed; tails unchanged\n",checks);
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            (p / 'check.c').write_text(source)
            for optimization in ('-O0', '-O2'):
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
                        '-I' + str(ROOT),
                        str(p / 'check.c'),
                        '-o',
                        str(p / 'check'),
                    ],
                    check=True,
                )
                result = subprocess.run(
                    [str(p / 'check')], check=True, capture_output=True, text=True, timeout=90
                )
                self.assertIn('5496 exact v1/v2 comparisons passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
