import React from 'react';
import { Activity, GitBranch, BarChart3, Terminal, Zap, Shield, Command } from 'lucide-react';

interface NavbarProps {
  activeTab: 'live' | 'history' | 'graph' | 'eval';
  setActiveTab: (tab: 'live' | 'history' | 'graph' | 'eval') => void;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, setActiveTab }) => {
  return (
    <header className="border-b border-white/[0.08] bg-[#09090d]/80 backdrop-blur-xl sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        {/* Brand Logo & System Status */}
        <div className="flex items-center gap-4">
          <div className="relative group flex items-center gap-3 cursor-pointer">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-violet-600 via-cyan-500 to-emerald-400 p-[1px] shadow-lg shadow-violet-500/20">
              <div className="w-full h-full bg-[#0b0c10] rounded-[11px] flex items-center justify-center">
                <Zap className="w-4 h-4 text-cyan-400 fill-cyan-400/20" />
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-white tracking-tight text-base font-sans">
                  FIXATE
                </span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20 font-semibold tracking-wider">
                  SYSTEM ACTIVE
                </span>
              </div>
              <p className="text-[11px] text-zinc-400 font-mono flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                Autonomous Self-Healing CI Engine
              </p>
            </div>
          </div>
        </div>

        {/* Floating Navigation Tabs */}
        <nav className="flex items-center gap-1 bg-[#121319]/90 p-1.5 rounded-2xl border border-white/[0.08] shadow-inner">
          <button
            onClick={() => setActiveTab('live')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all duration-200 ${
              activeTab === 'live'
                ? 'bg-gradient-to-r from-violet-600/30 to-cyan-500/30 text-white border border-white/20 shadow-lg shadow-violet-500/10'
                : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <Activity className="w-3.5 h-3.5 text-cyan-400" />
            Live Pipeline
          </button>

          <button
            onClick={() => setActiveTab('graph')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all duration-200 ${
              activeTab === 'graph'
                ? 'bg-gradient-to-r from-violet-600/30 to-cyan-500/30 text-white border border-white/20 shadow-lg shadow-violet-500/10'
                : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <GitBranch className="w-3.5 h-3.5 text-violet-400" />
            AST Graph
          </button>

          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all duration-200 ${
              activeTab === 'history'
                ? 'bg-gradient-to-r from-violet-600/30 to-cyan-500/30 text-white border border-white/20 shadow-lg shadow-violet-500/10'
                : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <Terminal className="w-3.5 h-3.5 text-emerald-400" />
            Audit Logs
          </button>

          <button
            onClick={() => setActiveTab('eval')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all duration-200 ${
              activeTab === 'eval'
                ? 'bg-gradient-to-r from-violet-600/30 to-cyan-500/30 text-white border border-white/20 shadow-lg shadow-violet-500/10'
                : 'text-zinc-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5 text-amber-400" />
            Eval Scorecard
          </button>
        </nav>

        {/* Right Status Badge */}
        <div className="hidden sm:flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03] border border-white/[0.08] text-xs text-zinc-400 font-mono">
            <Shield className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-zinc-300 font-medium">Sandbox Docker Isolation</span>
          </div>
        </div>
      </div>
    </header>
  );
};
