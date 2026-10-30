import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('collector',Path(__file__).with_name('recopilador.py'))
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)

class CollectorTests(unittest.TestCase):
    def test_exact_bitrate_and_cpu_math(self):
        previous={'mono':10,'rx':1000,'tx':2000,'cpu':(100,50),'monitor':{'cpu_seconds':2}}
        current={'mono':15,'rx':5001000,'tx':2502000,'cpu':(200,140),'monitor':{'cpu_seconds':2.1,'memory_peak_bytes':123},'ram':11}
        record=collector.rate_record(previous,current)
        self.assertEqual(record['rx_mbps'],8)
        self.assertEqual(record['tx_mbps'],4)
        self.assertEqual(record['host_cpu_pct'],10)
        self.assertAlmostEqual(record['monitor_cpu_delta_s'],.1)

    def test_initial_sample_does_not_double_count_cgroup_cpu(self):
        current={'mono':15,'rx':1000,'tx':2000,'cpu':(200,140),'monitor':{'cpu_seconds':200},'ram':11}
        record=collector.rate_record(None,current)
        self.assertEqual(record['monitor_cpu_delta_s'],0)
        self.assertEqual(record['rx_delta_bytes'],0)

    def test_counter_reset_does_not_create_negative_rate(self):
        previous={'mono':10,'rx':1000,'tx':2000,'cpu':(100,50),'monitor':{}}
        current={'mono':15,'rx':1,'tx':2,'cpu':(200,140),'monitor':{},'ram':11}
        record=collector.rate_record(previous,current)
        self.assertEqual(record['rx_mbps'],0);self.assertEqual(record['tx_mbps'],0)

    def test_storage_cap_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            writer=collector.Writer(Path(folder),collector.RESERVE+10)
            with self.assertRaises(OverflowError):writer.write('test.jsonl',{'kind':'too-long'})
            self.assertFalse((Path(folder)/'test.jsonl').exists())

    def test_low_disk_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(collector.shutil,'disk_usage',return_value=type('Usage',(),{'free':0})()):
            writer=collector.Writer(Path(folder),collector.LIMIT)
            with self.assertRaises(OverflowError):writer.write('test.jsonl',{'kind':'x'})

    def test_summary_and_restore_preserve_counts(self):
        config={'start_epoch':1000,'end_epoch':87400,'interface':'eth0','limit_bytes':collector.LIMIT}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            sample={'kind':'network','elapsed_s':5,'rx_delta_bytes':5000000,'tx_delta_bytes':1000000,'rx_mbps':8,'tx_mbps':1.6,'host_cpu_pct':10,'monitor_cpu_delta_s':.1,'monitor_memory_peak_bytes':10000,'monitor_memory_anonymous_bytes':6000,'ram_used_pct':11}
            (path/'trafico-recursos.jsonl').write_text(json.dumps(sample)+'\n')
            summary=collector.restore_summary(config,path)
            with patch.object(collector.os,'cpu_count',return_value=4):collector.write_summary(path,summary,config)
            saved=json.loads((path/'resumen.json').read_text())
            self.assertEqual(saved['network_samples'],1)
            self.assertEqual(saved['rx_average_mbps'],8)
            self.assertEqual(saved['monitor_cpu_average_pct_host'],.5)
            self.assertEqual(saved['monitor_memory_peak_bytes'],10000)

    def test_restart_instance_change_is_distinguished(self):
        summary=collector.summary_base({'start_epoch':1000,'end_epoch':87400,'interface':'eth0'})
        for cid,restarts in [('old',2),('new',0)]:
            collector.aggregate(summary,{'kind':'health','data':{'local_status':'ok','containers':[{'name':'app','id':cid,'restarts':restarts,'stats':{'CPUPerc':'1.2%'}}]}})
        self.assertEqual(summary['container_cpu']['app']['instance_changes'],1)
        self.assertEqual(summary['health_samples'],2)

    def test_session_path_cannot_escape_log_root(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'state.json';state.write_text(json.dumps({'directory':'/elsewhere'}))
            with patch.object(collector,'STATE',state),patch.object(collector,'LOGROOT',Path(folder)):
                with self.assertRaises(ValueError):collector.read_state()

    def test_short_collection_stops_at_deadline_and_preserves_logs(self):
        class Clock:
            elapsed=0
            def time(self):return 1000+self.elapsed
            def monotonic(self):return self.elapsed
            def sleep(self,seconds):self.elapsed+=seconds
        class Future:
            def done(self):return True
            def result(self,**kwargs):return {'kind':'health','time':'test','probe_duration_s':.1,'data':{'local_status':'ok','containers':[]}}
        class Pool:
            def __init__(self,**kwargs):pass
            def submit(self,*args,**kwargs):return Future()
            def shutdown(self,**kwargs):pass
        clock=Clock()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=root/'session';directory.mkdir();state=root/'actual.json'
            config={'directory':str(directory),'start_epoch':1000,'end_epoch':1003,'hours':3/3600,'interface':'eth0','network_interval_s':1,'health_interval_s':1,'limit_bytes':collector.LIMIT}
            state.write_text(json.dumps(config));(directory/'resumen.json').write_text(json.dumps(collector.summary_base(config)))
            with patch.object(collector,'STATE',state),patch.object(collector,'LOGROOT',root),patch.object(collector.time,'time',side_effect=clock.time),patch.object(collector.time,'monotonic',side_effect=clock.monotonic),patch.object(collector.time,'sleep',side_effect=clock.sleep),patch.object(collector.signal,'signal'),patch.object(collector,'cgroup_path',return_value=None),patch.object(collector,'network_bytes',side_effect=lambda interface:(int(clock.elapsed*1000),int(clock.elapsed*2000))),patch.object(collector,'host_cpu',return_value=(100,20)),patch.object(collector,'memory_used',return_value=11),patch.object(collector.concurrent.futures,'ThreadPoolExecutor',Pool):
                collector.collect()
            report=json.loads((directory/'resumen.json').read_text())
            self.assertEqual(report['status'],'completed');self.assertEqual(report['network_samples'],3)
            self.assertEqual(report['rx_bytes'],2000);self.assertEqual(report['health_samples'],3)
            self.assertTrue((directory/'trafico-recursos.jsonl').is_file());self.assertTrue((directory/'salud.jsonl').is_file())


if __name__=='__main__':unittest.main()
