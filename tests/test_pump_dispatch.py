import unittest

from aquaflow.pumps.schedule import Hist, Pump, choose
from aquaflow.workflow_rules import evaluate


def p(pid, flow=100.0, kw=50.0, min_rest=30.0):
    return Pump(pid, kw, flow, min_run=5.0, min_rest=min_rest)


class TestMinimumRestInterlock(unittest.TestCase):
    def test_just_stopped_pump_is_excluded(self):
        # Started long ago, but stopped moments ago: since_start looks rested,
        # the interlock must instead read since_stop and keep it out.
        pumps = [p("A")]
        hist = {"A": Hist(running=False, since_start=9999.0, since_stop=1.0)}
        with self.assertRaises(ValueError):
            choose(pumps, hist, required=50.0, max_kw=1000.0)

    def test_running_pump_stays_selectable(self):
        pumps = [p("A")]
        hist = {"A": Hist(running=True, since_start=1.0, since_stop=9999.0)}
        self.assertEqual(choose(pumps, hist, required=50.0, max_kw=1000.0), ["A"])

    def test_rested_pump_is_selectable_again(self):
        pumps = [p("A", min_rest=30.0)]
        hist = {"A": Hist(running=False, since_start=5.0, since_stop=31.0)}
        self.assertEqual(choose(pumps, hist, required=50.0, max_kw=1000.0), ["A"])

    def test_boundary_rest_interval_is_inclusive(self):
        pumps = [p("A", min_rest=30.0)]
        hist = {"A": Hist(running=False, since_start=0.0, since_stop=30.0)}
        self.assertEqual(choose(pumps, hist, required=50.0, max_kw=1000.0), ["A"])

    def test_two_pumps_combined_to_meet_flow(self):
        # A just stopped (locked out); B alone cannot meet demand, B+C can.
        pumps = [p("A", flow=100.0, kw=50.0),
                 p("B", flow=60.0, kw=30.0),
                 p("C", flow=60.0, kw=30.0)]
        hist = {
            "A": Hist(running=False, since_start=9999.0, since_stop=1.0),
            "B": Hist(running=False, since_start=9999.0, since_stop=120.0),
            "C": Hist(running=False, since_start=9999.0, since_stop=120.0),
        }
        self.assertEqual(choose(pumps, hist, required=100.0, max_kw=1000.0), ["B", "C"])

    def test_rested_pump_preferred_over_two_pump_combo(self):
        # Once the big pump has rested it alone meets demand with lower kw.
        pumps = [p("A", flow=100.0, kw=50.0),
                 p("B", flow=60.0, kw=30.0),
                 p("C", flow=60.0, kw=30.0)]
        hist = {
            "A": Hist(running=False, since_start=9999.0, since_stop=40.0),
            "B": Hist(running=False, since_start=9999.0, since_stop=120.0),
            "C": Hist(running=False, since_start=9999.0, since_stop=120.0),
        }
        self.assertEqual(choose(pumps, hist, required=100.0, max_kw=1000.0), ["A"])

    def test_infeasible_demand_raises_clear_failure(self):
        pumps = [p("A", flow=40.0), p("B", flow=40.0)]
        hist = {
            "A": Hist(running=False, since_start=9999.0, since_stop=120.0),
            "B": Hist(running=False, since_start=9999.0, since_stop=120.0),
        }
        with self.assertRaises(ValueError):
            choose(pumps, hist, required=100.0, max_kw=1000.0)

    def test_locked_out_pump_cannot_mask_power_infeasibility(self):
        # A alone would satisfy flow but is locked out; the rest exceed max_kw.
        pumps = [p("A", flow=100.0, kw=10.0), p("B", flow=100.0, kw=80.0)]
        hist = {
            "A": Hist(running=False, since_start=9999.0, since_stop=1.0),
            "B": Hist(running=False, since_start=9999.0, since_stop=120.0),
        }
        with self.assertRaises(ValueError):
            choose(pumps, hist, required=90.0, max_kw=50.0)


def _payload(history):
    return {
        "pumps": [
            {"id": "A", "kw": 50.0, "flow": 100.0, "min_run": 5.0, "min_rest": 30.0},
            {"id": "B", "kw": 30.0, "flow": 60.0, "min_run": 5.0, "min_rest": 30.0},
            {"id": "C", "kw": 30.0, "flow": 60.0, "min_run": 5.0, "min_rest": 30.0},
        ],
        "history": history,
        "required": 100.0,
        "max_kw": 1000.0,
    }


class TestDispatchWorkflowPath(unittest.TestCase):
    def test_just_stopped_excluded_end_to_end(self):
        payload = _payload({
            "A": {"running": False, "since_start": 9999.0, "since_stop": 1.0},
            "B": {"running": False, "since_start": 9999.0, "since_stop": 120.0},
            "C": {"running": False, "since_start": 9999.0, "since_stop": 120.0},
        })
        result = evaluate("pump_dispatch", payload)
        self.assertEqual(result["value"], ["B", "C"])
        self.assertEqual(result["evidence"]["capacity"], 120.0)

    def test_rested_pump_recovered_end_to_end(self):
        payload = _payload({
            "A": {"running": False, "since_start": 2.0, "since_stop": 31.0},
            "B": {"running": False, "since_start": 9999.0, "since_stop": 120.0},
            "C": {"running": False, "since_start": 9999.0, "since_stop": 120.0},
        })
        result = evaluate("pump_dispatch", payload)
        self.assertEqual(result["value"], ["A"])

    def test_infeasible_demand_fails_end_to_end(self):
        payload = _payload({
            "A": {"running": False, "since_start": 9999.0, "since_stop": 1.0},
            "B": {"running": False, "since_start": 9999.0, "since_stop": 1.0},
            "C": {"running": False, "since_start": 9999.0, "since_stop": 1.0},
        })
        with self.assertRaises(ValueError):
            evaluate("pump_dispatch", payload)

    def test_normalized_contract_no_longer_overrides_rest_clock(self):
        from aquaflow.api import AquaFlowService

        payload = _payload({
            "A": {"running": False, "since_start": 9999.0, "since_stop": 1.0},
            "B": {"running": False, "since_start": 9999.0, "since_stop": 120.0},
            "C": {"running": False, "since_start": 9999.0, "since_stop": 120.0},
        })
        result = AquaFlowService().run_workflow("pump_dispatch", payload)
        self.assertEqual(result["value"], ["B", "C"])
        self.assertEqual(result["audit"]["contract"], "v1")


if __name__ == "__main__":
    unittest.main()
