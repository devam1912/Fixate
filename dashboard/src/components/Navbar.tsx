import React from 'react';
import { Activity, GitBranch, BarChart3, Terminal, Shield, ScanSearch } from 'lucide-react';

interface NavbarProps {
  activeTab: 'workbench' | 'live' | 'history' | 'graph' | 'eval';
  setActiveTab: (tab: 'workbench' | 'live' | 'history' | 'graph' | 'eval') => void;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, setActiveTab }) => {
  return (
    <header className="border-b border-zinc-800/80 bg-black/90 sticky top-0 z-50 backdrop-blur">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        {/* Brand Logo */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-zinc-900 border border-zinc-700 flex items-center justify-center text-white font-mono font-extrabold text-sm shadow-[0_0_24px_rgba(16,185,129,0.16)]">
            Fx
          </div>
          <div>
            <h1 className="font-bold text-white tracking-tight text-sm flex items-center gap-2">
              Fixate <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-zinc-800 font-mono">v0.1.0</span>
            </h1>
            <p className="text-[11px] text-zinc-500">Failure triage, verified repairs, pull requests</p>
          </div>
        </div>

        {/* Minimalist Tab Navigation */}
        <nav className="flex items-center gap-1 bg-zinc-950 p-1 rounded-xl border border-zinc-800">
          <button
            onClick={() => setActiveTab('workbench')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'workbench'
                ? 'bg-zinc-800 text-white border border-zinc-700 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
            }`}
          >
            <ScanSearch className="w-3.5 h-3.5 text-emerald-400" />
            Workbench
          </button>

          <button
            onClick={() => setActiveTab('live')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'live'
                ? 'bg-zinc-800 text-white border border-zinc-700 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
            }`}
          >
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            Pipeline
          </button>

          <button
            onClick={() => setActiveTab('graph')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'graph'
                ? 'bg-zinc-800 text-white border border-zinc-700 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
            }`}
          >
            <GitBranch className="w-3.5 h-3.5 text-zinc-400" />
            AST Graph
          </button>

          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'history'
                ? 'bg-zinc-800 text-white border border-zinc-700 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
            }`}
          >
            <Terminal className="w-3.5 h-3.5 text-zinc-400" />
            Audit Logs
          </button>

          <button
            onClick={() => setActiveTab('eval')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === 'eval'
                ? 'bg-zinc-800 text-white border border-zinc-700 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5 text-zinc-400" />
            Scorecard
          </button>
        </nav>

        {/* Sandbox Docker Status */}
        <div className="hidden sm:flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-xs text-zinc-400 font-mono">
            <Shield className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-zinc-300">Docker Sandbox</span>
          </div>
        </div>
      </div>
    </header>
  );
};
