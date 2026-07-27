import React from 'react';
import { Search, Database, Code, ShieldCheck, CheckCircle2, XCircle, Clock, AlertTriangle } from 'lucide-react';
import { IncidentSummary } from '../types';

interface PipelineFlowProps {
  summary: IncidentSummary | null;
}

export const PipelineFlow: React.FC<PipelineFlowProps> = ({ summary }) => {
  const currentState = summary?.state || 'IDLE';

  const stages = [
    {
      id: 'LOCALIZING',
      name: 'Failure Localization',
      description: 'AST Graph Backward Walk & LLM Plausibility Ranker',
      icon: Search,
    },
    {
      id: 'RETRIEVING',
      name: 'Code-RAG Retrieval',
      description: 'ChromaDB AST Chunker & Past Fix History Lookup',
      icon: Database,
    },
    {
      id: 'PATCHING',
      name: 'Patch Generation',
      description: 'Minimal Machine-Applicable Unified Diff Engine',
      icon: Code,
    },
    {
      id: 'VERIFYING',
      name: 'Sandbox Verification',
      description: `Docker Isolated Container Test Runner (Attempt ${summary?.total_attempts || 0}/3)`,
      icon: Clock,
    },
    {
      id: 'CHECKING_SAFETY',
      name: 'Safety & Approval Gate',
      description: 'Heuristic Risk Evaluator for Auth / Payment / Schema',
      icon: ShieldCheck,
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
    <div className="glass-panel p-6 rounded-2xl border border-slate-800 my-6">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-6 flex items-center justify-between">
        <span>Agent Execution Pipeline Flow</span>
        {summary && (
          <span className="font-mono text-xs text-slate-400 font-normal">
            Incident ID: <span className="text-cyan-400">{summary.incident_id}</span>
          </span>
        )}
      </h2>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4 relative">
        {stages.map((stage, idx) => {
          const status = getStageStatus(stage.id);
          const Icon = stage.icon;

          let badgeColor = 'bg-slate-900 border-slate-800 text-slate-500';
          let iconColor = 'text-slate-500';

          if (status === 'completed') {
            badgeColor = 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300';
            iconColor = 'text-emerald-400';
          } else if (status === 'active') {
            badgeColor = 'bg-cyan-950/60 border-cyan-500/50 text-cyan-300 shadow-lg shadow-cyan-500/10 animate-pulse';
            iconColor = 'text-cyan-400';
          } else if (status === 'failed') {
            badgeColor = 'bg-rose-950/40 border-rose-500/30 text-rose-300';
            iconColor = 'text-rose-400';
          }

          return (
            <div
              key={stage.id}
              className={`p-4 rounded-xl border ${badgeColor} transition-all duration-300 flex flex-col justify-between`}
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className={`p-2 rounded-lg bg-slate-950/50 border border-slate-800 ${iconColor}`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <span className="font-mono text-[10px] font-bold text-slate-500">0{idx + 1}</span>
                </div>
                <h3 className="text-xs font-semibold text-slate-200 mb-1">{stage.name}</h3>
                <p className="text-[11px] text-slate-400 leading-tight">{stage.description}</p>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-800/50 flex items-center justify-between">
                <span className="text-[10px] uppercase font-mono font-medium">
                  {status === 'completed' && <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3"/> Done</span>}
                  {status === 'active' && <span className="text-cyan-400 flex items-center gap-1"><Clock className="w-3 h-3 animate-spin"/> Executing</span>}
                  {status === 'failed' && <span className="text-rose-400 flex items-center gap-1"><XCircle className="w-3 h-3"/> Failed</span>}
                  {status === 'pending' && <span className="text-slate-500">Waiting</span>}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
