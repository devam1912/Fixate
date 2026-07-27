import React from 'react';
import { Search, Database, Code2, ShieldAlert, CheckCircle2, XCircle, Loader2, Play } from 'lucide-react';
import { IncidentSummary } from '../types';

interface PipelineFlowProps {
  summary: IncidentSummary | null;
}

export const PipelineFlow: React.FC<PipelineFlowProps> = ({ summary }) => {
  const currentState = summary?.state || 'IDLE';

  const stages = [
    {
      id: 'LOCALIZING',
      name: '01. Localization',
      shortName: 'Localize',
      description: 'AST Backward Walk & Candidate Ranker',
      icon: Search,
      color: 'from-violet-500 to-indigo-500',
    },
    {
      id: 'RETRIEVING',
      name: '02. Code-RAG',
      shortName: 'Retrieve',
      description: 'AST Vector Chunker & Fix History',
      icon: Database,
      color: 'from-cyan-500 to-blue-500',
    },
    {
      id: 'PATCHING',
      name: '03. Patch Gen',
      shortName: 'Patch',
      description: 'Unified Machine Diff Applicator',
      icon: Code2,
      color: 'from-teal-500 to-emerald-500',
    },
    {
      id: 'VERIFYING',
      name: '04. Verification',
      shortName: 'Verify',
      description: `Docker Sandbox Execution (Attempt ${summary?.total_attempts || 0}/3)`,
      icon: Loader2,
      color: 'from-amber-500 to-orange-500',
    },
    {
      id: 'CHECKING_SAFETY',
      name: '05. Safety Gate',
      shortName: 'Safety',
      description: 'Auth / Payment / Schema Risk Audit',
      icon: ShieldAlert,
      color: 'from-rose-500 to-pink-500',
    },
  ];

  const getStageStatus = (stageId: string) => {
    if (!summary || summary.state === 'IDLE') return 'pending';

    const stateOrder = ['LOCALIZING', 'RETRIEVING', 'PATCHING', 'VERIFYING', 'CHECKING_SAFETY'];
    const currentIdx = stateOrder.indexOf(currentState);
    const stageIdx = stateOrder.indexOf(stageId);

    if (summary.state === 'FAILED') {
      if (stageIdx === currentIdx) return 'failed';
      if (stageIdx < currentIdx) return 'completed';
      return 'pending';
    }

    if (summary.state === 'COMPLETED' || summary.state === 'PENDING_APPROVAL') return 'completed';

    if (stageIdx < currentIdx) return 'completed';
    if (stageIdx === currentIdx) return 'active';
    return 'pending';
  };

  return (
    <div className="glass-card p-6 rounded-3xl border border-white/[0.08] relative overflow-hidden my-6">
      {/* Top Header info */}
      <div className="flex items-center justify-between pb-6 mb-6 border-b border-white/[0.08]">
        <div>
          <h2 className="text-xs font-mono font-semibold uppercase tracking-widest text-violet-400 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-violet-400 animate-ping" />
            Live Agentic Orchestration Pipeline
          </h2>
          <p className="text-xs text-zinc-400 mt-1 font-sans">
            5-Stage Autonomous Root-Cause Localization & Sandboxed Patch Repair Loop
          </p>
        </div>

        {summary && (
          <div className="flex items-center gap-3 font-mono text-xs">
            <span className="px-3 py-1 rounded-xl bg-white/[0.04] border border-white/[0.08] text-zinc-300">
              ID: <span className="text-cyan-400 font-bold">{summary.incident_id}</span>
            </span>
            <span className="px-3 py-1 rounded-xl bg-violet-500/10 border border-violet-500/20 text-violet-300 font-semibold">
              State: {summary.state}
            </span>
          </div>
        )}
      </div>

      {/* 5-Stage Visual Node Flow */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4 relative">
        {stages.map((stage, idx) => {
          const status = getStageStatus(stage.id);
          const Icon = stage.icon;

          let cardStyle = 'bg-zinc-900/40 border-white/[0.06] text-zinc-500';
          let iconStyle = 'text-zinc-600 bg-white/[0.02] border-white/[0.05]';
          let titleStyle = 'text-zinc-400';

          if (status === 'completed') {
            cardStyle = 'bg-emerald-950/20 border-emerald-500/30 text-emerald-300 shadow-lg shadow-emerald-500/5';
            iconStyle = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
            titleStyle = 'text-emerald-200 font-bold';
          } else if (status === 'active') {
            cardStyle = 'bg-cyan-950/40 border-cyan-500/50 text-cyan-200 glass-card-glow animate-neon-pulse';
            iconStyle = 'text-cyan-300 bg-cyan-500/20 border-cyan-500/40 animate-spin';
            titleStyle = 'text-white font-bold';
          } else if (status === 'failed') {
            cardStyle = 'bg-rose-950/30 border-rose-500/40 text-rose-300';
            iconStyle = 'text-rose-400 bg-rose-500/10 border-rose-500/20';
            titleStyle = 'text-rose-200 font-bold';
          }

          return (
            <div
              key={stage.id}
              className={`p-4 rounded-2xl border transition-all duration-300 relative flex flex-col justify-between ${cardStyle}`}
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className={`p-2.5 rounded-xl border ${iconStyle}`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <span className="text-[10px] font-mono font-bold text-zinc-500">
                    STEP 0{idx + 1}
                  </span>
                </div>

                <h3 className={`text-xs font-sans tracking-tight mb-1 ${titleStyle}`}>
                  {stage.name}
                </h3>
                <p className="text-[11px] text-zinc-400 font-sans leading-snug">
                  {stage.description}
                </p>
              </div>

              {/* Bottom Status pill */}
              <div className="mt-5 pt-3 border-t border-white/[0.06] flex items-center justify-between">
                <span className="text-[10px] font-mono uppercase font-semibold">
                  {status === 'completed' && (
                    <span className="text-emerald-400 flex items-center gap-1.5">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Passed
                    </span>
                  )}
                  {status === 'active' && (
                    <span className="text-cyan-300 flex items-center gap-1.5">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Running...
                    </span>
                  )}
                  {status === 'failed' && (
                    <span className="text-rose-400 flex items-center gap-1.5">
                      <XCircle className="w-3.5 h-3.5" /> Failed
                    </span>
                  )}
                  {status === 'pending' && <span className="text-zinc-600">Pending</span>}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
