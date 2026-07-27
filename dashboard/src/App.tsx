import React, { useState } from 'react';
import { Navbar } from './components/Navbar';
import { PipelineFlow } from './components/PipelineFlow';
import { DiffViewer } from './components/DiffViewer';
import { GraphViewer } from './components/GraphViewer';
import { EvalCharts } from './components/EvalCharts';
import { IncidentHistory } from './components/IncidentHistory';
import { IncidentSummary, TelemetryEvent } from './types';
import { Play, Sparkles, Code2, AlertTriangle, FolderCog, Terminal } from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'live' | 'history' | 'graph' | 'eval'>('live');
  const [mode, setMode] = useState<'sample' | 'custom'>('sample');
  
  // Sample Repos State
  const [selectedRepo, setSelectedRepo] = useState<string>('calculator_app');

  // Custom User Repo State
  const [customRepoPath, setCustomRepoPath] = useState<string>('');
  const [customPytestLog, setCustomPytestLog] = useState<string>('');

  const [incidentSummary, setIncidentSummary] = useState<IncidentSummary | null>(null);
  const [telemetryEvents, setTelemetryEvents] = useState<TelemetryEvent[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const handleTriggerIncident = async () => {
    setIsLoading(true);
    setTelemetryEvents([]);
    try {
      const payload =
        mode === 'custom'
          ? {
              repo_path: customRepoPath.trim() || undefined,
              pytest_log: customPytestLog.trim() || undefined,
              human_approval_required: true,
            }
          : {
              repo_name: selectedRepo,
              human_approval_required: true,
            };

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
    <div className="min-h-screen bg-[#070709] bg-grid-pattern bg-radial-gradient text-zinc-100 flex flex-col font-sans selection:bg-violet-500/30 selection:text-violet-200">
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
        {/* Dynamic Mode Selector Bar */}
        <div className="glass-card p-6 rounded-3xl border border-white/[0.08] mb-8 relative overflow-hidden">
          <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 pb-6 border-b border-white/[0.08]">
            <div className="flex items-center gap-4">
              <div className="p-3 rounded-2xl bg-gradient-to-br from-violet-600/30 to-cyan-500/30 border border-white/10 text-cyan-300 shadow-lg shadow-violet-500/10">
                <Sparkles className="w-6 h-6" />
              </div>
              <div>
                <h2 className="text-sm font-mono font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  Codebase Self-Healing Trigger Engine
                </h2>
                <p className="text-xs text-zinc-400 mt-0.5">
                  Select a built-in benchmark target or provide your own local project directory path
                </p>
              </div>
            </div>

            {/* Mode Switcher Buttons */}
            <div className="flex items-center gap-2 bg-[#090a0f] p-1.5 rounded-2xl border border-white/[0.08]">
              <button
                onClick={() => setMode('sample')}
                className={`px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all ${
                  mode === 'sample'
                    ? 'bg-gradient-to-r from-violet-600/40 to-cyan-500/40 text-white border border-white/20 shadow-md shadow-violet-500/10'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                Built-in Benchmarks
              </button>
              <button
                onClick={() => setMode('custom')}
                className={`px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all ${
                  mode === 'custom'
                    ? 'bg-gradient-to-r from-violet-600/40 to-cyan-500/40 text-white border border-white/20 shadow-md shadow-violet-500/10'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                Dynamic Custom Repository
              </button>
            </div>
          </div>

          {/* Mode A: Built-in Benchmark Cards */}
          {mode === 'sample' && (
            <div className="mt-6">
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-mono text-zinc-400 uppercase tracking-wider">
                  Select Target Sample Codebase:
                </span>
                <button
                  onClick={handleTriggerIncident}
                  disabled={isLoading}
                  className="bg-gradient-to-r from-violet-600 via-cyan-500 to-emerald-400 hover:opacity-90 text-[#070709] font-extrabold text-xs px-6 py-3 rounded-2xl flex items-center gap-2.5 transition-all shadow-xl shadow-violet-500/20 disabled:opacity-50 font-mono tracking-wide"
                >
                  <Play className="w-4 h-4 fill-[#070709]" />
                  {isLoading ? 'EXECUTING SELF-HEALING...' : 'TRIGGER SELF-HEALING FIX'}
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {sampleRepos.map((repo) => {
                  const isSelected = selectedRepo === repo.id;
                  return (
                    <button
                      key={repo.id}
                      onClick={() => setSelectedRepo(repo.id)}
                      className={`p-4 rounded-2xl border text-left transition-all duration-200 ${
                        isSelected
                          ? 'bg-gradient-to-r from-violet-950/40 via-cyan-950/40 to-slate-900/60 border-cyan-500/50 shadow-lg shadow-cyan-500/10'
                          : 'bg-zinc-900/40 border-white/[0.06] hover:border-white/20'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <Code2 className={`w-4 h-4 ${isSelected ? 'text-cyan-400' : 'text-zinc-500'}`} />
                          <span className="font-mono font-bold text-xs text-white">{repo.title}</span>
                        </div>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.04] text-zinc-400 border border-white/[0.06]">
                          {repo.type}
                        </span>
                      </div>
                      <div className="text-[11px] font-mono text-rose-300 font-semibold mb-1 flex items-center gap-1.5">
                        <AlertTriangle className="w-3 h-3 text-rose-400 shrink-0" /> {repo.bug}
                      </div>
                      <p className="text-[11px] text-zinc-400 font-sans leading-snug">{repo.description}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Mode B: Dynamic Custom Repository Form */}
          {mode === 'custom' && (
            <div className="mt-6 space-y-4">
              <div>
                <label className="text-xs font-mono text-cyan-300 font-semibold block mb-2 flex items-center gap-2">
                  <FolderCog className="w-4 h-4 text-cyan-400" />
                  Local Repository Absolute Directory Path:
                </label>
                <input
                  type="text"
                  placeholder="e.g. C:\Users\Admin\Desktop\MyProject or /home/user/myproject"
                  value={customRepoPath}
                  onChange={(e) => setCustomRepoPath(e.target.value)}
                  className="w-full bg-[#090a0f] border border-white/[0.08] rounded-2xl px-4 py-3 text-xs font-mono text-white focus:outline-none focus:border-cyan-500/60"
                />
                <p className="text-[11px] text-zinc-500 font-mono mt-1">
                  Fixate will dynamically parse AST symbols, construct call graph, and verify fixes in Docker for this directory.
                </p>
              </div>

              <div>
                <label className="text-xs font-mono text-zinc-400 font-semibold block mb-2 flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-emerald-400" />
                  Optional Pytest Error Traceback (Leave blank to auto-run `pytest` in directory):
                </label>
                <textarea
                  rows={3}
                  placeholder="Paste Pytest traceback output or stack trace (Optional)..."
                  value={customPytestLog}
                  onChange={(e) => setCustomPytestLog(e.target.value)}
                  className="w-full bg-[#090a0f] border border-white/[0.08] rounded-2xl p-4 text-xs font-mono text-white focus:outline-none focus:border-cyan-500/60"
                />
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={handleTriggerIncident}
                  disabled={isLoading || (!customRepoPath.trim() && !customPytestLog.trim())}
                  className="bg-gradient-to-r from-violet-600 via-cyan-500 to-emerald-400 hover:opacity-90 text-[#070709] font-extrabold text-xs px-8 py-3.5 rounded-2xl flex items-center gap-2.5 transition-all shadow-xl shadow-violet-500/20 disabled:opacity-50 font-mono tracking-wide"
                >
                  <Play className="w-4 h-4 fill-[#070709]" />
                  {isLoading ? 'EXECUTING DYNAMIC FIX...' : 'RUN DYNAMIC SELF-HEALING FIX'}
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
            customRepoPath={mode === 'custom' && customRepoPath.trim() ? customRepoPath.trim() : undefined}
          />
        )}

        {activeTab === 'history' && <IncidentHistory events={telemetryEvents} />}

        {activeTab === 'eval' && <EvalCharts />}
      </main>

      <footer className="border-t border-white/[0.06] py-6 text-center text-xs text-zinc-500 font-mono">
        Fixate — Dynamic Autonomous Self-Healing CI & Codebase Agent • Sandboxed Container Execution
      </footer>
    </div>
  );
};
