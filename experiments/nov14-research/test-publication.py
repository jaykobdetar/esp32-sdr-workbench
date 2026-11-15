"""Hash, image, numerical-projection and source-overlay consistency checks."""
import hashlib,json,pathlib,unittest
R=pathlib.Path(__file__).resolve().parent
class Publication(unittest.TestCase):
 def test_overlays(self):
  for variant in ['core-bank-v9','compact-v2']:
   for rel,h in json.loads((R/variant/'overlay-sha256.json').read_text()).items():
    self.assertEqual(hashlib.sha256((R/variant/'overlay'/rel).read_bytes()).hexdigest(),h)
 def test_images(self):
  for name,h in {'core-bank-v9-app.bin':'8a8b9036a012d80017d05dd494acf8080d825f4b2149d587c70d7f778ee3b2b5','compact-v2-app.bin':'fc629ff663647f3e27c4b9494ef78e220ce74ac46cf5137ac8362edf3a73bea5'}.items():self.assertEqual(hashlib.sha256((R/'firmware-images'/name).read_bytes()).hexdigest(),h)
 def test_projected_results(self):
  e=R.parents[1]/'docs/evidence/nov14-compact-comparison'
  ds=[json.loads((e/f'rx{n}-analysis.json').read_text()) for n in (0,1)]
  self.assertEqual(sum(d['verified_captures'] for d in ds),480)
  counts={m:sum(b['source_consistent_records'] or 0 for d in ds for b in d['blocks'] if b['mode']==m) for m in ['compact','legacy']}
  self.assertEqual(counts,{'compact':82,'legacy':91})
if __name__=='__main__':unittest.main()
