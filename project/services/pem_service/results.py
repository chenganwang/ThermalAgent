"""Traceable CSV/JSON import retaining failed and malformed individual cases."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
from uuid import uuid4
from .quality import evaluate_quality, digest

IMPORT_VERSION = 'pem-import-0.1'
PROVENANCE = {'real_fluent','manual','fluent_export','manual_import','synthetic_demo'}
STRUCTURED = {'boundary_conditions','physical_model_details','pressure_drop_definition','channel_mass_flows','residuals','convergence_criteria'}
FIELDS = {'candidate_id','geometry_version','physics_model','model_version','fluid','side','boundary_conditions','physical_model_details',
    'pressure_drop','pressure_drop_unit','inlet_mass_flow','inlet_mass_flow_unit','outlet_mass_flow','outlet_mass_flow_unit',
    'mass_source','mass_source_unit','mass_balance_scope','channel_mass_flows','channel_mass_flows_unit','flow_distribution_basis',
    'mesh_cells','mesh_id','mesh_min_orthogonal_quality','mesh_max_skewness','convergence_status','iterations','residuals','convergence_criteria','solver_version',
    'flow_surface_definition','flow_partition_count','pressure_drop_definition'}

def safe_data(value):
    if isinstance(value,float) and not math.isfinite(value):
        return {'__nonfinite__':repr(value)}
    if isinstance(value,dict):
        return {str(k):safe_data(v) for k,v in value.items()}
    if isinstance(value,list):
        return [safe_data(v) for v in value]
    return value

def nonfinite_paths(value,path='row'):
    if isinstance(value,float) and not math.isfinite(value):
        return [path]
    if isinstance(value,dict):
        return [p for k,v in value.items() for p in nonfinite_paths(v,path+'.'+str(k))]
    if isinstance(value,list):
        return [p for i,v in enumerate(value) for p in nonfinite_paths(v,path+f'[{i}]')]
    return []

def unique_object(pairs):
    obj = {}
    for key,value in pairs:
        if key in obj:
            raise ValueError('Duplicate JSON keys are ambiguous evidence')
        obj[key] = value
    return obj

def bounded_tree(value):
    pending, visited = [(value,0)], 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 500000:
            raise ValueError('JSON structure exceeds nesting or node limits')
        if isinstance(item,str):
            try:
                item.encode('utf-8')
            except UnicodeEncodeError:
                raise ValueError('JSON strings must be valid UTF-8 Unicode') from None
        if isinstance(item,dict):
            for key in item:
                try:
                    key.encode('utf-8')
                except UnicodeEncodeError:
                    raise ValueError('JSON keys must be valid UTF-8 Unicode') from None
            pending.extend((v,depth+1) for v in item.values())
        elif isinstance(item,list):
            pending.extend((v,depth+1) for v in item)

def parse_json(text):
    try:
        value = json.loads(text,object_pairs_hook=unique_object)
        bounded_tree(value)
        return value
    except RecursionError:
        raise ValueError('JSON structure exceeds nesting limits') from None

def bounded_filename(filename):
    if (not isinstance(filename,str) or not filename.strip() or len(filename)>200
        or PureWindowsPath(filename).name != filename or PurePosixPath(filename).name != filename
        or any(ord(c)<32 for c in filename) or filename in {'.','..'}):
        raise ValueError('filename must be a plain filename without paths')
    return filename

def import_results(study,candidates,content,format,filename,provenance,field_map=None):
    if format not in {'csv','json'} or provenance not in PROVENANCE:
        raise ValueError('Unsupported format or provenance')
    provenance = {'real_fluent':'fluent_export','manual':'manual_import'}.get(provenance,provenance)
    filename = bounded_filename(filename)
    if not isinstance(content,str) or not content.strip() or len(content.encode('utf-8'))>5000000:
        raise ValueError('Import content must be nonempty and at most 5 MB')
    mapping = field_map or {}
    if not isinstance(mapping,dict) or set(mapping)-FIELDS or any(not isinstance(v,str) or not v for v in mapping.values()):
        raise ValueError('field_map maps canonical fields to source columns')
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('A source field cannot be mapped multiple times')
    if format == 'json':
        try:
            data = parse_json(content.lstrip('\ufeff'))
        except (ValueError,RecursionError):
            raise ValueError('Invalid JSON document') from None
        rows = data.get('records') if isinstance(data,dict) else data
        if not isinstance(rows,list):
            raise ValueError('JSON must be a row array or records object')
    else:
        reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')),strict=True)
        try:
            headers = reader.fieldnames
        except csv.Error:
            raise ValueError('Invalid CSV header') from None
        if not headers or len(headers)!=len(set(headers)) or len(headers)>100:
            raise ValueError('CSV requires distinct headers and at most 100 columns')
        try:
            rows = list(reader)
        except csv.Error:
            raise ValueError('Invalid CSV document') from None
    if not 1 <= len(rows) <= 2000:
        raise ValueError('Imports must contain 1 to 2000 rows')
    if provenance != 'synthetic_demo':
        for raw in rows:
            if isinstance(raw,dict):
                marked = raw.get('provenance') == 'synthetic_demo' or any(
                    'synthetic' in str(raw.get(mapping.get(k,k), '')).lower()
                    for k in ('solver_version','mesh_id'))
                if marked:
                    raise ValueError('Explicit synthetic fixture must be imported as synthetic_demo')
    source = {'filename':filename,'sha256':hashlib.sha256(content.encode('utf-8')).hexdigest(),'encoding':'utf-8','format':format,
        'provenance':provenance,'provenance_verified':False,'field_map':mapping,'import_version':IMPORT_VERSION,'at_utc':datetime.now(timezone.utc).isoformat()}
    by_id, records = {c['candidate_id']:c for c in candidates}, []
    for index,raw in enumerate(rows,1):
        errors = []
        if nonfinite_paths(raw):
            errors.append({'code':'NONFINITE_RAW_DATA','level':'error','message':'原始行含 NaN/Infinity，内容保留并排除比较。'})
        if not isinstance(raw,dict):
            row = {}
            errors.append({'code':'INVALID_ROW','level':'error','message':'此行不是对象，原数据保留。'})
        else:
            row = {name:raw.get(mapping.get(name,name)) for name in FIELDS}
            for name in STRUCTURED:
                if isinstance(row.get(name),str) and row[name].strip():
                    try:
                        row[name] = parse_json(row[name])
                    except (ValueError,RecursionError):
                        errors.append({'code':'INVALID_STRUCTURED_FIELD','level':'error','field':name,'message':'结构化单元格须为合法 JSON。'})
            if nonfinite_paths(row):
                errors.append({'code':'NONFINITE_MAPPED_DATA','level':'error','message':'映射后观测含非有限值。'})
            if None in raw:
                errors.append({'code':'CSV_COLUMN_COUNT_MISMATCH','level':'error','message':'CSV 行列数超出表头。'})
        cid = row.get('candidate_id')
        candidate = by_id.get(cid) if isinstance(cid,str) else None
        quality = evaluate_quality(study,candidate,row)
        quality['checks'] = errors + quality['checks']
        if errors:
            quality.update(status='invalid',eligible_for_comparison=False)
        quality = safe_data(quality)
        raw_safe, row_safe = safe_data(raw), safe_data(row)
        records.append({'result_id':'pem_result_'+uuid4().hex,'candidate_id':cid if isinstance(cid,str) else None,
            'geometry_version':row_safe.get('geometry_version'),'record_version':IMPORT_VERSION,'provenance':provenance,
            'source':{**source,'row_number':index},'raw':raw_safe,'raw_row_sha256':digest(raw_safe),'observation':row_safe,
            'quality':quality,'candidate_snapshot':candidate,'at_utc':source['at_utc']})
    warnings = ['来源标签由导入者声明，须与 case/data/求解日志核对。']
    if provenance=='synthetic_demo':
        warnings.append('合成演示观测不能作为科研结果或真实性能验收。')
    return {'records':records,'source':source,'warnings':warnings,'import_version':IMPORT_VERSION,
        'counts':{'total':len(records),'screened':sum(r['quality']['eligible_for_comparison'] for r in records),'invalid':sum(not r['quality']['eligible_for_comparison'] for r in records)}}
