import React from 'react';
import { Activity, GitBranch, BarChart3, ShieldCheck, Terminal } from 'lucide-react';

interface NavbarProps {
  activeTab: 'live' | 'history' | 'graph' | 'eval';
  setActiveTab: (tab: 'live' | 'history' | 'graph' | 'eval') => void;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, setActiveTab }) => {
  return (
    <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-bold text-lg">
            F
          </div>
          <div>
            <h1 className="font-semibold text-slate-100 tracking-tight text-base flex items-center gap-2">
              Fixate <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-mono">v0.1.0 SRE</span>
            </h1>
            <p className="text-xs text-slate-400">Self-Healing CI & Codebase Agent</p>
          </div>
        </div>

        <nav className="flex items-center gap-1 bg-slate-900/60 p-1 rounded-xl border border-slate-800">
          <button
            onClick={() => setActiveTab('live')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'live'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Activity className="w-3.5 h-3.5" /> Live Incident
          </button>
          <button
            onClick={() => setActiveTab('graph')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'graph'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <GitBranch className="w-3.5 h-3.5" /> AST Code Graph
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'history'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" /> Incident Log
          </button>
          <button
            onClick={() => setActiveTab('eval')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'eval'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" /> Eval Harness
          </button>
        </nav>
      </div>
    </header>
  );
};
