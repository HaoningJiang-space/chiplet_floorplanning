"""Independent hand-calculated constraint surfaces, without PDK downloads."""

from pathlib import Path
import tempfile
import unittest

from tools.validation.interface_bridge import query_constraint, receiver_tables


def constraint_library(swapped=False, hold_negative=False):
    variables = (["constrained_pin_transition", "related_pin_transition"] if swapped else
                 ["related_pin_transition", "constrained_pin_transition"])
    axes = (["0.2, 0.8", "0.1, 0.5"] if swapped else ["0.1, 0.5", "0.2, 0.8"])
    # Analytic surface f(clock_slew, data_slew) = 2*clock_slew + 3*data_slew.
    values = '"0.8, 1.6", "2.6, 3.4"' if swapped else '"0.8, 2.6", "1.6, 3.4"'
    text = f'''library(test) {{
lu_table_template(constraints) {{variable_1:{variables[0]};variable_2:{variables[1]};}}
cell(FF) {{ff(IQ,IQN) {{clocked_on:"CLK";next_state:"D";}}
pin(D) {{
'''
    for check in ("setup", "hold"):
        rows = '"-0.1, -0.1", "-0.1, -0.1"' if hold_negative and check == "hold" else values
        text += f'timing() {{related_pin:"CLK";timing_type:{check}_rising;'
        for edge in ("rise", "fall"):
            text += f'{edge}_constraint(constraints) {{index_1("{axes[0]}");index_2("{axes[1]}");values({rows});}}'
        text += '}'
    return text + '}}}'


class RealInterfaceConstraintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "constraint.lib"

    def tearDown(self):
        receiver_tables.cache_clear()
        self.temp.cleanup()

    def query(self, text, data=0.4, clock=0.3, check="setup"):
        receiver_tables.cache_clear()
        self.path.write_text(text)
        return query_constraint(self.path, "FF", check, "rise", data, clock)

    def test_opposite_axis_orders_recover_same_physical_surface(self):
        a = self.query(constraint_library())
        b = self.query(constraint_library(swapped=True))
        self.assertAlmostEqual(a["value_ns"], 1.8)
        self.assertAlmostEqual(b["value_ns"], 1.8)
        self.assertNotEqual(a["query_ns"], b["query_ns"])
        self.assertTrue(a["inside_table_domain"] and b["inside_table_domain"])

    def test_wrong_axis_order_is_not_numerically_invisible(self):
        broken = constraint_library().replace('variable_1:related_pin_transition;variable_2:constrained_pin_transition;',
                                               'variable_1:constrained_pin_transition;variable_2:related_pin_transition;')
        self.assertGreater(abs(self.query(broken)["value_ns"] - 1.8), 0.05)

    def test_extrapolated_value_is_preserved_but_not_qualified(self):
        result = self.query(constraint_library(), data=0.9)
        self.assertAlmostEqual(result["value_ns"], 3.3)
        self.assertFalse(result["inside_table_domain"])

    def test_negative_hold_constraint_is_not_clamped(self):
        result = self.query(constraint_library(hold_negative=True), check="hold")
        self.assertAlmostEqual(result["value_ns"], -0.1)

    def test_conditional_constraint_is_not_silently_selected(self):
        text = constraint_library().replace('timing_type:setup_rising;', 'timing_type:setup_rising;when:"EN";')
        with self.assertRaisesRegex(ValueError, "conditional"):
            self.query(text)


if __name__ == "__main__":
    unittest.main()
