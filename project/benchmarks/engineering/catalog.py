"""Versioned cases: explicit inputs, expected workflow and numerical tolerances.

Expected numerical values are NOT stored or supplied to the Agent. The independent
oracle derives them from these reviewed SI inputs after execution.
"""
from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

DATASET_VERSION = "engineering-benchmark-v1"
FIXTURE_DOC_ID, FIXTURE_CHUNK_ID = 990101, 990201
FIXTURE_TITLE = "BENCHMARK FIXTURE — steady thermal and hydraulic model notes"
FIXTURE_TEXT = (
    "BENCHMARK FIXTURE，非生产知识库、非实验测量。稳态液冷控制体满足 Q=m_dot*cp*deltaT。"
    "管路采用 Darcy–Weisbach 压降，层流 f=64/Re，光滑管湍流使用 Blasius 近似。"
    "一维平壁导热 Q=k*A*deltaT/L，串联多层等效热阻为各层 L/(k*A) 之和。"
    "上述理想模型不覆盖局部热点、复杂CFD、瞬态、接触热阻或温度相关物性。"
)


class VariableExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    unit: str
    oracle_key: str
    step_id: str | None = None
    absolute_tolerance: float = Field(default=1e-6, ge=0, allow_inf_nan=False)
    relative_tolerance: float = Field(default=1e-5, ge=0, le=.01, allow_inf_nan=False)


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(pattern=r"^[A-Z]{2}-\d{3}$")
    title: str
    purpose: str
    request: dict
    knowledge: Literal["fixture", "empty"] = "fixture"
    oracle: Literal["liquid", "plane_wall", "layered_wall", "none"]
    oracle_inputs: dict = Field(default_factory=dict)
    expected_status: Literal["completed", "blocked", "incomplete"]
    expected_steps: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    expected_dependencies: list[tuple[str, str]] = Field(default_factory=list)
    variables: list[VariableExpectation] = Field(default_factory=list)
    physics_required: bool = True
    source_required: bool = True
    report_required: bool = True
    missing_parameters: list[str] = Field(default_factory=list)
    design_status: Literal["passed", "violated", "unavailable"] | None = None

    @model_validator(mode="after")
    def coherent_case(self):
        if self.knowledge == "empty" and self.source_required:
            raise ValueError("An empty fixture cannot require citation evidence")
        if self.variables and self.oracle == "none":
            raise ValueError("Numerical expectations need an independent oracle")
        if len(self.expected_steps) != len(set(self.expected_steps)):
            raise ValueError("Repeated expected step")
        return self


LIQUID_INPUTS = dict(heat_load_w=1000., coolant_delta_t_k=5., specific_heat_j_kgk=4180.,
                    density_kg_m3=997., dynamic_viscosity_pa_s=.001, hydraulic_diameter_m=.01,
                    length_m=2., minor_loss_coefficient=2.)
LIQUID_STEPS = ["structure_inputs", "retrieval", "flow", "pressure", "validation", "report"]
REFERENCE_STEPS = ["structure_inputs", "retrieval", "calculation", "validation", "report"]
LIQUID_TOOLS = ["liquid_flow_rate_required", "liquid_pressure_drop_estimate"]
LIQUID_VARIABLES = [dict(name=name, oracle_key=name, unit=unit, step_id=step)
                     for name, unit, step in [("mass_flow_kg_s", "kg/s", "flow"),
                         ("volume_flow_L_min", "L/min", "flow"), ("velocity_m_s", "m/s", "pressure"),
                         ("reynolds_number", "1", "pressure"), ("pressure_drop_pa", "Pa", "pressure")]]
LAYERS = dict(area_m2=.01, left_temperature_k=350., right_temperature_k=300., cells_per_layer=2,
              layers=[dict(thickness_m=.002, conductivity_w_mk=200.), dict(thickness_m=.003, conductivity_w_mk=1.)])


