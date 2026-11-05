"""Independent energy/monotonicity oracles for machine coolant outputs."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.retrieval_service.tools.thermal_calculators import coolant_temperature_rise
from services.retrieval_service.tools.tool_registry import run_detected_tool
from services.retrieval_service.visualization.request_graph import build_requested_visualization


class CoolantPrecisionTests(unittest.TestCase):
    def test_small_and_normal_heat_preserves_energy_and_strict_monotonicity(self):
        for heat in (1e-10, .001, .004, 500., 1e7):
            with self.subTest(heat=heat):
                outputs = []
                for index in range(21):
                    mass = .1 + .4 * index / 20
                    result = coolant_temperature_rise(Q_W=heat, m_dot_kg_s=mass, cp_J_kgK=4000.)
                    self.assertEqual(result['status'], 'ok')
                    delta = result['result']['delta_T_K']
                    self.assertTrue(math.isclose(mass * 4000. * delta, heat, rel_tol=1e-12, abs_tol=0))
                    outputs.append(delta)
                self.assertTrue(all(left > right > 0 for left, right in zip(outputs, outputs[1:])))

    def test_outlet_temperature_preserves_available_float_precision(self):
        inlet = 28.123456789
        result = coolant_temperature_rise(Q_W=.004, m_dot_kg_s=.14, cp_J_kgK=4000., T_in_C=inlet)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['result']['T_out_C'], inlet + .004 / (.14 * 4000.))
        self.assertTrue(result['calculation_steps'])

    def test_real_curve_keeps_small_energy_and_unit_equivalence(self):
        for heat in (.001, .004, 500.):
            curves = []
            for flow in ('质量流量0.1至0.5 kg/s', '体积流量6至30 L/min', '体积流量0.36至1.8 m3/h'):
                response = build_requested_visualization(f'画流量温升曲线，Q={heat}W，比热4000 J/kgK，密度1000 kg/m3，{flow}')
                self.assertTrue(response['generated'])
                curves.append(response['graph']['chart']['series'][0]['points'])
            for index, point in enumerate(curves[0]):
                mass = .1 + .4 * index / 20
                expected = heat / mass / 4000.
                self.assertTrue(math.isclose(point['y'], expected, rel_tol=1e-12, abs_tol=0))
                for equivalent in curves[1:]:
                    self.assertTrue(math.isclose(equivalent[index]['y'], expected, rel_tol=1e-12, abs_tol=0))
            self.assertTrue(all(a['y'] > b['y'] for a, b in zip(curves[0], curves[0][1:])))

    def test_original_scalar_agent_tool_path_retains_small_result(self):
        result = run_detected_tool('质量流量0.14 kg/s，带走0.004W热量，比热容4000 J/(kg*K)，冷却液温升多少？')
        self.assertIsNotNone(result)
        self.assertEqual(result['tool_name'], 'coolant_temperature_rise')
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(math.isclose(result['result']['delta_T_K'] * .14 * 4000., .004, rel_tol=1e-12, abs_tol=0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
