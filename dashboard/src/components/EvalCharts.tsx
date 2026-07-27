import React, { useEffect, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { BarChart3, CheckCircle, Clock, DollarSign, Target } from 'lucide-react';
import { EvalScorecard } from '../types';

export const EvalCharts: React.FC = () => {
  const [scorecard, setScorecard] = useState<EvalScorecard | null>(null);

  useEffect(() => {
    fetch('/api/eval')
      .then((res) => res.json())
      .then((data) => setScorecard(data))
      .catch((err) => console.error('Error fetching eval scorecard:', err));
  }, []);

  if (!scorecard) {
    return <div className="glass-panel p-8 text-center text-slate-500">Running benchmark scorecard evaluation...</div>;
  }

  const chartData = [
    { name: 'Localization Acc', value: scorecard.localization_accuracy_pct, color: '#06b6d4' },
    { name: 'First Pass Success', value: scorecard.first_attempt_success_pct, color: '#10b981' },
    { name: 'Overall Fix Rate', value: scorecard.overall_fix_rate_pct, color: '#8b5cf6' },
  ];

  return (
    <div className="space-y-6 my-6">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="glass-panel p-5 rounded-2xl border border-slate-800">
          <div className="flex items-center gap-2 text-slate-400 text-xs mb-2">
            <Target className="w-4 h-4 text-cyan-400" /> Root Cause Localization
          </div>
          <div className="text-2xl font-bold text-slate-100">{scorecard.localization_accuracy_pct}%</div>
          <p className="text-[10px] text-slate-500 mt-1">AST backward walk accuracy</p>
        </div>

        <div className="glass-panel p-5 rounded-2xl border border-slate-800">
          <div className="flex items-center gap-2 text-slate-400 text-xs mb-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" /> Overall Fix Rate
          </div>
          <div className="text-2xl font-bold text-slate-100">{scorecard.overall_fix_rate_pct}%</div>
          <p className="text-[10px] text-slate-500 mt-1">Verified passing fixes</p>
        </div>

        <div className="glass-panel p-5 rounded-2xl border border-slate-800">
          <div className="flex items-center gap-2 text-slate-400 text-xs mb-2">
            <Clock className="w-4 h-4 text-purple-400" /> Avg Attempts / Case
          </div>
          <div className="text-2xl font-bold text-slate-100">{scorecard.average_attempts_per_case}</div>
          <p className="text-[10px] text-slate-500 mt-1">Bounded retry cap: 3</p>
        </div>

        <div className="glass-panel p-5 rounded-2xl border border-slate-800">
          <div className="flex items-center gap-2 text-slate-400 text-xs mb-2">
            <DollarSign className="w-4 h-4 text-amber-400" /> Token Cost / Run
          </div>
          <div className="text-2xl font-bold text-slate-100">${scorecard.total_token_cost_usd}</div>
          <p className="text-[10px] text-slate-500 mt-1">Total benchmark cost</p>
        </div>
      </div>

      <div className="glass-panel p-6 rounded-2xl border border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200 mb-6">Benchmark Accuracy Metric Breakdown</h3>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} domain={[0, 100]} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }} />
              <Bar dataKey="value" fill="#06b6d4" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};
