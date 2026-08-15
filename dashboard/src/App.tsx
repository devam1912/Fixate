import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Code2,
  FolderCog,
  GitPullRequest,
  Github,
  KeyRound,
  Loader2,
  Play,
  Radio,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
} from 'lucide-react';
import { Navbar } from './components/Navbar';
import { PipelineFlow } from './components/PipelineFlow';
import { DiffViewer } from './components/DiffViewer';
import { GraphViewer } from './components/GraphViewer';
import { IncidentHistory } from './components/IncidentHistory';
import { EvalCharts } from './components/EvalCharts';
import { IncidentSummary, RepositoryFailure, RepositoryScan } from './types';

type Tab = 'workbench' | 'live' | 'history' | 'graph' | 'eval';
type Mode = 'github' | 'sample' | 'local';

const sampleRepos = [
  { id: 'enterprise_app', title: 'Enterprise suite', note: 'Python services, 5 known defects' },
  { id: 'calculator_app', title: 'Calculator API', note: 'Small pytest logic bug' },
  { id: 'ecommerce_api', title: 'Ecommerce API', note: 'Validation and schema failures' },
  { id: 'data_processor', title: 'Data pipeline', note: 'Boundary and null handling' },
  { id: 'ts_cart_app', title: 'TS cart app', note: 'Vitest TypeScript repair path' },
];

const languageColor: Record<string, string> = {
  python: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/25',
  javascript: 'text-cyan-300 bg-cyan-500/10 border-cyan-500/25',
  cpp: 'text-amber-300 bg-amber-500/10 border-amber-500/25',
};

function statusLabel(status: string) {
  if (status === 'failed') return 'Needs attention';
  if (status === 'passed') return 'Clean';
  if (status === 'no_tests') return 'No tests';
  if (status === 'unparsed_failure') return 'Unparsed failure';
  return status.replace(/_/g, ' ');
}

