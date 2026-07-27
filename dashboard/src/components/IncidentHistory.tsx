import React from 'react';
import { Terminal, CheckCircle2, XCircle, Clock } from 'lucide-react';
import { TelemetryEvent } from '../types';

interface IncidentHistoryProps {
  events: TelemetryEvent[];
}

export const IncidentHistory: React.FC<IncidentHistoryProps> = ({ events }) => {
  return (
    <div className="glass-panel p-6 rounded-2xl border border-slate-800 my-6">
      <h2 className="text-sm font-semibold text-slate-200 mb-6 flex items-center gap-2">
        <Terminal className="w-4 h-4 text-cyan-400" /> Real-Time Telemetry Audit Event Log ({events.length} Events)
      </h2>

      {events.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-6">No incident telemetry events recorded yet. Trigger a run to watch live logs.</p>
      ) : (
        <div className="space-y-3 font-mono text-xs max-h-[500px] overflow-y-auto pr-2">
          {events.map((evt, idx) => (
            <div key={idx} className="p-3 rounded-xl bg-slate-950/80 border border-slate-800/80 flex items-start gap-3">
              <div className="mt-0.5">
                {evt.result === 'SUCCESS' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                {evt.result === 'FAILURE' && <XCircle className="w-4 h-4 text-rose-400" />}
                {evt.result === 'IN_PROGRESS' && <Clock className="w-4 h-4 text-cyan-400 animate-spin" />}
                {evt.result === 'REQUIRES_APPROVAL' && <Clock className="w-4 h-4 text-amber-400" />}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between text-[11px] mb-1">
                  <span className="font-semibold text-cyan-300">[{evt.agent}] {evt.action}</span>
                  <span className="text-slate-500">{new Date(evt.timestamp).toLocaleTimeString()}</span>
                </div>
                <div className="text-slate-300 text-[11px] truncate">
                  Input: <span className="text-slate-400">{evt.input_summary}</span>
                </div>
                <div className="text-slate-400 text-[11px] truncate mt-0.5">
                  Output: <span className="text-slate-300">{evt.output_summary}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
