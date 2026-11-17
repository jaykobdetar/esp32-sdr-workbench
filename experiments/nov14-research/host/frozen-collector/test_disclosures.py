import unittest,struct
import collector
class DisclosureTests(unittest.TestCase):
 def test_mock_hypothesis_counters(self):
  vals=[0,0,9,7,2,5,3,4,6,8,8189,40945,16372]
  d=collector.verification_disclosures(struct.pack('<13I',*vals)+bytes(1792),0)
  self.assertEqual(list(d['native_counters'].values()),vals)
  self.assertTrue(d['decoder_output_drops_present']);self.assertEqual(d['configured_output_cap'],0)
  self.assertEqual(d['observed_body_records_checked'],0);self.assertIsNone(d['observed_body_crc_consistent'])
  for k in ('symbol_support_evaluated','source_association_evaluated','transmitter_attestation'):self.assertIs(d[k],False)
  self.assertNotIn('missed_packets',d);self.assertNotIn('source_recall',d)
 def test_existing_iq_caps(self):
  v,lib=collector.reference();m,iq,t=v.frame((collector.ROOT/'mock-result.bin.iq').read_bytes())
  observed=[]
  for cap in (0,1,64):
   r=v.replay(lib,iq,cap);d=collector.verification_disclosures(bytes(r),cap)
   self.assertEqual(d['native_counters']['count'],r.count)
   self.assertEqual(d['native_counters']['output_drops'],r.output_drops)
   self.assertEqual(d['decoder_output_drops_present'],r.output_drops>0)
   observed.append((r.count,r.output_drops))
  self.assertEqual(observed,[(0,12),(1,8),(3,0)])
 def test_normal_summary_both_modes(self):
  import tempfile
  from pathlib import Path
  from test_collector import Fake
  from test_compact_collector import CompactFake
  for mode,cls in [('legacy',Fake),('compact',CompactFake)]:
   with tempfile.TemporaryDirectory() as temp:
    fake=cls();r=collector.Collector(fake,Path(temp)/'session',exclusive_idle=True,mode=mode,clock=fake.clock).run()
    self.assertTrue(r['success'],r)
    v=r['verification'];self.assertEqual(v['observed_records'],3)
    self.assertIsNone(v['source_recall']);self.assertIsNone(v['coverage'])
    self.assertIn('not transmitter attestation',v['evidence'])
    self.assertEqual(v['native_counters']['count'],3)
    self.assertFalse(v['symbol_support_evaluated']);self.assertFalse(v['source_association_evaluated'])
    self.assertFalse(v['decoder_output_drops_present']);self.assertEqual(v['configured_output_cap'],64)
if __name__=='__main__':unittest.main()
