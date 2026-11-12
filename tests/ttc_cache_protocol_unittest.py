"""Protocol changes cannot hide behind the known cache-loading adapter."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_ttc_cached_reference import protocol


class CacheProtocolTest(unittest.TestCase):
    def source(self, cached=False):
        signature = ', prior_controls=None' if cached else ''
        block = "        print('full backward Euler reference', dt, flush=True)\n        be = backward_euler_pulse(g, c, b, h, power, dt, groups, loss)\n"
        if cached:
            block = ("        if prior_controls is None:\n" + ''.join('    '+line+'\n' for line in block.splitlines()) +
                     "        else:\n"
                     "            print('reuse verified full backward Euler reference', dt, flush=True)\n"
                     "            reference, metadata = prior_controls\n"
                     "            be = {k:reference['be_'+str(dt)+'_'+k] for k in ('sensors', 'body_means', 'cumulative_boundary_heat_j')}\n"
                     "            be.update(metadata['backward_euler'][str(dt)])\n")
        return ("import numpy as np\n"
                "def pulse(reduced, power):\n    return reduced.run(power, dt=.1)\n"
                "def physical_flux_check(reduced, assembly):\n    return 0.\n"
                f"def controls(g, c, b, h, loss, groups, assembly, reductions, folder{signature}):\n"
                "    power = np.array(list(patterns().values())).T\n"
                "    for dt in (.005, .0025, .00125):\n" + block +
                ('' if cached else "    write_json(folder/'numerical-controls.json', result)\n") +
                "    return result\n")

    def fingerprint(self, source):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root/'audit_ttc_package_transient.py'
            path.write_text(source)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            (root/'frozen-inputs.json').write_text(json.dumps(dict(code_sha256={str(path): digest})))
            return protocol(root)[1]

    def test_known_adapter_and_comments_preserve_protocol(self):
        self.assertEqual(self.fingerprint(self.source()), self.fingerprint(self.source(True)+'\n# comment\n'))

    def test_changed_power_steps_or_sampling_changes_protocol(self):
        original = self.source(True)
        for old, new in (('.T', '.T[:, ::-1]'), ('(.005, .0025, .00125)', '(.005, .0025, .000625)'),
                         ('dt=.1', 'dt=.2')):
            with self.subTest(change=old):
                self.assertNotEqual(self.fingerprint(self.source()), self.fingerprint(original.replace(old, new)))

    def test_modified_cache_adapter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unrecognized cache adapter'):
            self.fingerprint(self.source(True).replace("reference['be_'+str(dt)+'_'+k]", "2*reference['be_'+str(dt)+'_'+k]"))


if __name__ == '__main__':
    unittest.main()
