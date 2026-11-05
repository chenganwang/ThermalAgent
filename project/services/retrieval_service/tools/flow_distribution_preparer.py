from __future__ import annotations
from typing import Any
from .hydraulic_network_calculators import calculate_network_flow_distribution, json_safe_network, validate_network_inputs

def _check(item_id:str,name:str,status:str,detail:str,required:bool)->dict[str,Any]:
    return {"item_id":item_id,"name":name,"status":status,"detail":detail,"required":required}

def prepare_flow_distribution(network:dict[str,Any]|None)->dict[str,Any]:
    try:
        validate_network_inputs(network or {})
    except (ValueError, TypeError, ArithmeticError):
        return {"generated":True,"status":"failed","topology":"unknown","known_inputs":json_safe_network(network or {}),
            "missing_inputs":[],"checklist":[],"calculation_ready":False,"result":{},"warnings":[],
            "not_run_reason":"Invalid or conflicting hydraulic inputs; no network calculation was executed.","cfd_executed":False}
    data=dict(network or {})
    topology=str(data.get("topology") or "unknown")
    branches=list(data.get("branches") or [])
    components=list(data.get("components") or [])
    assumptions=list(data.get("assumptions") or [])
    has_flow=data.get("total_flow_rate_lpm") is not None or data.get("total_flow_rate_m3_s") is not None
    explicit_identical="identical_branches_explicit" in assumptions
    has_resistance=bool(branches) and all(b.get("resistance_coefficient") is not None for b in branches)
    has_series_dp=bool(components or branches) and all(x.get("pressure_drop_pa") is not None for x in (components or branches))
    missing=[]
    if topology=="unknown": missing.append("topology")
    if topology=="parallel" and not has_flow: missing.append("total_flow_rate")
    if topology=="parallel" and not has_resistance and not explicit_identical: missing.append("branch_resistance_or_identical_assumption")
    if topology=="series" and not has_series_dp and not has_flow: missing.append("pressure_drop_or_resistance_and_total_flow")
    checklist=[
        _check("topology","Network topology","ok" if topology!="unknown" else "missing",topology,True),
        _check("total_flow","Total flow rate","ok" if has_flow else ("not_applicable" if topology=="series" and has_series_dp else "missing"),"Provided." if has_flow else "Not provided.",topology=="parallel"),
        _check("branch_count","Branch/component count","ok" if branches or components else "missing",str(len(branches or components)),True),
        _check("branch_resistance","Branch resistance","ok" if has_resistance else "missing","Provided." if has_resistance else "No resistance values inferred.",topology=="parallel" and not explicit_identical),
        _check("resistance_exponent","Resistance exponent","ok" if has_resistance and all(b.get("resistance_exponent") is not None for b in branches) else "missing","Required with resistance model.",has_resistance),
        _check("identical_assumption","Identical branches","ok" if explicit_identical else "not_applicable","Explicit only; never inferred.",False),
        _check("geometry","Branch geometry","warning","Not inferred by this preparer.",False),
        _check("minor_losses","Minor-loss coefficients","warning","No K values are inferred.",False),
        _check("coolant_properties","Coolant properties","not_applicable","Required only for geometry-based resistance calculations not performed here.",False),
        _check("pressure_or_head","Pressure drop or pump head","ok" if has_series_dp else "warning","Useful for validation.",False),
        _check("validation","Measurement or CFD validation","warning","Recommended after the one-dimensional estimate.",False),
        _check("manifold","Manifold distribution","warning","Not modeled or inferred.",False),
    ]
    result=None
    if not missing:
        calculated=calculate_network_flow_distribution(data)
        result=calculated.to_dict()
        status="estimated" if calculated.status=="success" else calculated.status
        missing=list(calculated.missing_parameters)
    else: status="missing_params"
    return {"generated":True,"status":status,"topology":topology,"known_inputs":{k:v for k,v in data.items() if v is not None},
        "missing_inputs":missing,"checklist":checklist,"calculation_ready":status=="estimated","result":result or {},
        "warnings":list((result or {}).get("warnings") or []),"not_run_reason":None if status=="estimated" else "Required network inputs are missing or unsupported.","cfd_executed":False}

__all__=["prepare_flow_distribution"]
