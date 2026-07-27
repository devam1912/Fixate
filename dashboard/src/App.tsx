import React, { useState } from 'react';
import { Navbar } from './components/Navbar';
import { PipelineFlow } from './components/PipelineFlow';
import { DiffViewer } from './components/DiffViewer';
import { GraphViewer } from './components/GraphViewer';
import { EvalCharts } from './components/EvalCharts';
import { IncidentHistory } from './components/IncidentHistory';
import { IncidentSummary, TelemetryEvent } from './types';
import { Play, ShieldAlert, Sparkles } from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'live' | 'history' | 'graph' | 'eval'>('live');
  const [selectedRepo, setSelectedRepo] = useState<string>('calculator_app');
  const [incidentSummary, setIncidentSummary] = useState<IncidentSummary | null>(null);
  const [telemetryEvents, setTelemetryEvents] = useState<TelemetryEvent[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const handleTriggerIncident = async () => {
    setIsLoading(true);
    setTelemetryEvents([]);
    try {
      const res = await fetch('/api/incident/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_name: selectedRepo, human_approval_required: true }),
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

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
        {/* Controls Bar */}
        <div className="glass-panel p-4 rounded-2xl border border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            <div>
              <h2 className="text-xs font-semibold text-slate-200">Target Sample Codebase</h2>
              <p className="text-[11px] text-slate-400">Select a broken repository target to trigger live AI self-healing fix</p>
            </div>
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto">
            <select
              value={selectedRepo}
              onChange={(e) => setSelectedRepo(e.target.value)}
              className="bg-slate-900 border border-slate-700 text-slate-200 text-xs rounded-xl px-3 py-2 focus:outline-none focus:border-cyan-500 font-mono"
            >
              <option value="calculator_app">calculator_app (Discount Math Error)</option>
              <option value="ecommerce_api">ecommerce_api (Dict Attribute Error)</option>
              <option value="data_processor">data_processor (Off-by-One Loop Error)</option>
            </select>

            <button
              onClick={handleTriggerIncident}
              disabled={isLoading}
              className="bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs px-4 py-2 rounded-xl flex items-center gap-2 transition-all shadow-md shadow-cyan-500/20 disabled:opacity-50 shrink-0"
            >
              <Play className="w-3.5 h-3.5 fill-slate-950" />
              {isLoading ? 'Executing Self-Healing...' : 'Trigger Self-Healing Fix'}
            </button>
          </div>
        </div>

        {activeTab === 'live' && (
          <div>
            <PipelineFlow summary={incidentSummary} />
            {incidentSummary?.verified_patch && (
              <DiffViewer patch={incidentSummary.verified_patch} risk={incidentSummary.risk_assessment} />
            )}
            <IncidentHistory events={telemetryEvents} />
          </div>
        )}

        {activeTab === 'graph' && <GraphViewer repoName={selectedRepo} />}

        {activeTab === 'history' && <IncidentHistory events={telemetryEvents} />}

        {activeTab === 'eval' && <EvalCharts />}
      </main>

      <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500 font-mono">
        Fixate Self-Healing CI Agent — Autonomous Sandboxed Code Repair Engine
      </footer>
    </div>
  );
};
