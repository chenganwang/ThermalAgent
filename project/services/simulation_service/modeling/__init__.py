"""Safe autonomous simulation-modeling contracts and deterministic services."""

from .capabilities import SimulationBuildCapabilityProbe
from .compiler import CompilationPlanner, GeneratedModelArtifactStore, ModelCompiler
from .janitor import GeneratedModelJanitor
from .model_ir import ModelIR
from .lifecycle import GeneratedModelRepository, GeneratedModelService
from .registry import ComponentRegistry
from .synthesizer import FakeModelSynthesizer, RuleBasedModelSynthesizer
from .simulink_compiler import SimulinkCompilerBackend
from .result_critic import GeneratedSimulationResultCritic
from .thermal_network import build_branched_network, build_conduction_convection_network, build_layered_network, build_series_network, with_requested_outputs
from .thermal_network_solver import ThermalNetworkReferenceSolver
from .validator import ModelValidator

__all__ = [
    "ComponentRegistry", "FakeModelSynthesizer", "ModelIR", "ModelValidator",
    "RuleBasedModelSynthesizer", "SimulationBuildCapabilityProbe", "CompilationPlanner",
    "GeneratedModelArtifactStore", "GeneratedModelJanitor", "ModelCompiler",
    "SimulinkCompilerBackend",
    "GeneratedModelRepository", "GeneratedModelService",
    "GeneratedSimulationResultCritic",
    "build_series_network",
    "build_layered_network",
    "build_conduction_convection_network",
    "build_branched_network",
    "with_requested_outputs",
    "ThermalNetworkReferenceSolver",
]
