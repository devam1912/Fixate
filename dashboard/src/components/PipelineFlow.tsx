import React from 'react';
import { Search, Database, Code2, Cpu, ShieldAlert, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
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
      description: 'AST Backward Walk & Candidate Ranker',
      icon: Search,
    },
    {
      id: 'RETRIEVING',
      name: '02. Code-RAG',
      description: 'AST Vector Chunker & Fix History',
      icon: Database,
    },
    {
      id: 'PATCHING',
      name: '03. Patch Gen',
      description: 'Unified Machine Diff Applicator',
      icon: Code2,
    },
    {
      id: 'VERIFYING',
      name: '04. Verification',
      description: `Docker Sandbox Execution (Attempt ${summary?.total_attempts || 0}/3)`,
      icon: Cpu,
    },
    {
      id: 'CHECKING_SAFETY',
      name: '05. Safety Gate',
      description: 'Auth / Payment / Schema Risk Audit',
      icon: ShieldAlert,
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
    <div className="glass-card p-6 rounded-2xl border border-zinc-800 my-6">
      {/* Top Header info */}
      <div className="flex items-center justify-between pb-4 mb-5 border-b border-zinc-800">
        <div>
          <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-zinc-300 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            Agentic Orchestration Pipeline Flow
          </h2>
          <p className="text-xs text-zinc-500 mt-0.5 font-mono">
            5-Stage Autonomous Root-Cause Localization & Sandboxed Patch Repair Loop
          </p>
        </div>

        {summary && (
          <div className="flex items-center gap-3 font-mono text-xs">
            <span className="px-3 py-1 rounded bg-zinc-900 border border-zinc-800 text-zinc-400">
              Incident ID: <span className="text-white font-bold">{summary.incident_id}</span>
            </span>
            <span className="px-3 py-1 rounded bg-zinc-900 border border-zinc-800 text-zinc-300 font-semibold">
              State: {summary.state}
            </span>
          </div>
        )}
      </div>

      {/* 5-Stage Visual Node Flow */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        {stages.map((stage, idx) => {
          const status = getStageStatus(stage.id);
          const Icon = status === 'active' ? Loader2 : stage.icon;

          let cardStyle = 'bg-zinc-950 border-zinc-800/80 text-zinc-600';
          let iconStyle = 'text-zinc-600 bg-zinc-900 border-zinc-800';
          let titleStyle = 'text-zinc-400';

          if (status === 'completed') {
            cardStyle = 'bg-zinc-900/60 border-emerald-500/40 text-emerald-400';
            iconStyle = 'text-emerald-400 bg-emerald-950/40 border-emerald-500/30';
            titleStyle = 'text-emerald-300 font-bold';
          } else if (status === 'active') {
            cardStyle = 'bg-zinc-900 border-white/30 text-white shadow-md';
            iconStyle = 'text-white bg-zinc-800 border-white/20 animate-spin';
            titleStyle = 'text-white font-bold';
          } else if (status === 'failed') {
            cardStyle = 'bg-zinc-900/60 border-rose-500/40 text-rose-400';
            iconStyle = 'text-rose-400 bg-rose-950/40 border-rose-500/30';
            titleStyle = 'text-rose-300 font-bold';
          }

          return (
            <div
              key={stage.id}
              className={`p-4 rounded-xl border transition-all duration-200 flex flex-col justify-between ${cardStyle}`}
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className={`p-2 rounded-lg border ${iconStyle}`}>
                    <Icon className={`w-4 h-4 ${status === 'active' ? 'animate-spin' : ''}`} />
                  </div>
                  <span className="text-[10px] font-mono font-bold text-zinc-600">
                    STEP 0{idx + 1}
                  </span>
                </div>

                <h3 className={`text-xs font-mono tracking-tight mb-1 ${titleStyle}`}>
                  {stage.name}
                </h3>
                <p className="text-[11px] text-zinc-500 font-sans leading-snug">
                  {stage.description}
                </p>
              </div>

              {/* Bottom Status pill */}
              <div className="mt-4 pt-3 border-t border-zinc-800/60 flex items-center justify-between">
                <span className="text-[10px] font-mono uppercase font-medium">
                  {status === 'completed' && (
                    <span className="text-emerald-400 flex items-center gap-1.5 font-bold">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Passed
                    </span>
                  )}
                  {status === 'active' && (
                    <span className="text-white flex items-center gap-1.5 font-bold">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Running...
                    </span>
                  )}
                  {status === 'failed' && (
                    <span className="text-rose-400 flex items-center gap-1.5 font-bold">
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
