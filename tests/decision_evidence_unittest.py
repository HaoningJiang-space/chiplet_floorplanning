import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.validation.decision_evidence import (verify_coverage, verify_inputs, verify_runtime,
    verify_timing_identity, verify_saved_sta_files, verify_artifact_links, file_hash)


class DecisionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.frozen = dict(profiles={'nominal': {'routing': {}, 'power_w': 3}},
                           layouts={'a': {'x': 0}, 'b': {'x': 1}},
                           route_orders={'first': ['data', 'clock']}, domain_size=2)
        self.rows = [dict(id=k, layout_id=k, profile='nominal', policy='first') for k in ('a', 'b')]

    def test_missing_duplicate_and_extra_case_do_not_receive_certificate(self):
        self.assertEqual(verify_coverage(self.rows, self.frozen), 2)
        for rows in (self.rows[:1], self.rows+[self.rows[0]], [self.rows[0], self.rows[0]]):
            with self.assertRaises(ValueError):
                verify_coverage(rows, self.frozen)

    def test_labels_cannot_hide_changed_power_layout_or_order(self):
        inputs = dict(layout={'x': 0}, configuration={'routing': {'order': ['data', 'clock']}, 'power_w': 3})
        row = dict(self.rows[0], input_sha256=hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest())
        verify_inputs(row, inputs, self.frozen)
        for key in ('power', 'layout', 'order', 'fingerprint'):
            changed = copy.deepcopy(inputs); candidate = row.copy()
            if key=='power':
                changed['configuration']['power_w'] = 4
            elif key=='layout':
                changed['layout']['x'] = 1
            elif key=='order':
                changed['configuration']['routing']['order'].reverse()
            else:
                candidate['input_sha256'] = '0'*64
            with self.assertRaises(ValueError):
                verify_inputs(candidate, changed, self.frozen)

    def test_runtime_checks_actual_selected_root_and_all_frozen_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); sta = root/'sta'; sta.write_bytes(b'original STA')
            original = root/'pdk-v03'; original.mkdir()
            custom = root/'custom-models'; custom.mkdir()
            for folder in (original, custom):
                (folder/'used.json').write_bytes(b'locked model')
                (folder/'other.json').write_bytes(b'other locked source')
            frozen = dict(executable_sha256=file_hash(sta), pdk_source_sha256={
                'pdk-v03/'+p.name: file_hash(p) for p in original.iterdir()})
            self.assertEqual(verify_runtime(sta, custom, frozen), frozen)
            (custom/'other.json').write_bytes(b'changed selected root; sibling remains valid')
            with self.assertRaisesRegex(ValueError, 'PDK source'):
                verify_runtime(sta, custom, frozen)
            sta.write_bytes(b'other STA')
            with self.assertRaisesRegex(ValueError, 'executable'):
                verify_runtime(sta, original, frozen)

    def test_changed_runtime_receipt_or_saved_library_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); lib = folder/'driver.lib'; lib.write_bytes(b'original library')
            (folder/'sta.log').write_bytes(b'observed paths')
            receipt = dict(executable_sha256='exe', input_sha256={'driver.lib': file_hash(lib)},
                log_sha256=file_hash(folder/'sta.log'), models={'driver': dict(path=str(lib),
                    source_files={'source.json': 'source'})})
            frozen = dict(executable_sha256='exe', pdk_source_sha256={'pdk-v03/source.json': 'source'})
            verify_timing_identity(receipt, frozen); verify_saved_sta_files(receipt, folder)
            for target in ('executable', 'source'):
                changed = copy.deepcopy(receipt)
                if target=='executable':
                    changed['executable_sha256'] = 'different'
                else:
                    changed['models']['driver']['source_files']['source.json'] = 'different'
                with self.assertRaises(ValueError):
                    verify_timing_identity(changed, frozen)
            lib.write_bytes(b'changed input capacitance after STA')
            with self.assertRaisesRegex(ValueError, 'input hash'):
                verify_saved_sta_files(receipt, folder)

    def test_accepted_audits_from_another_experiment_are_rejected(self):
        benchmark = dict(complete=True, frozen_inputs_sha256='frozen')
        witness = dict(complete=True, benchmark_inputs_sha256='frozen')
        thermal = copy.deepcopy(witness)
        channel = dict(accepted=True, input_report_sha256={'benchmark': 'b', 'witness': 'w'})
        verify_artifact_links('frozen', benchmark, witness, thermal, channel, ['b', 'w'])
        for target in ('benchmark', 'witness', 'thermal', 'channel'):
            records = copy.deepcopy([benchmark, witness, thermal, channel])
            if target=='channel':
                records[3]['input_report_sha256']['witness'] = 'different'
            elif target=='benchmark':
                records[0]['frozen_inputs_sha256'] = 'different'
            else:
                records[1 if target=='witness' else 2]['benchmark_inputs_sha256'] = 'different'
            with self.assertRaises(ValueError):
                verify_artifact_links('frozen', *records, ['b', 'w'])


if __name__=='__main__':
    unittest.main()