export function App() {
  const [activeTab, setActiveTab] = useState<Tab>('workbench');
  const [mode, setMode] = useState<Mode>('github');
  const [selectedRepo, setSelectedRepo] = useState('enterprise_app');
  const [githubUrl, setGithubUrl] = useState('');
  const [customRepoPath, setCustomRepoPath] = useState('');
  const [customEnvText, setCustomEnvText] = useState('');
  const [scan, setScan] = useState<RepositoryScan | null>(null);
  const [selectedFailureId, setSelectedFailureId] = useState<string | null>(null);
  const [incidentSummary, setIncidentSummary] = useState<IncidentSummary | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [isFixing, setIsFixing] = useState(false);
  const [isCreatingPr, setIsCreatingPr] = useState(false);
  const [liveState, setLiveState] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [prMessage, setPrMessage] = useState<string | null>(null);

  const selectedFailure = useMemo(
    () => scan?.failures.find((failure) => failure.failure_id === selectedFailureId) || scan?.failures[0] || null,
    [scan, selectedFailureId]
  );

  const groupedFailures = useMemo(() => {
    const groups: Record<string, RepositoryFailure[]> = {};
    for (const failure of scan?.failures || []) {
      groups[failure.language] = [...(groups[failure.language] || []), failure];
    }
    return groups;
  }, [scan]);

  const payloadForTarget = () => {
    const base: any = { env_text: customEnvText.trim() || undefined };
    if (mode === 'github') base.repo_url = githubUrl.trim();
    else if (mode === 'local') base.repo_path = customRepoPath.trim();
    else base.repo_name = selectedRepo;
    return base;
  };

  const handleScanRepository = async () => {
    setIsScanning(true);
    setErrorMessage(null);
    setPrMessage(null);
    setIncidentSummary(null);
    setLiveState(null);

    try {
      const response = await fetch('/api/repository/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payloadForTarget()),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Scan failed');
      setScan(body as RepositoryScan);
      setSelectedFailureId(body.failures?.[0]?.failure_id || null);
    } catch (err: any) {
      setErrorMessage(err.message || 'Could not scan this repository.');
    } finally {
      setIsScanning(false);
    }
  };

  const handleFixSelected = async () => {
    if (!scan || !selectedFailure) return;
    setIsFixing(true);
    setErrorMessage(null);
    setPrMessage(null);
    setIncidentSummary(null);
    setLiveState(null);
    setActiveTab('live');

    try {
      const response = await fetch('/api/incident/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...payloadForTarget(),
          pytest_log: selectedFailure.raw_log,
          human_approval_required: true,
          env_text: customEnvText.trim() || undefined,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Could not start repair');
      const data = await followIncident(body.incident_id);
      setIncidentSummary(data);
      setActiveTab('workbench');
    } catch (err: any) {
      setErrorMessage(err.message || 'Repair failed.');
    } finally {
      setIsFixing(false);
    }
  };

  const followIncident = (incidentId: string): Promise<IncidentSummary> =>
    new Promise((resolve, reject) => {
      const source = new EventSource(`/api/stream/sse/${incidentId}`);

      const finish = async () => {
        source.close();
        try {
          const res = await fetch(`/api/incident/${incidentId}`);
          const body = await res.json();
          if (body.status === 'completed') resolve(body.summary as IncidentSummary);
          else reject(new Error(body.detail || 'The incident did not complete.'));
        } catch (err: any) {
          reject(err);
        }
      };

      source.addEventListener('agent_event', (evt: MessageEvent) => {
        try {
          const event = JSON.parse(evt.data);
          if (event.action === 'STATE_TRANSITION') setLiveState(event.output_summary);
        } catch {
          /* ignore malformed frames */
        }
      });

      source.addEventListener('done', finish);
      source.onerror = () => {
        source.close();
        const poll = setInterval(async () => {
          const res = await fetch(`/api/incident/${incidentId}`);
          const body = await res.json();
          if (body.status === 'completed') {
            clearInterval(poll);
            resolve(body.summary as IncidentSummary);
          } else if (body.status === 'error') {
            clearInterval(poll);
            reject(new Error(body.detail));
          }
        }, 2000);
      };
    });

  const handleCreatePr = async () => {
    if (!incidentSummary) return;
    setIsCreatingPr(true);
    setErrorMessage(null);
    setPrMessage(null);

    try {
      const response = await fetch(`/api/incident/${incidentSummary.incident_id}/pull-request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Could not create pull request');
      setPrMessage(`Pull request opened: ${body.url}`);
      setIncidentSummary({ ...incidentSummary, pull_request: body });
    } catch (err: any) {
      setErrorMessage(err.message || 'Could not create pull request.');
    } finally {
      setIsCreatingPr(false);
    }
  };

  const canScan =
    (mode === 'github' && githubUrl.trim()) ||
    (mode === 'local' && customRepoPath.trim()) ||
    mode === 'sample';

  return (
    <div className="min-h-screen bg-black text-zinc-100 flex flex-col font-sans selection:bg-zinc-800 selection:text-white">
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
        {/* Error Alert Banner */}
        {errorMessage && (
          <div className="mb-6 p-4 rounded-xl bg-rose-950/80 border border-rose-800/80 text-rose-200 text-xs font-mono flex items-start gap-3 shadow-lg animate-in fade-in slide-in-from-top-2">
            <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-bold uppercase tracking-wider block mb-1">Execution Warning:</span>
              <p className="leading-relaxed">{errorMessage}</p>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-rose-400 hover:text-rose-100 font-bold px-2 py-0.5 rounded hover:bg-rose-900/50 transition-colors"
            >
              ✕
            </button>
          </div>
        )}

        {/* Dynamic Input Control Card */}
        <div className="glass-card p-6 rounded-2xl border border-zinc-800 mb-8">
          <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 pb-5 border-b border-zinc-800">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-white">
                <Sparkles className="w-5 h-5 text-emerald-400" />
              </div>
              <div>
                <h2 className="text-sm font-mono font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  Repository Self-Healing Trigger
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5 font-mono">
                  Clone any Python GitHub repository URL, specify local folder path, or use built-in benchmarks
                </p>
              </div>
            </div>

            {/* Mode Switcher */}
            <div className="flex items-center gap-1 bg-zinc-950 p-1 rounded-xl border border-zinc-800">
              <button
                onClick={() => setMode('github')}
                className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
                  mode === 'github'
                    ? 'bg-zinc-800 text-white border border-zinc-700'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                <Github className="w-3.5 h-3.5" />
                GitHub Repo URL
              </button>
              <button
                onClick={() => setMode('sample')}
                className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
                  mode === 'sample'
                    ? 'bg-zinc-800 text-white border border-zinc-700'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                Sample Benchmarks
              </button>
              <button
                onClick={() => setMode('local')}
                className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
                  mode === 'local'
                    ? 'bg-zinc-800 text-white border border-zinc-700'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                <FolderCog className="w-3.5 h-3.5" />
                Local Folder Path
              </button>
            </div>
          </div>

          {/* Mode 1: GitHub Repo URL */}
          {mode === 'github' && (
            <div className="mt-5 space-y-4">
              <div>
                <label className="text-xs font-mono text-zinc-300 font-semibold block mb-2 flex items-center gap-2">
                  <Github className="w-4 h-4 text-emerald-400" />
                  GitHub Repository URL (or `owner/repo`):
                </label>
                <input
                  type="text"
                  placeholder="https://github.com/pallets/flask  or  pallets/flask"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-2.5 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                />
                <p className="text-[11px] font-mono text-zinc-500 mt-1.5">
                  Fixate requires a Python repository containing .py files. It will clone the repository, run pytest, build AST graph, retrieve context, and generate a verified diff patch.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-mono text-zinc-400 block mb-1.5 flex items-center gap-1.5">
                    <Code2 className="w-3.5 h-3.5 text-zinc-500" />
                    Optional Pytest Error Log (Leave blank to auto-detect pytest errors):
                  </label>
                  <textarea
                    rows={3}
                    placeholder="Paste failing pytest traceback log (Optional)..."
                    value={customPytestLog}
                    onChange={(e) => setCustomPytestLog(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-mono text-zinc-400 block mb-1.5 flex items-center gap-1.5">
                    <KeyRound className="w-3.5 h-3.5 text-emerald-400" />
                    Optional Environment Variables (.env Secrets):
                  </label>
                  <textarea
                    rows={3}
                    placeholder="API_KEY=your_key_here&#10;DATABASE_URL=postgres://..."
                    value={customEnvText}
                    onChange={(e) => setCustomEnvText(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                  />
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={handleTriggerIncident}
                  disabled={isLoading || !githubUrl.trim()}
                  className="bg-white hover:bg-zinc-200 text-black font-mono font-bold text-xs px-6 py-2.5 rounded-xl flex items-center gap-2 transition-all disabled:opacity-40"
                >
                  <Play className="w-3.5 h-3.5 fill-black" />
                  {isLoading ? 'CLONING & FIXING...' : 'CLONE & TRIGGER SELF-HEALING'}
                </button>
              </div>
            </div>
          )}

          {/* Mode 2: Sample Repo Benchmarks */}
          {mode === 'sample' && (
            <div className="mt-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-mono text-zinc-400">
                  Select Benchmark Codebase:
                </span>
                <button
                  onClick={handleTriggerIncident}
                  disabled={isLoading}
                  className="bg-white hover:bg-zinc-200 text-black font-mono font-bold text-xs px-6 py-2 rounded-xl flex items-center gap-2 transition-all disabled:opacity-40"
                >
                  <Play className="w-3.5 h-3.5 fill-black" />
                  {isLoading ? 'EXECUTING...' : 'TRIGGER FIX'}
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                {sampleRepos.map((repo) => {
                  const isSelected = selectedRepo === repo.id;
                  return (
                    <button
                      key={repo.id}
                      onClick={() => setSelectedRepo(repo.id)}
                      className={`p-3.5 rounded-xl border text-left transition-all ${
                        isSelected
                          ? 'bg-zinc-900 border-emerald-500/50 text-white shadow-sm'
                          : 'bg-zinc-950 border-zinc-800/80 text-zinc-400 hover:border-zinc-700'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <Code2 className={`w-3.5 h-3.5 ${isSelected ? 'text-emerald-400' : 'text-zinc-500'}`} />
                          <span className="font-mono font-bold text-xs text-white truncate max-w-[120px]">{repo.title}</span>
                        </div>
                        <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-zinc-800 truncate">
                          {repo.type}
                        </span>
                      </div>
                      <div className="text-[11px] font-mono text-rose-400 font-medium mb-1 flex items-center gap-1.5">
                        <AlertTriangle className="w-3 h-3 text-rose-400 shrink-0" /> {repo.bug}
                      </div>
                      <p className="text-[11px] text-zinc-500 font-sans leading-snug line-clamp-2">{repo.description}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Mode 3: Local Directory Path */}
          {mode === 'local' && (
            <div className="mt-5 space-y-4">
              <div>
                <label className="text-xs font-mono text-zinc-300 font-semibold block mb-2 flex items-center gap-2">
                  <FolderCog className="w-4 h-4 text-emerald-400" />
                  Local Repository Directory Path:
                </label>
                <input
                  type="text"
                  placeholder="C:\Users\Admin\Desktop\Projects\Fixate\sample_repos\enterprise_app"
                  value={customRepoPath}
                  onChange={(e) => setCustomRepoPath(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-2.5 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-mono text-zinc-400 block mb-1.5 flex items-center gap-1.5">
                    <Code2 className="w-3.5 h-3.5 text-zinc-500" />
                    Optional Pytest Error Log (Leave blank to auto-detect pytest errors):
                  </label>
                  <textarea
                    rows={3}
                    placeholder="Paste failing pytest traceback log (Optional)..."
                    value={customPytestLog}
                    onChange={(e) => setCustomPytestLog(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-mono text-zinc-400 block mb-1.5 flex items-center gap-1.5">
                    <KeyRound className="w-3.5 h-3.5 text-emerald-400" />
                    Optional Environment Variables (.env Secrets):
                  </label>
                  <textarea
                    rows={3}
                    placeholder="API_KEY=your_key_here&#10;DATABASE_URL=postgres://..."
                    value={customEnvText}
                    onChange={(e) => setCustomEnvText(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                  />
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={handleTriggerIncident}
                  disabled={isLoading || !customRepoPath.trim()}
                  className="bg-white hover:bg-zinc-200 text-black font-mono font-bold text-xs px-6 py-2.5 rounded-xl flex items-center gap-2 transition-all disabled:opacity-40"
                >
                  <Play className="w-3.5 h-3.5 fill-black" />
                  {isLoading ? 'ANALYZING & FIXING...' : 'TRIGGER SELF-HEALING'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Tab View Switcher */}
        {activeTab === 'live' && (
          <div className="space-y-8 animate-in fade-in duration-300">
            <PipelineFlow summary={incidentSummary} liveState={liveState} />
            <DiffViewer patch={incidentSummary?.verified_patch} risk={incidentSummary?.risk_assessment} />
          </div>
        )}

        {activeTab === 'graph' && (
          <div className="animate-in fade-in duration-300">
            <GraphViewer repoName={selectedRepo} customRepoPath={customRepoPath || (mode === 'github' ? githubUrl : undefined)} />
          </div>
        )}

        {activeTab === 'history' && (
          <div className="animate-in fade-in duration-300">
            <IncidentHistory events={incidentSummary?.telemetry_events || []} />
          </div>
        )}

        {activeTab === 'eval' && (
          <div className="animate-in fade-in duration-300">
            <EvalCharts />
          </div>
        )}
      </main>

      <footer className="border-t border-zinc-800/80 py-4 text-center text-xs font-mono text-zinc-400">
        Fixate — Autonomous Self-Healing CI & Codebase Agent • Docker Sandbox Isolation
      </footer>
    </div>
  );
}
