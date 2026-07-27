import React from 'react';
import { FileCode, Sparkles, CheckCircle, AlertTriangle } from 'lucide-react';
import { GeneratedPatch, RiskAssessment } from '../types';

interface DiffViewerProps {
  patch?: GeneratedPatch;
  risk?: RiskAssessment;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ patch, risk }) => {
  if (!patch) {
    return (
      <div className="glass-panel p-8 rounded-2xl border border-slate-800 text-center text-slate-500">
        <FileCode className="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p className="text-xs">No proposed diff patch generated yet.</p>
      </div>
    );
  }

  const diffLines = patch.unified_diff.split('\n');

  return (
    <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden my-6">
      <div className="bg-slate-900/80 px-6 py-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileCode className="w-4 h-4 text-cyan-400" />
          <span className="font-mono text-xs font-semibold text-slate-200">{patch.target_file}</span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400">
            {patch.lines_changed} lines changed
          </span>
        </div>

        {risk && (
          <div className="flex items-center gap-2">
            {risk.is_risky ? (
              <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-1.5 font-medium">
                <AlertTriangle className="w-3.5 h-3.5" /> High Risk — Requires Approval
              </span>
            ) : (
              <span className="text-xs px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5 font-medium">
                <CheckCircle className="w-3.5 h-3.5" /> Verified & Approved
              </span>
            )}
          </div>
        )}
      </div>

      <div className="p-4 bg-slate-950/60 text-xs font-mono border-b border-slate-800 text-slate-300 flex items-start gap-2">
        <Sparkles className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-cyan-300">Patch Rationale:</span> {patch.explanation}
        </div>
      </div>

      <div className="p-4 bg-slate-950 font-mono text-xs overflow-x-auto max-h-[350px]">
        {diffLines.map((line, idx) => {
          let lineStyle = 'text-slate-400';
          let bgStyle = '';

          if (line.startswith('+') && !line.startswith('+++')) {
            lineStyle = 'text-emerald-400 font-medium';
            bgStyle = 'bg-emerald-950/30 border-l-2 border-emerald-500';
          } else if (line.startswith('-') && !line.startswith('---')) {
            lineStyle = 'text-rose-400 font-medium';
            bgStyle = 'bg-rose-950/30 border-l-2 border-rose-500';
          } else if (line.startswith('@@')) {
            lineStyle = 'text-cyan-400 font-semibold';
            bgStyle = 'bg-cyan-950/20';
          }

          return (
            <div key={idx} className={`px-3 py-0.5 leading-relaxed ${lineStyle} ${bgStyle}`}>
              {line}
            </div>
          );
        })}
      </div>
    </div>
  );
};
