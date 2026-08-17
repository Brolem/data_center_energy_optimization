from __future__ import annotations

from collections.abc import Mapping

from .types import PowerScenario


NAMED_MODEL_TDP_WATTS = {
    "A10": 150.0,
    "A100-SXM4-80GB": 400.0,
    "A800-SXM4-80GB": 400.0,
    "H800": 700.0,
}

ANONYMOUS_MODEL_WATTS = {
    "low": {"GPU-series-1": 150.0, "GPU-series-2": 300.0},
    "baseline": {"GPU-series-1": 300.0, "GPU-series-2": 500.0},
    "high": {"GPU-series-1": 400.0, "GPU-series-2": 700.0},
}

POWER_SOURCE_URLS = {
    "A10": "https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/a10/pdf/a10-datasheet.pdf",
    "A100-SXM4-80GB": "https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/a100/pdf/nvidia-a100-datasheet-nvidia-us-2188504-web.pdf",
    "A800-SXM4-80GB": "https://docs.nvidia.com/dgx/archives/dgx-os-5-user-guide/known_issues.html",
    "H800": "https://www.delltechnologies.com/asset/en-us/products/servers/technical-support/poweredge-rack-quick-reference-guide.pdf.external",
}


def _scenario(
    name: str,
    *,
    pue: float,
    it_overhead_multiplier: float,
    active_power_fraction: float,
) -> PowerScenario:
    model_watts = dict(NAMED_MODEL_TDP_WATTS)
    model_watts.update(ANONYMOUS_MODEL_WATTS[name])
    return PowerScenario(
        name=name,  # type: ignore[arg-type]
        pue=pue,
        it_overhead_multiplier=it_overhead_multiplier,
        active_power_fraction=active_power_fraction,
        model_tdp_watts=tuple(sorted(model_watts.items())),
    )


class PowerModel:
    """Convert model-specific active GPU allocations to incremental facility MW."""

    def __init__(self, scenario: PowerScenario) -> None:
        self.scenario = scenario
        self._tdp_watts = dict(scenario.model_tdp_watts)

    @classmethod
    def low(cls) -> PowerModel:
        return cls(
            _scenario(
                "low",
                pue=1.10,
                it_overhead_multiplier=1.00,
                active_power_fraction=0.50,
            )
        )

    @classmethod
    def baseline(cls) -> PowerModel:
        return cls(
            _scenario(
                "baseline",
                pue=1.20,
                it_overhead_multiplier=1.15,
                active_power_fraction=0.70,
            )
        )

    @classmethod
    def high(cls) -> PowerModel:
        return cls(
            _scenario(
                "high",
                pue=1.40,
                it_overhead_multiplier=1.30,
                active_power_fraction=0.90,
            )
        )

    @property
    def supported_models(self) -> frozenset[str]:
        return frozenset(self._tdp_watts)

    def facility_mw(self, active_gpus_by_model: Mapping[str, float]) -> float:
        gpu_watts = 0.0
        for model, count in active_gpus_by_model.items():
            if model not in self._tdp_watts:
                raise ValueError(f"missing power mapping for GPU model {model!r}")
            if count < 0.0:
                raise ValueError(f"active GPU count cannot be negative for {model!r}")
            gpu_watts += (
                float(count)
                * self.scenario.active_power_fraction
                * self._tdp_watts[model]
            )
        return (
            self.scenario.pue
            * self.scenario.it_overhead_multiplier
            * gpu_watts
            / 1_000_000.0
        )


def power_scenarios() -> tuple[PowerScenario, ...]:
    return (
        PowerModel.low().scenario,
        PowerModel.baseline().scenario,
        PowerModel.high().scenario,
    )
