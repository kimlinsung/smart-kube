import copy
import os
import tempfile
import unittest
from unittest import mock

from backend import auth, db, paper_jobs, paper_agents, paper_suite
from backend.archive_paths import resolve_archive

EXECUTE_PROGRAM = paper_jobs._execute_generated_program


class SuiteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patch = mock.patch('backend.db.DB_PATH', os.path.join(self.temp.name, 'state.db'))
        patch.start(); self.addCleanup(patch.stop)
        db.init_db()
        self.user, _ = auth.create_user('suite-owner', 'Te5t!Fixture_2026')
        self.exp = db.create_experiment(self.user['id'], 'suite')
        self.workspace = db.create_paper_workspace(self.user['id'], self.exp['id'], 'suite', 'compare', 'full', {})
        self.task = db.create_execution_task(self.user['id'], self.exp['id'], 'paper', 'suite')
        self.row = dict(tier='cloud', count=1, arch='amd64', image='python:3.11-slim', cpu='500m', memory='128Mi', gpu=0)
        self.intelligence = dict(title='suite', goal='compare', summary='evidence', domain='systems', agent_trace={}, acceptance_criteria=['measure'],
            experiments=[dict(id=f'experiment-{i}', title=f'Case {i}', goal=f'Goal {i}', source_quote='Source evidence', paper_findings=['latency 10 ms'], acceptance_criteria=['measure latency']) for i in range(1, 4)])
        self.order = []
        patches = {
            'backend.paper_jobs.task_events.publish_task': {},
            'backend.paper_jobs._plan_configuration': {'side_effect': self.plan},
            'backend.k8s_client.preflight_resources': {'return_value': {'status': 'passed'}},
            'backend.k8s_client.create_ssh_pod': {'side_effect': self.allocate},
            'backend.paper_jobs._wait_for_pod_ready': {'side_effect': self.ready},
            'backend.paper_agents.run_code_agent': {'side_effect': self.code},
            'backend.paper_jobs._persist_generated_program': {'side_effect': self.artifact},
            'backend.paper_jobs._execute_generated_program': {'side_effect': self.execute},
            'backend.paper_agents.run_analysis_agent': {'return_value': {'verdict':'needs_attention','summary':'Limited evidence','checks':[],'risks':['Not comparable']}},
            'backend.paper_agents.run_report_agent': {'return_value': ('# Process report', {})},
            'backend.paper_agents.run_comparison_agent': {'return_value': ('# Comparison report', {})},
            'backend.k8s_client.delete_pods_by_experiment': {'return_value': ['unit-1']},
        }
        self.mocks = {}
        for target, kwargs in patches.items():
            patch = mock.patch(target, **kwargs)
            self.mocks[target] = patch.start(); self.addCleanup(patch.stop)

    def plan(self, workspace, documents, intelligence):
        self.order.append('plan')
        return {'resources':[dict(self.row)], 'agent_trace':[], 'experiment':{'mode':'full'}, 'document_intelligence':intelligence}

    def allocate(self, *args, **kwargs):
        self.order.append('allocate')
        return dict(pod_name='unit-1', node='node104', arch='amd64', node_type='cloud', gpu=0)

    def ready(self, name):
        self.order.append('ready')
        return {'phase':'Running'}

    def code(self, documents, intelligence, configuration):
        self.order.append('code:'+intelligence['id'])
        return {'runtime':{'filename':'same.py','image':'python:3.11-slim'}, 'code':'print(1)', 'runs':[], 'agent_trace':{}}

    def artifact(self, workspace_id, user_id, files, program):
        self.order.append('artifact:'+program['runtime']['filename'])
        return {'stored_path':os.path.join(self.temp.name, program['runtime']['filename'])}

    def execute(self, workspace_id, task_id, schedule, program, path, persist=None):
        self.order.append('execute:'+os.path.basename(path))
        schedule['executions'] = [{'run_id':'run-1','pod_name':'unit-1','node':'node104','status':'succeeded','stdout':'{}','observation':{'latency_ms':12}}]
        persist(schedule)
        return schedule

    def run_suite(self):
        paper_suite.execute_suite(self.workspace['id'], self.task['id'], self.user, [], self.intelligence, [])
        return db.get_paper_workspace(self.workspace['id'])

    def test_three_experiments_share_peak_pool_and_run_sequentially(self):
        result = self.run_suite()
        self.assertEqual(self.order[:5], ['plan','plan','plan','allocate','ready'])
        self.assertEqual([x for x in self.order if x.startswith(('code:','execute:'))],
                         ['code:experiment-1','execute:experiment_1.py','code:experiment-2','execute:experiment_2.py','code:experiment-3','execute:experiment_3.py'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['schedule_json']['created'], 1)
        self.assertEqual(len(result['schedule_json']['executions']), 3)
        self.assertEqual(result['comparison_report_md'], '# Comparison report')
        self.assertEqual(result['report_md'], '# Process report')
        self.assertEqual(len(result['config_json']['suite']), 3)
        self.assertEqual(len(db.get_paper_workspace_status(self.workspace['id'])['experiment_suite']), 3)

    def test_peak_pool_uses_maxima_and_separates_architectures(self):
        configs = [{'resources':[self.row]}, {'resources':[{**self.row,'cpu':'2','memory':'1Gi','count':2}]},
                   {'resources':[{**self.row,'arch':'arm64'}]}]
        rows, assignments = paper_suite.peak_pool(configs)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['cpu'], '2')
        self.assertEqual(rows[0]['memory'], '1Gi')
        self.assertEqual(assignments, [[0],[0,1],[2]])

    def test_real_executor_reclaims_on_first_failed_result(self):
        placement = dict(pod_name='unit-1', node='node104', arch='amd64', node_type='cloud', tier_index=1)
        schedule = {'placements':[placement], 'created':1, 'resources_retained':True}
        db.update_paper_workspace(self.workspace['id'], schedule_json=schedule)
        program = {'runtime':{'filename':'experiment_1.py'}, 'runs':[{'run_id':'run-1','target_tier':'cloud','target_index':1}]}
        result = dict(run_id='run-1',pod_name='unit-1',node='node104',status='failed',exit_code=1,duration_seconds=.1,stdout='',stderr='failure')
        with mock.patch('backend.k8s_client.exec_in_pod'), mock.patch('backend.k8s_client.copy_to_pod',return_value='/tmp/experiment_1.py'), mock.patch('backend.paper_jobs._run_on_placement',return_value=result):
            with self.assertRaises(RuntimeError):
                EXECUTE_PROGRAM(self.workspace['id'],self.task['id'],schedule,program,'/tmp/experiment_1.py')
        saved=db.get_paper_workspace(self.workspace['id'])
        self.assertTrue(saved['resources_reclaimed'])
        self.assertEqual(saved['schedule_json']['executions'][0]['status'],'failed')
        self.mocks['backend.k8s_client.delete_pods_by_experiment'].assert_called_once_with(self.exp['id'])

    def test_decomposition_rejects_missing_excess_or_unverified_experiments(self):
        base={**self.intelligence,'ambiguities':[],'assumptions':[]}
        for cases in [None, [], self.intelligence['experiments']*2, [{**self.intelligence['experiments'][0],'source_quote':'made up quotation from nowhere'}]]:
            with mock.patch('backend.paper_agents._invoke_json',return_value=({**base,'experiments':cases},{})):
                with self.assertRaises(paper_agents.PaperAgentError):
                    paper_agents.run_intent_agent([{'name':'paper.txt','content_type':'text/plain','text':'Source evidence and reported results','truncated':False,'extraction_issue':None}])

    def test_report_kinds_are_independent_and_authorized(self):
        from backend.app import create_app
        with mock.patch('backend.k8s_client.ensure_namespace'),mock.patch('backend.k8s_client.migrate_unlabeled_pods_to',return_value=0):
            app=create_app()
        client=app.test_client()
        db.update_paper_workspace(self.workspace['id'],report_md='# Process',comparison_report_md='# Comparison')
        with client.session_transaction() as session:
            session['user_id']=self.user['id']
        url='/api/paper/workspaces/'+self.workspace['id']+'/report'
        self.assertEqual(client.get(url).data,b'# Process')
        self.assertEqual(client.get(url+'?kind=comparison').data,b'# Comparison')
        self.assertEqual(client.get(url+'?kind=unknown').status_code,400)
        other,_=auth.create_user('foreign-reader','Te5t!Fixture_2026')
        with client.session_transaction() as session:
            session['user_id']=other['id']
        self.assertEqual(client.get(url+'?kind=comparison').status_code,404)

    def test_pool_limit_never_silently_drops_experiments(self):
        with self.assertRaises(ValueError):
            paper_suite.peak_pool([{'resources':[{**self.row,'count':5}]}, {'resources':[{**self.row,'arch':'arm64','count':5}]}])

    def test_failure_reclaims_and_preserves_both_reports(self):
        self.mocks['backend.paper_jobs._execute_generated_program'].side_effect = RuntimeError('run failed')
        with self.assertRaisesRegex(RuntimeError, 'run failed'):
            self.run_suite()
        result = db.get_paper_workspace(self.workspace['id'])
        self.assertTrue(result['resources_reclaimed'])
        self.assertFalse(result['schedule_json']['resources_retained'])
        self.assertEqual([case['status'] for case in result['config_json']['suite']], ['failed','skipped','skipped'])
        self.assertIn('过程报告', result['report_md'])
        self.assertIn('实验对比报告', result['comparison_report_md'])
        self.assertEqual(len([x for x in self.order if x.startswith('code:')]), 1)

    def test_readiness_failure_never_generates_code(self):
        self.mocks['backend.paper_jobs._wait_for_pod_ready'].side_effect = RuntimeError('not ready')
        with self.assertRaisesRegex(RuntimeError, 'not ready'):
            self.run_suite()
        self.mocks['backend.paper_agents.run_code_agent'].assert_not_called()
        self.assertTrue(db.get_paper_workspace(self.workspace['id'])['resources_reclaimed'])

    def test_cleanup_failure_stays_visible_and_retryable(self):
        self.mocks['backend.paper_jobs._execute_generated_program'].side_effect = RuntimeError('run failed')
        self.mocks['backend.k8s_client.delete_pods_by_experiment'].side_effect = RuntimeError('API unavailable')
        with self.assertRaises(RuntimeError):
            self.run_suite()
        result = db.get_paper_workspace(self.workspace['id'])
        self.assertFalse(result['resources_reclaimed'])
        self.assertEqual(result['schedule_json']['cleanup']['status'], 'failed')

    def test_report_failure_keeps_evidence_and_reclaims(self):
        self.mocks['backend.paper_agents.run_comparison_agent'].side_effect = RuntimeError('LLM unavailable')
        with self.assertRaises(RuntimeError):
            self.run_suite()
        result = db.get_paper_workspace(self.workspace['id'])
        self.assertTrue(result['comparison_report_md'])
        self.assertTrue(result['resources_reclaimed'])

    def test_legacy_path_mapping_is_exact_and_owner_bound(self):
        path = '/home/ubuntu/smart-kube/uploads/6/paper/id/input.pdf'
        self.assertEqual(resolve_archive(path, self.temp.name, 6), os.path.realpath(self.temp.name)+'/6/paper/id/input.pdf')
        for bad in [path.replace('/6/', '/7/'), path.replace('/paper/', '/../'), '/etc/passwd']:
            with self.assertRaises(ValueError):
                resolve_archive(bad, self.temp.name, 6)

    def test_mapped_symlink_cannot_escape_upload_root(self):
        os.symlink('/etc', self.temp.name+'/6')
        with self.assertRaises(ValueError):
            resolve_archive('/home/ubuntu/smart-kube/uploads/6/passwd', self.temp.name, 6)
