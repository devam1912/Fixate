import React, { useState } from 'react';
import { Navbar } from './components/Navbar';
import { PipelineFlow } from './components/PipelineFlow';
import { DiffViewer } from './components/DiffViewer';
import { GraphViewer } from './components/GraphViewer';
import { EvalCharts } from './components/EvalCharts';
import { IncidentHistory } from './components/IncidentHistory';
import { IncidentSummary, TelemetryEvent } from './types';
import { Play, Sparkles, Code2, AlertTriangle, Github, Terminal, FolderCog } from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'live' | 'history' | 'graph' | 'eval'>('live');
  const [mode, setMode] = useState<'github' | 'sample' | 'local'>('github');
  
  // GitHub Repo State
  const [githubUrl, setGithubUrl] = useState<string>('');
  
  // Sample Repos State
  const [selectedRepo, setSelectedRepo] = useState<string>('calculator_app');

  // Custom User Local Repo State
  const [customRepoPath, setCustomRepoPath] = useState<string>('');
  const [customPytestLog, setCustomPytestLog] = useState<string>('');

  const [incidentSummary, setIncidentSummary] = useState<IncidentSummary | null>(null);
  const [telemetryEvents, setTelemetryEvents] = useState<TelemetryEvent[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const handleTriggerIncident = async () => {
    setIsLoading(true);
    setTelemetryEvents([]);
    try {
      let payload: any = { human_approval_required: true };

      if (mode === 'github') {
        payload.repo_url = githubUrl.trim();
        payload.pytest_log = customPytestLog.trim() || undefined;
      } else if (mode === 'local') {
        payload.repo_path = customRepoPath.trim();
        payload.pytest_log = customPytestLog.trim() || undefined;
      } else {
        payload.repo_name = selectedRepo;
      }

      const res = await fetch('/api/incident/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data: IncidentSummary = await res.json();
      setIncidentSummary(data);
      if (data.telemetry_events) {
        setTelemetryEvents(data.telemetry_events);
      }
    } catch (err) {
      console.error('Error triggering incident:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const sampleRepos = [
    {
      id: 'calculator_app',
      title: 'calculator_app',
      bug: 'Discount Logic Bug',
      type: 'Math / Logic',
      description: 'Off-by-one percentage discount formula error in price engine.',
    },
    {
      id: 'ecommerce_api',
      title: 'ecommerce_api',
      bug: 'Dict KeyError & Attribute Exception',
      type: 'API Schema',
      description: 'Missing dictionary attribute validation in order creation endpoint.',
    },
    {
      id: 'data_processor',
      title: 'data_processor',
      bug: 'Off-by-One Loop & Null Reference',
      type: 'Pipeline Data',
      description: 'Index boundary overshoot and unhandled None value in record transformer.',
    },
  ];

  return (
    <div className="min-h-screen bg-black text-zinc-100 flex flex-col font-sans selection:bg-zinc-800 selection:text-white">
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
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
                  Clone any GitHub repository URL, specify local folder path, or use built-in benchmarks
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
                Local Path
              </button>
            </div>
          </div>

          {/* Mode 1: GitHub Repo URL Form */}
          {mode === 'github' && (
            <div className="mt-5 space-y-4">
              <div>
                <label className="text-xs font-mono text-zinc-300 font-semibold block mb-2 flex items-center gap-2">
                  <Github className="w-4 h-4 text-emerald-400" />
                  GitHub Repository URL (or `owner/repo`):
                </label>
                <input
                  type="text"
                  placeholder="https://github.com/owner/repository (e.g., https://github.com/pallets/flask)"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-2.5 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                />
                <p className="text-[11px] text-zinc-500 font-mono mt-1">
                  Fixate will clone the repository, run pytest, build AST graph, retrieve context, and generate a verified diff patch.
                </p>
              </div>

              <div>
                <label className="text-xs font-mono text-zinc-400 font-semibold block mb-2 flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-zinc-500" />
                  Optional Pytest Error Log (Leave blank to auto-detect pytest errors):
                </label>
                <textarea
                  rows={2}
                  placeholder="Paste failing pytest traceback log (Optional)..."
                  value={customPytestLog}
                  onChange={(e) => setCustomPytestLog(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                />
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

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {sampleRepos.map((repo) => {
                  const isSelected = selectedRepo === repo.id;
                  return (
                    <button
                      key={repo.id}
                      onClick={() => setSelectedRepo(repo.id)}
                      className={`p-3.5 rounded-xl border text-left transition-all ${
                        isSelected
                          ? 'bg-zinc-900 border-zinc-700 text-white shadow-sm'
                          : 'bg-zinc-950 border-zinc-800/80 text-zinc-400 hover:border-zinc-700'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <Code2 className={`w-3.5 h-3.5 ${isSelected ? 'text-emerald-400' : 'text-zinc-500'}`} />
                          <span className="font-mono font-bold text-xs text-white">{repo.title}</span>
                        </div>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-zinc-800">
                          {repo.type}
                        </span>
                      </div>
                      <div className="text-[11px] font-mono text-rose-400 font-medium mb-1 flex items-center gap-1.5">
                        <AlertTriangle className="w-3 h-3 text-rose-400 shrink-0" /> {repo.bug}
                      </div>
                      <p className="text-[11px] text-zinc-500 font-sans leading-snug">{repo.description}</p>
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
                  placeholder="e.g. C:\Users\Admin\Desktop\MyProject or /home/user/myproject"
                  value={customRepoPath}
                  onChange={(e) => setCustomRepoPath(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-4 py-2.5 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                />
              </div>

              <div>
                <label className="text-xs font-mono text-zinc-400 font-semibold block mb-2">
                  Optional Pytest Traceback Log:
                </label>
                <textarea
                  rows={2}
                  placeholder="Paste failing traceback (Optional)..."
                  value={customPytestLog}
                  onChange={(e) => setCustomPytestLog(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-xl p-3 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
                />
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={handleTriggerIncident}
                  disabled={isLoading || (!customRepoPath.trim() && !customPytestLog.trim())}
                  className="bg-white hover:bg-zinc-200 text-black font-mono font-bold text-xs px-6 py-2.5 rounded-xl flex items-center gap-2 transition-all disabled:opacity-40"
                >
                  <Play className="w-3.5 h-3.5 fill-black" />
                  {isLoading ? 'EXECUTING...' : 'RUN LOCAL FIX'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Tab Views */}
        {activeTab === 'live' && (
          <div>
            <PipelineFlow summary={incidentSummary} />
            {incidentSummary?.verified_patch && (
              <DiffViewer patch={incidentSummary.verified_patch} risk={incidentSummary.risk_assessment} />
            )}
            <IncidentHistory events={telemetryEvents} />
          </div>
        )}

        {activeTab === 'graph' && (
          <GraphViewer
            repoName={selectedRepo}
            customRepoPath={
              mode === 'github' && githubUrl.trim()
                ? githubUrl.trim()
                : mode === 'local' && customRepoPath.trim()
                ? customRepoPath.trim()
                : undefined
            }
          />
        )}

        {activeTab === 'history' && <IncidentHistory events={telemetryEvents} />}

        {activeTab === 'eval' && <EvalCharts />}
      </main>

      <footer className="border-t border-zinc-900 py-6 text-center text-xs text-zinc-500 font-mono">
        Fixate — Autonomous Self-Healing CI & Codebase Agent • Docker Sandbox Isolation
      </footer>
    </div>
  );
};
