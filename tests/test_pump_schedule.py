import unittest

from aquaflow.api import AquaFlowService
from aquaflow.pumps.schedule import Hist, Pump, choose

P1 = Pump("P1", kw=40, flow=50, min_run=1, min_rest=4)
P2 = Pump("P2", kw=60, flow=60, min_run=1, min_rest=4)
PUMPS = [P1, P2]


def hist(running, since_start, since_stop):
    return {"P1": Hist(running[0], since_start[0], since_stop[0]),
            "P2": Hist(running[1], since_start[1], since_stop[1])}


class TestMinRestInterlock(unittest.TestCase):
    def test_just_stopped_pump_is_excluded(self):
        # P1 started long ago (since_start >= min_rest) but stopped 0.5h ago:
        # the rest clock, not the start clock, must lock it out.
        h = hist((False, False), (10, 8), (0.5, 6))
        self.assertEqual(choose(PUMPS, h, required=50, max_kw=100), ["P2"])

    def test_rested_pump_is_eligible_again(self):
        # P1 has rested exactly min_rest hours: the interval is over.
        h = hist((False, False), (10, 8), (4, 6))
        self.assertEqual(choose(PUMPS, h, required=50, max_kw=100), ["P1"])

    def test_running_pump_stays_eligible(self):
        # Already running, so the restart interlock does not apply.
        h = hist((True, False), (0.5, 8), (0, 6))
        self.assertEqual(choose(PUMPS, h, required=50, max_kw=100), ["P1"])

    def test_two_pumps_combine_to_meet_flow(self):
        h = hist((False, False), (10, 8), (5, 6))
        self.assertEqual(choose(PUMPS, h, required=100, max_kw=100), ["P1", "P2"])

    def test_infeasible_demand_fails_clearly(self):
        h = hist((False, False), (10, 8), (5, 6))
        with self.assertRaisesRegex(ValueError, "no feasible combination"):
            choose(PUMPS, h, required=200, max_kw=100)

    def test_all_pumps_interlocked_fails_clearly(self):
        h = hist((False, False), (10, 8), (1, 2))
        with self.assertRaisesRegex(ValueError, "no feasible combination"):
            choose(PUMPS, h, required=50, max_kw=100)


class TestDispatchWorkflow(unittest.TestCase):
    PAYLOAD = {
        "pumps": [
            {"id": "P1", "kw": 40, "flow": 50, "min_run": 1, "min_rest": 4},
            {"id": "P2", "kw": 60, "flow": 60, "min_run": 1, "min_rest": 4},
        ],
        "history": {
            "P1": {"running": False, "since_start": 10, "since_stop": 0.5},
            "P2": {"running": False, "since_start": 8, "since_stop": 6},
        },
        "required": 50,
        "max_kw": 100,
    }

    def test_workflow_excludes_just_stopped_pump(self):
        result = AquaFlowService().run_workflow("pump_dispatch", self.PAYLOAD)
        self.assertEqual(result["decision"], "dispatch")
        self.assertEqual(result["value"], ["P2"])
        self.assertEqual(result["evidence"]["capacity"], 60)
        self.assertEqual(result["audit"]["contract"], "v1")

    def test_workflow_infeasible_demand_fails_clearly(self):
        payload = dict(self.PAYLOAD, required=200)
        with self.assertRaisesRegex(ValueError, "no feasible combination"):
            AquaFlowService().run_workflow("pump_dispatch", payload)


if __name__ == "__main__":
    unittest.main()
