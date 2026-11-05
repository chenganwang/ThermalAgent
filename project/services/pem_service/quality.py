"""Conservative PEM observation checks; no CFD or efficiency model."""
from __future__ import annotations
import hashlib
import json
import math

QUALITY_VERSION = 'pem-quality-0.1'
UNITS = {
    'pressure': {'Pa': 1.0, 'kPa': 1000.0, 'MPa': 1000000.0},
    'mass_flow': {'kg/s': 1.0, 'g/s': 0.001, 'kg/h': 1/3600},
    'temperature': {'K': (1.0, 0.0), 'degC': (1.0, 273.15)},
}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()

def definition(study):
    return study.get('definition', study.get('request', study))

def finite(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('A finite numeric value is required')
    try:
        number = float(value)
    except OverflowError:
        raise ValueError('Numeric value exceeds the finite float range') from None
    if not math.isfinite(number):
        raise ValueError('NaN and infinity are not physical observations')
    return number

def quantity(value, unit, dimension):
    number = finite(value)
    if unit not in UNITS[dimension]:
        raise ValueError(f'Invalid {dimension} unit')
    factor = UNITS[dimension][unit]
    return number * factor[0] + factor[1] if isinstance(factor, tuple) else number * factor

def normalize_boundary(boundary):
    if not isinstance(boundary, dict):
        raise ValueError('boundary_conditions must be an object')
    normalized = {}
    for name, dim in [('mass_flow_rate','mass_flow'), ('temperature','temperature'), ('outlet_pressure','pressure')]:
        item = boundary.get(name)
        if not isinstance(item, dict) or set(item) != {'value', 'unit'}:
            raise ValueError(f'Missing or malformed boundary quantity: {name}')
        number = quantity(item['value'], item['unit'], dim)
        if (name != 'outlet_pressure' and number <= 0) or (name == 'outlet_pressure' and number < 0):
            raise ValueError('Invalid boundary magnitude')
        normalized[name] = float(format(number, '.14g'))
    normalized['additional'] = boundary.get('additional', {})
    if not isinstance(normalized['additional'], dict):
        raise ValueError('Additional conditions must be an object')
    digest(normalized)
    return normalized

def evaluate_quality(study, candidate, row):
    spec, checks, metrics = definition(study), [], {}
    def add(code, level, message, **detail):
        checks.append({'code': code, 'level': level, 'message': message, **detail})
    if candidate is None:
        add('UNKNOWN_CANDIDATE', 'error', '候选编号不属于本研究；记录保留但不能比较。')
    else:
        if row.get('geometry_version') != candidate.get('geometry_version'):
            add('GEOMETRY_VERSION_MISMATCH', 'error', '几何版本缺失或与候选不一致。')
        if not candidate.get('normalized_parameters'):
            add('CANDIDATE_PARAMETERS_MISSING', 'error', '候选没有归一化参数证据。')
    for name in ['physics_model','model_version','fluid','side']:
        if not row.get(name):
            add('MISSING_MODEL_CONTEXT','error',f'缺少 {name}。',field=name)
        elif row[name] != spec.get(name):
            add('MODEL_CONTEXT_MISMATCH','error',f'{name} 与研究设定不一致。',field=name)
    details = row.get('physical_model_details')
    if details is None:
        details = {}
    if not isinstance(details, dict):
        add('INVALID_MODEL_DETAILS','error','物理模型详情必须是对象。')
        details = {}
    if spec.get('physics_model') in {'two_phase','electrochemical'} and not details:
        add('COUPLED_MODEL_DETAILS_MISSING','error','须声明具体两相或电化学模型、相/反应与耦合条件。')
    pressure_definition = row.get('pressure_drop_definition')
    if (not isinstance(pressure_definition,dict)
        or pressure_definition.get('pressure_kind') not in ('static','total')
        or pressure_definition.get('sign_convention') != 'inlet_minus_outlet'
        or any(not isinstance(pressure_definition.get(k),str) or not pressure_definition[k].strip()
               for k in ['inlet_surface','outlet_surface','averaging'])):
        add('PRESSURE_DROP_DEFINITION_MISSING','error','须明确静压/总压、进出口取面、平均方式与入口减出口符号；不猜测指标定义。')
    boundary = None
    try:
        boundary = normalize_boundary(row.get('boundary_conditions'))
        if boundary != normalize_boundary(spec.get('boundary_conditions')):
            add('OPERATING_CONDITION_MISMATCH','error','工况与研究设定不一致，不混入同工况排序。')
        else:
            add('OPERATING_CONDITION_MATCH','pass','显式工况与研究设定一致。')
    except (ValueError, TypeError, KeyError):
        add('INVALID_BOUNDARY_CONDITIONS','error','边界缺失、单位非法或含非有限值。')
    for name, dim, metric in [('pressure_drop','pressure','pressure_drop_pa'), ('inlet_mass_flow','mass_flow','inlet_mass_flow_kg_s'), ('outlet_mass_flow','mass_flow','outlet_mass_flow_kg_s')]:
        try:
            number = quantity(row.get(name), row.get(name+'_unit'), dim)
            if number < 0 or (dim == 'mass_flow' and number == 0):
                raise ValueError('Invalid magnitude')
            metrics[metric] = number
            add('VALID_QUANTITY','pass',f'{name} 转換到 SI。',field=name)
        except (ValueError, TypeError, OverflowError):
            add('INVALID_QUANTITY','error',f'{name} 缺失、单位非法、非有限值或数值不合理。',field=name)
    policy = spec.get('quality_policy') or {}
    try:
        tolerance = finite(policy.get('mass_balance_relative_tolerance',0.01))
        if not 0 < tolerance < 1:
            raise ValueError('Invalid tolerance')
    except (ValueError, TypeError):
        tolerance = 0.01
        add('INVALID_SCREENING_POLICY','error','质量守恒初筛容差非法。')
    source_mass = 0.0
    if row.get('mass_source') is not None:
        try:
            source_mass = quantity(row['mass_source'],row.get('mass_source_unit'),'mass_flow')
        except (ValueError, TypeError):
            add('INVALID_MASS_SOURCE','error','净域质量源项必须带合法单位和有限值。')
    metrics['mass_source_kg_s'] = source_mass
    if row.get('mass_balance_scope') != 'whole_domain_all_boundaries':
        add('MASS_ACCOUNTING_SCOPE_MISSING','error','须明确包含全部边界的总质量收支，相流量不能替代全域守恒。')
    if all(k in metrics for k in ['inlet_mass_flow_kg_s','outlet_mass_flow_kg_s']):
        inlet, outlet = metrics['inlet_mass_flow_kg_s'], metrics['outlet_mass_flow_kg_s']
        expected_outlet = inlet + source_mass
        error = abs(expected_outlet-outlet)/max(abs(inlet),abs(outlet),abs(source_mass),1e-30)
        metrics['mass_balance_relative_error'] = error
        add('MASS_BALANCE','pass' if error <= tolerance and expected_outlet > 0 else 'error','显式总质量收支检查；软件容差不是专业标准。',relative_error=error,tolerance=tolerance)
        if boundary and not math.isclose(inlet,boundary['mass_flow_rate'],rel_tol=tolerance,abs_tol=1e-30):
            add('INLET_FLOW_BOUNDARY_MISMATCH','error','总入口流量与设定不一致。')
    channels = row.get('channel_mass_flows')
    try:
        if not isinstance(channels,list) or not 2 <= len(channels) <= 10000:
            raise ValueError('At least two channel observations required')
        flows = [quantity(v,row.get('channel_mass_flows_unit'),'mass_flow') for v in channels]
        if any(v < 0 for v in flows) or sum(flows) <= 0:
            raise ValueError('Negative/zero distribution')
        params = (candidate or {}).get('normalized_parameters',{})
        topology = params.get('topology', 'parallel')
        count = params.get('channel_count') if topology == 'parallel' else None
        if topology != 'parallel':
            if not isinstance(row.get('flow_surface_definition'),str) or not row['flow_surface_definition'].strip():
                add('TOPOLOGY_FLOW_SURFACES_UNSPECIFIED','error','非并联拓扑须明确互不重叠的出口分区面定义；串联段流量不能相加当成出口流量。')
            try:
                partitions = finite(row.get('flow_partition_count'))
                if not partitions.is_integer() or partitions != len(flows):
                    raise ValueError('Partition count mismatch')
            except (ValueError, TypeError):
                add('FLOW_PARTITION_COUNT_MISMATCH','error','须声明与实际出口分区观测一致的分区数量。')
        if count is not None and len(flows) != count:
            add('CHANNEL_COUNT_MISMATCH','error','分流观测数量与流道数量不一致。')
        if row.get('flow_distribution_basis') != 'total_mass_flow':
            add('FLOW_DISTRIBUTION_BASIS_MISSING','error','CV 必须声明总质量流量基准，不能混用相流量。')
        mean = sum(flows)/len(flows)
        metrics['flow_cv'] = math.sqrt(sum((v-mean)**2 for v in flows)/len(flows))/mean
        metrics['channel_mass_flows_kg_s'] = flows
        outlet = metrics.get('outlet_mass_flow_kg_s')
        if outlet is not None:
            error = abs(sum(flows)-outlet)/max(outlet,1e-30)
            add('CHANNEL_FLOW_BALANCE','pass' if error <= tolerance else 'error','分流截面总质量流量与总出口核对。',relative_error=error,tolerance=tolerance)
    except (ValueError, TypeError, OverflowError):
        add('INVALID_FLOW_DISTRIBUTION','error','分流量缺失、数量不足、单位非法、负流量或非有限值。')
    status = row.get('convergence_status')
    add('SOLVER_STATUS','pass' if status == 'converged' else 'error','收敛为导入方声明，残差另行核对。' if status == 'converged' else '算例未收敛、失败或状态缺失，原始记录保留。',reported_status=status)
    residuals, criteria = row.get('residuals'), row.get('convergence_criteria')
    try:
        if not isinstance(residuals,dict) or not isinstance(criteria,dict) or not criteria or set(criteria)-set(residuals):
            raise ValueError('Residual evidence missing')
        if any(finite(v) < 0 for v in residuals.values()):
            raise ValueError('Invalid residual')
        for name, threshold in criteria.items():
            threshold, residual = finite(threshold), finite(residuals[name])
            if threshold <= 0 or residual < 0:
                raise ValueError('Invalid residual')
            add('RESIDUAL_CRITERION','pass' if residual <= threshold else 'error','按导入方明确准则检查；不认证模型准确性。',field=name,residual=residual,threshold=threshold)
    except (ValueError, TypeError):
        add('RESIDUAL_EVIDENCE_MISSING','error','残差或明确收敛准则缺失/非法。')
    for name in ['mesh_cells','iterations']:
        try:
            number = finite(row.get(name))
            if number <= 0 or not number.is_integer():
                raise ValueError('Positive integer required')
        except (ValueError, TypeError):
            add('INVALID_SOLVER_METADATA','error',f'{name} 必须为正整数。',field=name)
    for name in ['mesh_id','solver_version']:
        if not isinstance(row.get(name),str) or not row[name].strip():
            add('MISSING_SOLVER_METADATA','error',f'缺少 {name}。',field=name)
    for name in ['mesh_min_orthogonal_quality','mesh_max_skewness']:
        try:
            number = finite(row.get(name))
            if not 0 <= number <= 1:
                raise ValueError('Mesh metric must be in [0,1]')
            if (name == 'mesh_min_orthogonal_quality' and number == 0) or (name == 'mesh_max_skewness' and number == 1):
                add('DEGENERATE_MESH','error','网格质量达到退化极值。',field=name)
        except (ValueError, TypeError):
            add('MISSING_MESH_QUALITY','error',f'{name} 缺失、非有限值或越界。',field=name)
    add('MESH_INDEPENDENCE_NOT_VERIFIED','warning','未核验独立网格加密对照，质量值不证明网格无关性。')
    add('PROVENANCE_DECLARED','warning','来源由导入方声明，哈希证明追溯性，不认证真实求解。')
    for key, value in list(metrics.items()):
        if isinstance(value, (int, float)) and not math.isfinite(value):
            metrics[key] = None
            add('NUMERIC_OVERFLOW','error','观测计算超出有限浮点范围，不能用于比较。',field=key)
    errors = [c for c in checks if c['level']=='error']
    return {'version':QUALITY_VERSION,'status':'invalid' if errors else 'screened','eligible_for_comparison':not errors,
            'checks':checks,'metrics':metrics,'mass_balance_relative_tolerance':tolerance,
            'limitations':['只针对已导入压降和总流量分布观测。','不能由单相流结果推断电解效率。','残差、网格和模型真实性仍需专业验证。']}