def load_cases():
    """Return a fresh, validated catalog; callers cannot mutate the frozen inputs."""
    def liquid(case_id, title, inputs=None, **changes):
        inputs = deepcopy(inputs or LIQUID_INPUTS)
        item = dict(case_id=case_id, title=title, purpose=title,
                    request={"query": "分析服务器液冷方案，计算流量、压降并验证，生成工程报告。", "liquid_cooling": inputs,
                             "requested_outputs": ["report"]}, oracle="liquid", oracle_inputs=deepcopy(inputs),
                    expected_status="completed", expected_steps=LIQUID_STEPS, expected_tools=LIQUID_TOOLS,
                    expected_dependencies=[("flow", "pressure"), ("validation", "report")], variables=LIQUID_VARIABLES)
        item.update(changes)
        return item

    def reference(case_id, title, inputs=None, **changes):
        inputs = deepcopy(inputs or LAYERS)
        item = dict(case_id=case_id, title=title, purpose=title,
                    request={"query": "评估多层导热设计，检索依据、计算热阻和边界热流、验证并生成报告。",
                             "reference_solver": inputs, "requested_outputs": ["report"]},
                    oracle="layered_wall", oracle_inputs=deepcopy(inputs), expected_status="completed",
                    expected_steps=REFERENCE_STEPS, expected_tools=["reference_layered_wall_solve"],
                    expected_dependencies=[("retrieval", "calculation"), ("validation", "report")],
                    variables=[dict(name=name, oracle_key=name, unit=unit, relative_tolerance=1e-8, absolute_tolerance=1e-8)
                               for name, unit in [("heat_rate", "W"), ("equivalent_resistance", "K/W")]])
        item.update(changes)
        return item

    natural = liquid("LC-002", "自然单位解析：2kW、10K与10mm管径", {**LIQUID_INPUTS, "heat_load_w": 2000., "coolant_delta_t_k": 10., "minor_loss_coefficient": 0.})
    natural["request"] = {"query": "分析服务器液冷方案：功率2kW，允许温升10K，比热4180J/(kg·K)，密度997kg/m³，动力黏度0.001Pa·s，管径10mm，管长2m，计算流量压降并生成报告。", "requested_outputs": ["report"]}
    blocked = liquid("LC-004", "缺失工程输入必须阻断计算", expected_status="blocked", oracle="none", oracle_inputs={},
                     expected_tools=[], variables=[], physics_required=False,
                     missing_parameters=["heat_load_w", "coolant_delta_t_k", "specific_heat_j_kgk", "density_kg_m3", "dynamic_viscosity_pa_s", "hydraulic_diameter_m", "length_m"])
    blocked["request"] = {"query": "请分析液冷方案并计算流量和压降", "requested_outputs": ["report"]}
    constrained = liquid("DS-001", "物理计算正确，但100Pa压降指标必须判为未满足", expected_status="incomplete", design_status="violated",
                         expected_steps=[*LIQUID_STEPS[:-1], "design_review", "report"], expected_dependencies=[("flow", "pressure"), ("design_review", "report")],
                         expected_tools=[*LIQUID_TOOLS, "explicit_design_limits"])
    constrained["request"]["design_criteria"] = {"max_pressure_drop_pa": 100.}
    data = [liquid("LC-001", "显式SI液冷湍流：能量到压降的真实依赖链"), natural,
            liquid("LC-003", "低热负荷层流：验证64/Re模型分支与舍入容差", {**LIQUID_INPUTS, "heat_load_w": 100., "coolant_delta_t_k": 10., "length_m": 1.5, "minor_loss_coefficient": 1.5}),
            blocked, liquid("LC-005", "无知识来源时保留计算但不宣布工程证据完整", knowledge="empty", source_required=False, expected_status="incomplete"),
            dict(case_id="HT-001", title="自然语言平壁：384W热流、热流密度和热阻", purpose="验证原Agent选工具与Fourier结果，不绕过原问答流程",
                 request={"query": "壁厚5mm，导热系数16W/(mK)，面积0.002m²，两侧温差60K，计算平壁导热热流并生成报告。", "requested_outputs": ["report"]},
                 oracle="plane_wall", oracle_inputs={"thickness_m": .005, "conductivity_w_mk": 16., "area_m2": .002, "delta_t_k": 60.},
                 expected_status="completed", expected_steps=["structure_inputs", "calculation", "validation", "retrieval", "report"], expected_tools=["plane_wall_conduction"],
                 expected_dependencies=[("calculation", "validation")], variables=[dict(name=name, oracle_key=name, unit=unit) for name, unit in [("heat_rate_W", "W"), ("heat_flux_W_m2", "W/m2"), ("R_cond_K_per_W", "K/W")]]),
            reference("HT-002", "双层壁：独立串联解析解与真实节点求解器对照"),
            reference("HT-003", "逆向导热：负热流不是非法绝对温度", {**LAYERS, "left_temperature_k": 300., "right_temperature_k": 350.}), constrained]
    cases = [BenchmarkCase.model_validate(deepcopy(item)) for item in data]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Case identifiers must be unique")
    return cases
