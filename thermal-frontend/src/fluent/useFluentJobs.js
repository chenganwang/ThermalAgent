import { useCallback, useEffect, useRef, useState } from 'react';
import { getCfdJob, getCfdJobReport, getCfdJobs, getCfdStatus, prepareCfdJob, runCfdJob } from '../api/client.js';
import { fluentError } from './fluentPresentation.js';

export default function useFluentJobs({ active, useMockResponses }) {
  const [status, setStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [revision, setRevision] = useState(0);
  const mounted = useRef(false);
  const operationRef = useRef(false);
  const operationController = useRef(null);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  const hasRunning = jobs.some(job => job.status === 'running');

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; operationController.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!active || useMockResponses || busy) return undefined;
    const controller = new AbortController();
    setLoading(true);
    Promise.all([getCfdStatus({ signal: controller.signal }), getCfdJobs({ signal: controller.signal })])
      .then(([nextStatus, nextJobs]) => {
        if (controller.signal.aborted) return;
        if (nextStatus?.schema_version !== '1.0' || !Array.isArray(nextJobs?.items)) throw Error('invalid contract');
        setStatus(nextStatus);
        setJobs(nextJobs.items);
        setLoadError('');
      })
      .catch(requestError => {
        if (controller.signal.aborted) return;
        setStatus(null);
        setLoadError(fluentError(requestError));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [active, useMockResponses, revision, busy]);

  useEffect(() => {
    if (!active || useMockResponses || busy || loading || loadError || !hasRunning) return undefined;
    const timer = setTimeout(refresh, 3000);
    return () => clearTimeout(timer);
  }, [active, useMockResponses, busy, loading, loadError, hasRunning, jobs, refresh]);

  const perform = async action => {
    if (operationRef.current || useMockResponses) return null;
    operationRef.current = true;
    operationController.current = new AbortController();
    setBusy(true);
    setActionError('');
    try {
      const value = await action({ signal: operationController.current.signal });
      if (!mounted.current) return null;
      if (value?.job_id && value?.status) {
        setJobs(previous => [value, ...previous.filter(job => job.job_id !== value.job_id)]);
        setSelectedId(value.job_id);
      }
      return value;
    } catch (requestError) {
      if (mounted.current) setActionError(fluentError(requestError));
      return null;
    } finally {
      operationRef.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const prepare = values => perform(options => prepareCfdJob(values, options));
  const run = job => perform(options => runCfdJob(job.job_id, job.input_fingerprint, options));
  const select = job => { setSelectedId(job.job_id); return perform(options => getCfdJob(job.job_id, options)); };
  const downloadReport = async job => {
    const report = await perform(options => getCfdJobReport(job.job_id, options));
    if (!report || typeof report.markdown !== 'string') return;
    const url = URL.createObjectURL(new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `CFD-${job.job_id.replace(/[^a-zA-Z0-9_-]/g, '_')}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return { status, jobs, selected: jobs.find(job => job.job_id === selectedId) || null, loading, busy, error: actionError || loadError, refresh, prepare, run, select, downloadReport };
}
