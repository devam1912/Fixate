import React, { useEffect, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Target, CheckCircle2, Clock, DollarSign, Award, Zap } from 'lucide-react';
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
    return (
      <div className="glass-card p-12 text-center text-zinc-500 rounded-3xl my-6">
        <Zap className="w-8 h-8 mx-auto mb-3 text-amber-400 animate-bounce" />
        Running Benchmark Scorecard Evaluation Suite...
      </div>
    );
  }

  const chartData = [
    { name: 'Localization Acc', value: scorecard.localization_accuracy_pct, fill: '#8b5cf6' },
    { name: 'First Pass Success', value: scorecard.first_attempt_success_pct, fill: '#06b6d4' },
    { name: 'Overall Fix Rate', value: scorecard.overall_fix_rate_pct, fill: '#10b981' },
  ];

  return (
    <div className="space-y-6 my-6">
      {/* 4 Stat Cards Header */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="glass-card p-5 rounded-3xl border border-white/[0.08] relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <Target className="w-4 h-4 text-violet-400" /> Root Cause Localization
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight">
            {scorecard.localization_accuracy_pct}%
          </div>
          <div className="w-full bg-white/[0.06] rounded-full h-1.5 mt-3 overflow-hidden">
            <div
              className="bg-gradient-to-r from-violet-500 to-indigo-500 h-full rounded-full"
              style={{ width: `${scorecard.localization_accuracy_pct}%` }}
            />
          </div>
        </div>

        <div className="glass-card p-5 rounded-3xl border border-white/[0.08] relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Overall Fix Pass Rate
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight">
            {scorecard.overall_fix_rate_pct}%
          </div>
          <div className="w-full bg-white/[0.06] rounded-full h-1.5 mt-3 overflow-hidden">
            <div
              className="bg-gradient-to-r from-emerald-500 to-teal-400 h-full rounded-full"
              style={{ width: `${scorecard.overall_fix_rate_pct}%` }}
            />
          </div>
        </div>

        <div className="glass-card p-5 rounded-3xl border border-white/[0.08] relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <Clock className="w-4 h-4 text-cyan-400" /> Avg Attempts / Case
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight">
            {scorecard.average_attempts_per_case} <span className="text-xs text-zinc-500 font-normal">/ 3</span>
          </div>
          <p className="text-[10px] text-zinc-500 font-mono mt-3">Bounded Retry Cap: Max 3</p>
        </div>

        <div className="glass-card p-5 rounded-3xl border border-white/[0.08] relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <DollarSign className="w-4 h-4 text-amber-400" /> Total Token Cost
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight">
            ${scorecard.total_token_cost_usd}
          </div>
          <p className="text-[10px] text-zinc-500 font-mono mt-3">Gemini 2.5 Flash Free Tier Priority</p>
        </div>
      </div>

      {/* Bar Chart Card */}
      <div className="glass-card p-6 rounded-3xl border border-white/[0.08]">
        <h3 className="text-xs font-mono font-bold text-violet-400 uppercase tracking-widest mb-6 flex items-center gap-2">
          <Award className="w-4 h-4 text-cyan-400" />
          Benchmark Scorecard Metric Distribution
        </h3>

        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
              <XAxis dataKey="name" stroke="#71717a" fontSize={12} tickLine={false} />
              <YAxis stroke="#71717a" fontSize={12} domain={[0, 100]} tickLine={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0c0d14',
                  borderColor: 'rgba(255, 255, 255, 0.1)',
                  borderRadius: '16px',
                  fontSize: '12px',
                  color: '#fff',
                }}
              />
              <Bar dataKey="value" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};
