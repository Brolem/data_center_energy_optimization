import unittest

from dc_energy_opt.optimization.types import PendingFlexibleTask, WindowSolveState


class OptimizationTypeTests(unittest.TestCase):
    def test_window_state_preserves_energy_and_pending_tasks(self) -> None:
        task = PendingFlexibleTask(origin_hour=-1, remaining_cpu_pu=0.25)
        state = WindowSolveState(
            stored_energy_mwh=1.0,
            pending_flexible_tasks=(task,),
        )

        self.assertEqual(state.stored_energy_mwh, 1.0)
        self.assertEqual(state.pending_flexible_tasks, (task,))
