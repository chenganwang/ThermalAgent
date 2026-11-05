"""Independent numeric/provenance regression for the PEM import and comparison path."""
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.pem_service.results import import_results
from services.pem_service.comparison import compare_results
from services.pem_service.report import build_report


def fixtures():
    study = {'study_id':'pem_study_test','study_version':1,'definition':{
        'title':'Explicit synthetic demonstration','objective':'Software regression only',
        'side':'anode','physics_model':'single_phase','model_version':'laminar-demo-v1','fluid':'water',
        'boundary_conditions':{'mass_flow_rate':{'value':0.004,'unit':'kg/s'},'temperature':{'value':298.15,'unit':'K'},'outlet_pressure':{'value':101325,'unit':'Pa'}},
        'quality_policy':{'mass_balance_relative_tolerance':0.01},'parameter_space':[
            {'name':'channel_width','kind':'continuous','unit':'mm','lower':0.8,'upper':1.2,'source':'explicit demo range, no manufacturing claim'}]}}
    candidates = [{'candidate_id':'candidate_A','geometry_version':'geom_a', 'normalized_parameters':{'channel_count':4,'plate_width':0.02,'plate_length':0.05}},
                  {'candidate_id':'candidate_B','geometry_version':'geom_b', 'normalized_parameters':{'channel_count':4,'plate_width':0.02,'plate_length':0.05}},
                  {'candidate_id':'candidate_C','geometry_version':'geom_c', 'normalized_parameters':{'channel_count':4,'plate_width':0.02,'plate_length':0.05}}]
    row = {'candidate_id':'candidate_A','geometry_version':'geom_a','side':'anode','physics_model':'single_phase',
        'model_version':'laminar-demo-v1','fluid':'water','boundary_conditions':deepcopy(study['definition']['boundary_conditions']),
        'physical_model_details':{'flow_model':'laminar','steady':True}, 'pressure_drop':100,'pressure_drop_unit':'Pa',
        'pressure_drop_definition':{'pressure_kind':'static','inlet_surface':'inlet','outlet_surface':'outlet','averaging':'area_weighted_mean','sign_convention':'inlet_minus_outlet'},
        'inlet_mass_flow':0.004,'inlet_mass_flow_unit':'kg/s','outlet_mass_flow':0.004,'outlet_mass_flow_unit':'kg/s',
        'channel_mass_flows':[0.001]*4,'channel_mass_flows_unit':'kg/s','mass_balance_scope':'whole_domain_all_boundaries',
        'flow_distribution_basis':'total_mass_flow','mesh_id':'demo_mesh_1','mesh_cells':10000,
        'mesh_min_orthogonal_quality':0.5,'mesh_max_skewness':0.5,'convergence_status':'converged','iterations':100,
        'residuals':{'continuity':1e-6,'velocity':1e-7}, 'convergence_criteria':{'continuity':1e-4,'velocity':1e-4}, 'solver_version':'external-schema-fixture-v1'}
    return study,candidates,row


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.study,self.candidates,self.row=fixtures()
    def imported(self,rows=None,provenance='synthetic_demo',**kwargs):
        return import_results(self.study,self.candidates,json.dumps(rows or [self.row]),'json','fixture.json',provenance,**kwargs)
    def errors(self,record):
        return {c['code'] for c in record['quality']['checks'] if c['level']=='error'}
    def test_observed_cv_and_mass_balance_independent_oracle(self):
        self.row['channel_mass_flows']=[0.0005,0.0015,0.0005,0.0015]
        r=self.imported()['records'][0]
        self.assertTrue(r['quality']['eligible_for_comparison'])
        self.assertAlmostEqual(r['quality']['metrics']['flow_cv'],0.5)
        self.assertEqual(r['quality']['metrics']['mass_balance_relative_error'],0)
    def test_exact_file_and_row_hash_trace(self):
        content=json.dumps([self.row])
        imported=import_results(self.study,self.candidates,content,'json','fixture.json','manual')
        r=imported['records'][0]
        self.assertEqual(r['source']['sha256'],hashlib.sha256(content.encode()).hexdigest())
        self.assertEqual(r['source']['row_number'],1)
        self.assertEqual(r['raw'],self.row)
        self.assertFalse(r['source']['provenance_verified'])
    def test_csv_mapping_structured_cells_and_equivalent_units(self):
        row=deepcopy(self.row)
        row['dp_export']=0.1
        del row['pressure_drop']
        row['pressure_drop_unit']='kPa'
        row['boundary_conditions']['temperature']={'value':25,'unit':'degC'}
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=list(row));writer.writeheader()
        writer.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
        imported=import_results(self.study,self.candidates,output.getvalue(),'csv','fluent.csv','real_fluent',{'pressure_drop':'dp_export'})
        r=imported['records'][0]
        self.assertTrue(r['quality']['eligible_for_comparison'],r['quality']['checks'])
        self.assertEqual(r['quality']['metrics']['pressure_drop_pa'],100)
    def test_nonfinite_and_failure_remain_traceable_and_json_safe(self):
        self.row['pressure_drop']=float('nan')
        self.row['convergence_status']='failed'
        r=self.imported()['records'][0]
        json.dumps(r,allow_nan=False)
        self.assertIn('NONFINITE_RAW_DATA',self.errors(r))
        self.assertIn('SOLVER_STATUS',self.errors(r))
        self.assertEqual(r['raw']['pressure_drop']['__nonfinite__'],'nan')
    def test_bad_row_mixed_import_preserved(self):
        data=self.imported([self.row,'failed input row',{}])
        self.assertEqual(data['counts'],{'total':3,'screened':1,'invalid':2})
        self.assertEqual(data['records'][1]['raw'],'failed input row')
    def test_invalid_units_missing_metrics_and_geometry_binding(self):
        for change,code in [({'pressure_drop_unit':'psi'},'INVALID_QUANTITY'),({'geometry_version':'stale'},'GEOMETRY_VERSION_MISMATCH'),({'candidate_id':'another_study'},'UNKNOWN_CANDIDATE'),({'pressure_drop':None},'INVALID_QUANTITY'),({'channel_mass_flows':[0.004]},'INVALID_FLOW_DISTRIBUTION')]:
            with self.subTest(change=change):
                row={**self.row,**change};r=self.imported([row])['records'][0]
                self.assertIn(code,self.errors(r));self.assertFalse(r['quality']['eligible_for_comparison'])
    def test_inlet_outlet_and_channel_conservation(self):
        self.row['outlet_mass_flow']=0.003
        r=self.imported()['records'][0]
        self.assertIn('MASS_BALANCE',self.errors(r))
        self.assertIn('CHANNEL_FLOW_BALANCE',self.errors(r))
        self.assertAlmostEqual(r['quality']['metrics']['mass_balance_relative_error'],0.25)
    def test_unconverged_bad_residual_mesh_and_reverse_flow(self):
        for change,code in [({'convergence_status':'unconverged'},'SOLVER_STATUS'),({'residuals':{'continuity':0.1,'velocity':0.1}},'RESIDUAL_CRITERION'),({'mesh_cells':1.5},'INVALID_SOLVER_METADATA'),({'mesh_max_skewness':1.5},'MISSING_MESH_QUALITY'),({'channel_mass_flows':[-0.001,0.001,0.002,0.002]},'INVALID_FLOW_DISTRIBUTION')]:
            r=self.imported([{**self.row,**change}])['records'][0]
            self.assertIn(code,self.errors(r))
    def test_different_conditions_and_models_excluded_from_ranking(self):
        second=deepcopy(self.row);second['boundary_conditions']['temperature']['value']=333.15
        third={**self.row,'physics_model':'two_phase'}
        rows=self.imported([self.row,second,third])['records']
        comparison=compare_results(self.study,rows)
        self.assertEqual(len(comparison['groups']),1)
        self.assertEqual(comparison['groups'][0]['sample_count'],1)
        self.assertEqual(len(comparison['excluded']),2)
        self.assertFalse(comparison['cross_group_ranking_allowed'])
    def test_phase_and_mass_scope_not_assumed(self):
        r=self.imported([{**self.row,'mass_balance_scope':None,'flow_distribution_basis':'oxygen_mass_flow'}])['records'][0]
        self.assertIn('MASS_ACCOUNTING_SCOPE_MISSING',self.errors(r))
        self.assertIn('FLOW_DISTRIBUTION_BASIS_MISSING',self.errors(r))
    def test_two_phase_and_electrochemical_context_retained(self):
        for model in ['two_phase','electrochemical']:
            self.study['definition']['physics_model']=model
            self.row['physics_model']=model
            self.row['physical_model_details']={}
            self.assertIn('COUPLED_MODEL_DETAILS_MISSING',self.errors(self.imported()['records'][0]))
            self.row['physical_model_details']={'model':'explicit professional model pending verification'}
            self.assertTrue(self.imported()['records'][0]['quality']['eligible_for_comparison'])
    def test_source_types_and_model_details_grouped_separately(self):
        a=self.imported(provenance='real_fluent')['records']
        b=self.imported(provenance='manual')['records']
        self.row['physical_model_details']={'flow_model':'turbulent'}
        c=self.imported(provenance='real_fluent')['records']
        result=compare_results(self.study,a+b+c)
        self.assertEqual(len(result['groups']),3)
        self.assertTrue(all(g['sample_count']==1 for g in result['groups']))
    def test_non_dominance_tradeoff_and_dominated_observation(self):
        a=deepcopy(self.row);a['channel_mass_flows']=[0.0005,0.0015,0.0005,0.0015]
        b={**deepcopy(self.row),'candidate_id':'candidate_B','geometry_version':'geom_b','pressure_drop':200}
        c={**deepcopy(a),'candidate_id':'candidate_C','geometry_version':'geom_c','pressure_drop':300}
        rows=self.imported([a,b,c])['records']
        result=compare_results(self.study,rows)
        self.assertEqual(set(result['groups'][0]['pareto_result_ids']),{rows[0]['result_id'],rows[1]['result_id']})
        self.assertFalse(result['selection_basis']['prediction_used'])
    def test_no_prediction_without_observations(self):
        result=compare_results(self.study,[])
        self.assertEqual(result['groups'],[])
        report=build_report(self.study,self.candidates,[],result)
        self.assertIn('当前没有符合比较条件',report)
        self.assertIn('尚有 3 个候选',report)
    def test_report_evidence_limits_and_synthetic_label(self):
        rows=self.imported()['records']
        report=build_report(self.study,self.candidates,rows,compare_results(self.study,rows))
        for marker in ['synthetic_demo',rows[0]['source']['sha256'],'geom_a','不能推断电解效率','参数来源','未自动设定','网格无关性']:
            self.assertIn(marker,report)
    def test_filename_mapping_document_rejections(self):
        for file in ['../secret.env','C:\\private.json','dir/results.csv','..']:
            with self.assertRaises(ValueError):
                import_results(self.study,self.candidates,'[]','json',file,'manual')
        with self.assertRaises(ValueError):self.imported(field_map={'madeup':'dp'})
        with self.assertRaises(ValueError):self.imported(field_map={'pressure_drop':'x','geometry_version':'x'})
        with self.assertRaises(ValueError):import_results(self.study,self.candidates,'a,a\n1,2','csv','bad.csv','manual')
        with self.assertRaises(ValueError):import_results(self.study,self.candidates,'{}','json','bad.json','manual')
    def test_selected_results_owned_and_distinct(self):
        rows=self.imported()['records']
        with self.assertRaises(ValueError):compare_results(self.study,rows,['foreign'])
        with self.assertRaises(ValueError):compare_results(self.study,rows,[rows[0]['result_id']]*2)
    def test_nonfinite_nested_unmapped_data_not_ignored(self):
        self.row['unmapped']={'value':float('inf')}
        r=self.imported()['records'][0]
        self.assertIn('NONFINITE_RAW_DATA',self.errors(r))
        json.dumps(r,allow_nan=False)
    def test_extreme_finite_values_fail_without_invalid_json(self):
        self.row.update(inlet_mass_flow=1e308,outlet_mass_flow=1e308,channel_mass_flows=[1e308]*4,mass_source=1e308,mass_source_unit='kg/s')
        r=self.imported()['records'][0]
        self.assertFalse(r['quality']['eligible_for_comparison'])
        json.dumps(r,allow_nan=False)
    def test_serial_topology_requires_disjoint_flow_surface_definition(self):
        self.candidates[0]['normalized_parameters']['topology']='serpentine'
        self.candidates[0]['normalized_parameters']['channel_count']=10
        r=self.imported()['records'][0]
        self.assertIn('TOPOLOGY_FLOW_SURFACES_UNSPECIFIED',self.errors(r))
        self.row.update(flow_surface_definition='four disjoint equal-area outlet patches',flow_partition_count=4)
        self.assertTrue(self.imported()['records'][0]['quality']['eligible_for_comparison'])
    def test_explicit_synthetic_observation_cannot_be_mislabeled(self):
        self.row['solver_version']='synthetic-fixture-no-Fluent-solver'
        with self.assertRaises(ValueError):self.imported(provenance='fluent_export')
        with self.assertRaises(ValueError):self.imported(provenance='manual_import')
        self.assertEqual(self.imported()['records'][0]['provenance'],'synthetic_demo')
    def test_utf8_bom_and_newlines_retained_in_hash(self):
        content='\ufeff'+json.dumps([self.row],ensure_ascii=False,indent=2).replace('\n','\r\n')
        result=import_results(self.study,self.candidates,content,'json','bom.json','synthetic_demo')
        self.assertTrue(result['records'][0]['quality']['eligible_for_comparison'])
        self.assertEqual(result['source']['sha256'],hashlib.sha256(content.encode('utf-8')).hexdigest())
    def test_extreme_integer_metadata_retained_per_row(self):
        for field in ['mass_source','mesh_cells','iterations']:
            row={**self.row,field:10**400}
            r=self.imported([row])['records'][0]
            self.assertFalse(r['quality']['eligible_for_comparison'])
            json.dumps(r,allow_nan=False)
        row=deepcopy(self.row);row['boundary_conditions']['temperature']['value']=10**400
        self.assertFalse(self.imported([row])['records'][0]['quality']['eligible_for_comparison'])
        row={**self.row,'residuals':{'continuity':10**400,'velocity':1e-6}}
        self.assertFalse(self.imported([row])['records'][0]['quality']['eligible_for_comparison'])
    def test_malformed_csv_header_is_a_document_rejection(self):
        with self.assertRaises(ValueError):
            import_results(self.study,self.candidates,'"unterminated\n1,2','csv','bad.csv','manual_import')
    def test_ambiguous_duplicate_keys_and_deep_json_rejected(self):
        with self.assertRaises(ValueError):
            import_results(self.study,self.candidates,'[{"convergence_status":"failed","convergence_status":"converged"}]','json','ambiguous.json','manual_import')
        nested={}
        for _ in range(600):nested={'nested':nested}
        row={**self.row,'extra':nested}
        with self.assertRaises(ValueError):self.imported([row])
    def test_wrong_model_details_type_never_defaulted_to_object(self):
        for value in [[], '', 0]:
            r=self.imported([{**self.row,'physical_model_details':value}])['records'][0]
            self.assertIn('INVALID_MODEL_DETAILS',self.errors(r))
    def test_equivalent_mass_source_units_form_one_si_group(self):
        a={**self.row,'mass_source':0.001,'mass_source_unit':'kg/s','outlet_mass_flow':0.005,'channel_mass_flows':[0.00125]*4}
        b={**a,'mass_source':1,'mass_source_unit':'g/s'}
        comparison=compare_results(self.study,self.imported([a,b])['records'])
        self.assertEqual(len(comparison['groups']),1)
        self.assertEqual(comparison['groups'][0]['context']['mass_source_kg_s'],0.001)
    def test_unpaired_unicode_rejected_before_storage(self):
        with self.assertRaises(ValueError):
            import_results(self.study,self.candidates,'[{"extra":"\\ud800"}]','json','invalid.json','manual_import')
    def test_pressure_metric_definitions_missing_or_different_not_mixed(self):
        missing={**self.row,'pressure_drop_definition':None}
        r=self.imported([missing])['records'][0]
        self.assertIn('PRESSURE_DROP_DEFINITION_MISSING',self.errors(r))
        total=deepcopy(self.row);total['pressure_drop_definition']['pressure_kind']='total'
        comparison=compare_results(self.study,self.imported([self.row,total])['records'])
        self.assertEqual(len(comparison['groups']),2)
        bad=deepcopy(self.row);bad['pressure_drop_definition']['pressure_kind']=[]
        self.assertIn('PRESSURE_DROP_DEFINITION_MISSING',self.errors(self.imported([bad])['records'][0]))

if __name__=='__main__':unittest.main(verbosity=2)
