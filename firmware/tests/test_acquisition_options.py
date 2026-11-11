import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AcquisitionOptions(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_every_word_fault_and_full_clear(self):
        src = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "main/targets/esp32/validate_candidates.h"
static uint32_t words[VALIDATE_CAPACITY];
static unsigned cases;
static void compare(unsigned n,unsigned expected){
 assert(validate_original(words,n)==expected);assert(validate_split(words,n)==expected);
 assert(validate_aggregate(words,n)==expected);assert(validate_unroll4(words,n)==expected);cases++;
}
int main(void){
 unsigned lengths[]={256,257,8191,16379,16380};
 for(unsigned c=0;c<5;c++){
  unsigned n=lengths[c];clear_original(words);for(unsigned j=0;j<n;j++)words[j]=j;
  compare(n,UINT_MAX);
  /* Every capture and guard word, not just a random subset. */
  for(unsigned j=0;j<VALIDATE_CAPACITY;j++){
   uint32_t old=words[j];words[j]=j<n?VALIDATE_SENTINEL:~VALIDATE_SENTINEL;
   compare(n,j);words[j]=old;
  }
  /* Multiple faults must report the earliest index for aggregate candidates. */
  for(unsigned j=0;j<VALIDATE_CAPACITY;j+=127){
   uint32_t a=words[j],b=words[VALIDATE_CAPACITY-1];
   words[j]=j<n?VALIDATE_SENTINEL:0;words[VALIDATE_CAPACITY-1]=0;
   compare(n,j);words[j]=a;words[VALIDATE_CAPACITY-1]=b;
  }
  for(unsigned j=0;j<VALIDATE_CAPACITY;j++)words[j]=~VALIDATE_SENTINEL;
  clear_unroll8(words);for(unsigned j=0;j<VALIDATE_CAPACITY;j++)assert(words[j]==VALIDATE_SENTINEL);
 }
 printf("%u all-word and earliest-fault equivalence cases passed\n",cases);return 0;
}
"""
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            (p / 'test.c').write_text(src)
            subprocess.run(
                [
                    'cc',
                    '-O2',
                    '-Wall',
                    '-Wextra',
                    '-Werror',
                    '-fsanitize=undefined',
                    '-fno-sanitize-recover=all',
                    '-I' + str(ROOT),
                    str(p / 'test.c'),
                    '-o',
                    str(p / 'test'),
                ],
                check=True,
            )
            r = subprocess.run(
                [str(p / 'test')], check=True, text=True, capture_output=True, timeout=120
            )
            self.assertIn('passed', r.stdout)
