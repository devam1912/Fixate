import React from 'react';
import { Terminal, CheckCircle2, XCircle, Loader2, AlertCircle } from 'lucide-react';
import { TelemetryEvent } from '../types';

interface IncidentHistoryProps {
  events: TelemetryEvent[];
}

export const IncidentHistory: React.FC<IncidentHistoryProps> = ({ events }) => {
  return (
    <div className="glass-card p-6 rounded-3xl border border-white/[0.08] my-6">
      <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/[0.08]">
        <h2 className="text-xs font-mono font-bold uppercase tracking-widest text-emerald-400 flex items-center gap-2">
          <Terminal className="w-4 h-4 text-emerald-400" />
          Telemetry Audit Log Feed ({events.length} Structured Events)
        </h2>
        <span className="text-[10px] font-mono text-zinc-500">Live SSE Stream</span>
      </div>

      {events.length === 0 ? (
        <div className="text-center py-10 text-zinc-500 font-mono text-xs">
          No active telemetry events recorded yet. Trigger a run above to view live execution traces.
        </div>
      ) : (
        <div className="space-y-3 font-mono text-xs max-h-[480px] overflow-y-auto pr-2">
          {events.map((evt, idx) => (
            <div
              key={idx}
              className="p-3.5 rounded-2xl bg-[#08080c] border border-white/[0.06] flex items-start gap-3 transition-all hover:border-white/[0.12]"
            >
              <div className="mt-0.5 shrink-0">
                {evt.result === 'SUCCESS' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                {evt.result === 'FAILURE' && <XCircle className="w-4 h-4 text-rose-400" />}
                {evt.result === 'IN_PROGRESS' && <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />}
                {evt.result === 'REQUIRES_APPROVAL' && <AlertCircle className="w-4 h-4 text-amber-400" />}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between text-[11px] mb-1">
                  <span className="font-bold text-violet-300">
                    [{evt.agent}] <span className="text-white font-medium">{evt.action}</span>
                  </span>
                  <span className="text-zinc-500 text-[10px]">{new Date(evt.timestamp).toLocaleTimeString()}</span>
                </div>
                <div className="text-zinc-300 text-[11px] truncate">
                  Input: <span className="text-zinc-400">{evt.input_summary}</span>
                </div>
                <div className="text-zinc-400 text-[11px] truncate mt-0.5">
                  Output: <span className="text-zinc-200">{evt.output_summary}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
