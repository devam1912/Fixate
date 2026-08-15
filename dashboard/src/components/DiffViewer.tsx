import React, { useState } from 'react';
import { FileCode, Sparkles, CheckCircle, AlertTriangle, Copy, Check } from 'lucide-react';
import { GeneratedPatch, RiskAssessment } from '../types';

interface DiffViewerProps {
  patch?: GeneratedPatch;
  risk?: RiskAssessment;
  failureReport?: string | null;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ patch, risk, failureReport }) => {
  const [copied, setCopied] = useState(false);

  if (!patch) {
    if (failureReport) {
      return (
        <div className="glass-card p-6 rounded-3xl border border-rose-900/70 bg-rose-950/20 my-6">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-xl bg-rose-500/10 border border-rose-500/25 text-rose-300 shrink-0">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-xs font-mono font-semibold uppercase text-rose-200">Repair stopped before a patch was generated</h3>
              <pre className="mt-3 whitespace-pre-wrap text-xs leading-relaxed text-rose-100/85 font-mono bg-black/35 border border-rose-900/60 rounded-xl p-4 max-h-[360px] overflow-auto">
                {failureReport}
              </pre>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="glass-card p-10 rounded-3xl border border-white/[0.08] text-center text-zinc-500 my-6">
        <FileCode className="w-10 h-10 mx-auto mb-3 text-zinc-600 opacity-40" />
        <h3 className="text-xs font-mono font-semibold uppercase text-zinc-400">No Patch Generated Yet</h3>
        <p className="text-xs text-zinc-500 mt-1">Scan a repository, select a failure, then click Fix selected.</p>
      </div>
    );
  }

  const diffLines = patch.unified_diff.split('\n');

  const handleCopy = () => {
    navigator.clipboard.writeText(patch.unified_diff);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="glass-card rounded-3xl border border-white/[0.08] overflow-hidden my-6 shadow-2xl">
      {/* Diff Header Bar */}
      <div className="bg-[#0f1017]/90 px-6 py-4 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-violet-500/10 border border-violet-500/20 text-violet-400">
            <FileCode className="w-4 h-4" />
          </div>
          <div>
            <h3 className="font-mono text-xs font-bold text-white tracking-wide">{patch.target_file}</h3>
            <p className="text-[11px] text-zinc-400 font-mono">
              <span className="text-emerald-400 font-semibold">+{patch.lines_changed} lines</span> changed via Unified Diff Machine Engine
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {risk && (
            <div>
              {risk.is_risky ? (
                <span className="text-xs px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-300 border border-amber-500/30 flex items-center gap-2 font-mono font-medium">
                  <AlertTriangle className="w-3.5 h-3.5" /> High Risk — Approval Required
                </span>
              ) : (
                <span className="text-xs px-3 py-1.5 rounded-xl bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 flex items-center gap-2 font-mono font-medium">
                  <CheckCircle className="w-3.5 h-3.5" /> Verified & Pre-Approved
                </span>
              )}
            </div>
          )}

          <button
            onClick={handleCopy}
            className="p-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-zinc-300 text-xs flex items-center gap-1.5 transition-all"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span className="font-mono text-[11px]">{copied ? 'Copied!' : 'Copy Diff'}</span>
          </button>
        </div>
      </div>

      {/* Rationale Explanation Callout */}
      <div className="p-4 bg-[#14151f]/80 border-b border-white/[0.08] text-xs font-sans text-zinc-300 flex items-start gap-3">
        <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 shrink-0 mt-0.5">
          <Sparkles className="w-3.5 h-3.5" />
        </div>
        <div>
          <span className="font-semibold text-cyan-300 font-mono">LLM Patch Rationale:</span>{' '}
          <span className="text-zinc-300">{patch.explanation}</span>
        </div>
      </div>

      {/* Unified Diff Line View */}
      <div className="p-4 bg-[#08080c] font-mono text-xs overflow-x-auto max-h-[420px] leading-relaxed">
        {diffLines.map((line, idx) => {
          let lineStyle = 'text-zinc-400';
          let bgStyle = '';

          if (line.startsWith('+') && !line.startsWith('+++')) {
            lineStyle = 'text-emerald-300 font-medium';
            bgStyle = 'bg-emerald-950/25 border-l-2 border-emerald-500';
          } else if (line.startsWith('-') && !line.startsWith('---')) {
            lineStyle = 'text-rose-300 font-medium';
            bgStyle = 'bg-rose-950/25 border-l-2 border-rose-500';
          } else if (line.startsWith('@@')) {
            lineStyle = 'text-cyan-400 font-semibold';
            bgStyle = 'bg-cyan-950/30 py-1';
          }

          return (
            <div key={idx} className={`px-4 py-0.5 rounded-sm flex items-center gap-4 ${lineStyle} ${bgStyle}`}>
              <span className="text-[10px] text-zinc-600 select-none w-8 text-right font-mono">{idx + 1}</span>
              <span className="whitespace-pre">{line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
