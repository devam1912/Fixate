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
    <div className="min-h-screen bg-black text-zinc-100 flex flex-col selection:bg-emerald-500/30 selection:text-white">
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-7">
        {errorMessage && (
          <div className="mb-5 p-4 rounded-lg bg-rose-950/70 border border-rose-800/80 text-rose-100 text-sm flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-rose-300 shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="font-semibold">Something needs attention</div>
              <p className="text-rose-200/80 text-xs mt-1">{errorMessage}</p>
            </div>
            <button onClick={() => setErrorMessage(null)} className="text-rose-300 hover:text-white">x</button>
          </div>
        )}

        {/* Dynamic Input Control Card */}
        <div className="glass-card p-6 rounded-2xl border border-zinc-800 mb-8">
          <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 pb-5 border-b border-zinc-800">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-white">
                <Sparkles className="w-5 h-5 text-emerald-400" />
              </div>
        )}
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

        {activeTab === 'workbench' && (
          <div className="space-y-6">
            <section className="relative overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 min-h-[260px]">
              <div className="signal-grid absolute inset-0 opacity-70" />
              <div className="absolute inset-y-0 right-0 w-1/2 scan-visual hidden lg:block">
                <div className="trace trace-a" />
                <div className="trace trace-b" />
                <div className="trace trace-c" />
              </div>
              <div className="relative z-10 grid grid-cols-1 lg:grid-cols-[1.05fr_0.95fr] gap-6 p-6">
                <div className="space-y-5">
                  <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3 py-1 text-[11px] text-emerald-200">
                    <Radio className="w-3.5 h-3.5" />
                    Multi-language incident workbench
                  </div>
                  <div>
                    <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white max-w-2xl">
                      Scan the repo, pick the failure, ship a verified fix.
                    </h2>
                    <p className="text-sm text-zinc-400 mt-3 max-w-xl leading-relaxed">
                      Python, TypeScript/JavaScript, and practical C++ paths are grouped into one triage view. Fixate repairs one incident at a time, then can open a PR after proof.
                    </p>
                  </div>
                  <div className="grid grid-cols-3 gap-3 max-w-xl">
                    {[
                      ['Python', 'pytest'],
                      ['C++', 'CMake / Make'],
                      ['JS / TS', 'Jest / Vitest'],
                    ].map(([name, note]) => (
                      <div key={name} className="rounded-lg border border-zinc-800 bg-black/45 p-3">
                        <div className="text-sm font-semibold text-white">{name}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">{note}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-zinc-800 bg-black/70 p-4 shadow-2xl">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <div className="text-sm font-semibold text-white">Repository target</div>
                      <div className="text-xs text-zinc-500 mt-0.5">Choose a source, then scan for every failure.</div>
                    </div>
                    <ScanSearch className="w-5 h-5 text-emerald-300" />
                  </div>

                  <div className="grid grid-cols-3 gap-1 bg-zinc-950 p-1 rounded-lg border border-zinc-800 mb-4">
                    {[
                      ['github', Github, 'GitHub'],
                      ['sample', Sparkles, 'Samples'],
                      ['local', FolderCog, 'Local'],
                    ].map(([key, Icon, label]) => {
                      const TypedIcon = Icon as typeof Github;
                      return (
                        <button
                          key={key as string}
                          onClick={() => setMode(key as Mode)}
                          className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-2 text-xs transition ${
                            mode === key ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:text-zinc-200'
                          }`}
                        >
                          <TypedIcon className="w-3.5 h-3.5" />
                          {label as string}
                        </button>
                      );
                    })}
                  </div>

                  {mode === 'github' && (
                    <input
                      value={githubUrl}
                      onChange={(event) => setGithubUrl(event.target.value)}
                      placeholder="https://github.com/owner/repo or owner/repo"
                      className="w-full rounded-lg bg-zinc-950 border border-zinc-800 px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-500/60"
                    />
                  )}

                  {mode === 'sample' && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {sampleRepos.map((repo) => (
                        <button
                          key={repo.id}
                          onClick={() => setSelectedRepo(repo.id)}
            </section>
                          className={`rounded-lg border p-3 text-left transition ${
                            selectedRepo === repo.id
                              ? 'border-emerald-500/60 bg-emerald-500/10'
                              : 'border-zinc-800 bg-zinc-950 hover:border-zinc-700'
                          }`}
                        >
                          <div className="text-xs font-semibold text-white">{repo.title}</div>
                          <div className="text-[11px] text-zinc-500 mt-1">{repo.note}</div>
                        </button>
                      ))}
                    </div>
                  )}

                  {mode === 'local' && (
                    <input
                      value={customRepoPath}
                      onChange={(event) => setCustomRepoPath(event.target.value)}
                      placeholder="C:\\Users\\Admin\\Desktop\\Projects\\Fixate\\sample_repos\\enterprise_app"
                      className="w-full rounded-lg bg-zinc-950 border border-zinc-800 px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-500/60"
                    />
                  )}

                  <div className="mt-3">
                    <label className="text-[11px] text-zinc-500 flex items-center gap-1.5 mb-1.5">
                      <KeyRound className="w-3.5 h-3.5 text-zinc-500" />
                      Optional environment values
                    </label>
                    <textarea
                      rows={3}
                      value={customEnvText}
                      onChange={(event) => setCustomEnvText(event.target.value)}
                      placeholder={'API_KEY=...\nDATABASE_URL=...'}
                      className="w-full rounded-lg bg-zinc-950 border border-zinc-800 px-3 py-2 text-xs font-mono text-white outline-none focus:border-emerald-500/60"
                    />
                  </div>

                  <button
                    onClick={handleScanRepository}
                    disabled={isScanning || !canScan}
                    className="mt-4 w-full inline-flex items-center justify-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-black hover:bg-zinc-200 disabled:opacity-40 transition"
                  >
                    {isScanning ? <Loader2 className="w-4 h-4 animate-spin" /> : <ScanSearch className="w-4 h-4" />}
                    {isScanning ? 'Scanning repository...' : 'Scan all failures'}
                  </button>
                </div>

            <section className="grid grid-cols-1 lg:grid-cols-[0.92fr_1.08fr] gap-6">
              <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">Language health</h3>
                    <p className="text-xs text-zinc-500 mt-0.5">One scan, separate runners.</p>
                  </div>
                  <ShieldCheck className="w-5 h-5 text-zinc-500" />
                </div>

                {!scan ? (
                  <div className="empty-panel">
                    <TerminalSquare className="w-7 h-7 text-zinc-600 mx-auto mb-2" />
                    <p>Scan a repository to see Python, C++, and JS/TS status side by side.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {scan.languages.map((language) => (
                      <div key={language.language} className="rounded-lg border border-zinc-800 bg-black/45 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${languageColor[language.language] || 'text-zinc-300 bg-zinc-800 border-zinc-700'}`}>
                            {language.language}
                          </span>
                          <span className="text-xs text-zinc-400">{statusLabel(language.status)}</span>
                        </div>
                        <div className="mt-3 flex items-center justify-between text-xs">
                          <span className="text-zinc-500">Failures</span>
                          <span className="text-white font-mono">{language.failure_count}</span>
                        </div>
                        {language.install_detail && (
                          <p className="mt-2 text-[11px] text-zinc-500 line-clamp-2">{language.install_detail}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                  <div>
                    <h3 className="text-sm font-semibold text-white">Failure queue</h3>
                    <p className="text-xs text-zinc-500 mt-0.5">
                      {scan ? `${scan.total_failures} parseable failure${scan.total_failures === 1 ? '' : 's'} found` : 'Waiting for a scan'}
                    </p>
                  </div>
                  <button
                    onClick={handleFixSelected}
                    disabled={!selectedFailure || isFixing}
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-400 px-4 py-2 text-sm font-semibold text-black hover:bg-emerald-300 disabled:opacity-40 transition"
                  >
                    {isFixing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-black" />}
                    {isFixing ? 'Fixing selected failure...' : 'Fix selected'}
                  </button>
                </div>
              </div>

                {!scan ? (
                  <div className="empty-panel">
                    <Bot className="w-7 h-7 text-zinc-600 mx-auto mb-2" />
                    <p>Errors will appear here grouped by language after the scan.</p>
                  </div>
                ) : scan.failures.length === 0 ? (
                  <div className="empty-panel">
                    <CheckCircle2 className="w-7 h-7 text-emerald-500 mx-auto mb-2" />
                    <p>No repair is needed right now. The supported checks did not return a failing Python, C++, or JS/TS test.</p>
                  </div>
                ) : (
                  <div className="space-y-5">
                    {Object.entries(groupedFailures).map(([language, failures]) => (
                      <div key={language}>
                        <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-2">{language}</div>
                        <div className="space-y-2">
                          {failures.map((failure) => {
                            const selected = selectedFailure?.failure_id === failure.failure_id;
                            return (
                              <button
                                key={failure.failure_id}
                                onClick={() => setSelectedFailureId(failure.failure_id)}
                                className={`w-full text-left rounded-lg border p-3 transition ${
                                  selected
                                    ? 'border-emerald-500/60 bg-emerald-500/10'
                                    : 'border-zinc-800 bg-black/40 hover:border-zinc-700'
                                }`}
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div>
                                    <div className="text-sm font-semibold text-white">{failure.test_name}</div>
                                    <div className="mt-1 text-xs text-zinc-500">
                                      {failure.exception_type}
                                      {failure.exception_message ? `: ${failure.exception_message}` : ''}
                                    </div>
                                  </div>
                                  <ArrowRight className={`w-4 h-4 mt-1 ${selected ? 'text-emerald-300' : 'text-zinc-600'}`} />
                                </div>
                                <div className="mt-2 flex items-center gap-2 text-[11px] text-zinc-500 font-mono">
                                  <Code2 className="w-3.5 h-3.5" />
                                  {failure.failing_file || 'unknown file'}
                                  {failure.failing_line ? `:${failure.failing_line}` : ''}
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>

            {incidentSummary && (
              <section className="grid grid-cols-1 lg:grid-cols-[0.9fr_1.1fr] gap-6">
                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold text-white">Verified repair</h3>
                      <p className="text-xs text-zinc-500 mt-1">
                        {incidentSummary.state} after {incidentSummary.total_attempts} attempt{incidentSummary.total_attempts === 1 ? '' : 's'}
                      </p>
                    </div>
                    <CheckCircle2 className="w-6 h-6 text-emerald-300" />
                  </div>
                  <div className="mt-4 space-y-2 text-sm">
                    <div className="flex justify-between gap-4"><span className="text-zinc-500">Test</span><span className="text-white text-right">{incidentSummary.failing_test}</span></div>
                    <div className="flex justify-between gap-4"><span className="text-zinc-500">Suspect</span><span className="text-white text-right">{incidentSummary.suspect_function}</span></div>
                    <div className="flex justify-between gap-4"><span className="text-zinc-500">Proof</span><span className="text-white text-right">{incidentSummary.verified_by}</span></div>
                  </div>
                  <button
                    onClick={handleCreatePr}
                    disabled={isCreatingPr || !incidentSummary.verified_patch || incidentSummary.state === 'FAILED'}
                    className="mt-5 w-full inline-flex items-center justify-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-zinc-800 disabled:opacity-40 transition"
                  >
                    {isCreatingPr ? <Loader2 className="w-4 h-4 animate-spin" /> : <GitPullRequest className="w-4 h-4 text-emerald-300" />}
                    {incidentSummary.pull_request ? 'Pull request created' : 'Create pull request'}
                  </button>
                </div>
                <DiffViewer
                  patch={incidentSummary.verified_patch}
                  risk={incidentSummary.risk_assessment}
                  failureReport={incidentSummary.failure_report}
                />
              </section>
            )}
          </div>
        )}

        {activeTab === 'live' && (
          <div className="space-y-8 animate-in fade-in duration-300">
            <PipelineFlow summary={incidentSummary} liveState={liveState} />
            <DiffViewer
              patch={incidentSummary?.verified_patch}
              risk={incidentSummary?.risk_assessment}
              failureReport={incidentSummary?.failure_report}
            />
          </div>
        )}

        {activeTab === 'graph' && (
          <GraphViewer repoName={selectedRepo} customRepoPath={customRepoPath || (mode === 'github' ? githubUrl : undefined)} />
        )}

        {activeTab === 'history' && (
          <IncidentHistory events={incidentSummary?.telemetry_events || []} />
        )}

        {activeTab === 'eval' && <EvalCharts />}
      </main>

      <footer className="border-t border-zinc-800/80 py-4 text-center text-xs text-zinc-500">
        Fixate keeps repairs small, proves them in isolation, then asks before it ships.
      </footer>
    </div>
  );
}
