import React, { useEffect, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Target, CheckCircle2, Clock, DollarSign, Award, Zap, RefreshCw, CheckCircle, XCircle } from 'lucide-react';
import { EvalScorecard } from '../types';

export const EvalCharts: React.FC = () => {
  const [scorecard, setScorecard] = useState<EvalScorecard | null>(null);
  const [recordedAt, setRecordedAt] = useState<string | null>(null);
  const [totalCases, setTotalCases] = useState<number>(0);
  const [isExecutingLive, setIsExecutingLive] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // A scorecard is only ever shown when a real run produced it. The API returns
  // `recorded: false` until the suite has actually been executed, so the tab
  // reports "not yet measured" rather than standing in numbers nobody produced.
  const applyResponse = (data: any) => {
    setTotalCases(data?.total_cases ?? 0);
    if (data?.recorded) {
      setScorecard(data as EvalScorecard);
      setRecordedAt(data.recorded_at ?? null);
    } else {
      setScorecard(null);
      setRecordedAt(null);
    }
  };

  const fetchScorecard = () => {
    setIsLoading(true);
    fetch('/api/eval')
      .then((res) => res.json())
      .then(applyResponse)
      .catch((err) => setError(String(err)))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => {
    fetchScorecard();
  }, []);

  const handleRunLiveBenchmark = async () => {
    setIsExecutingLive(true);
    setError(null);
    try {
      const res = await fetch('/api/eval/run', { method: 'POST' });
      if (!res.ok) throw new Error(`Benchmark run failed: ${res.statusText}`);
      applyResponse(await res.json());
    } catch (err: any) {
      setError(err?.message ?? 'Benchmark run failed');
    } finally {
      setIsExecutingLive(false);
    }
  };

  if (isLoading) {
    return (
      <div className="glass-card p-12 text-center text-zinc-500 rounded-3xl my-6 border border-zinc-800">
        <Zap className="w-8 h-8 mx-auto mb-3 text-emerald-400 animate-bounce" />
        Loading benchmark scorecard...
      </div>
    );
  }

  if (!scorecard) {
    return (
      <div className="glass-card p-12 rounded-3xl my-6 border border-zinc-800 text-center">
        <Award className="w-9 h-9 mx-auto mb-4 text-zinc-600" />
        <h2 className="text-sm font-mono font-bold text-white uppercase tracking-wider">
          No benchmark run recorded
        </h2>
        <p className="text-xs text-zinc-500 font-mono mt-2 max-w-lg mx-auto leading-relaxed">
          Metrics appear here only after the suite has actually run. Executing
          {` ${totalCases || 'the'} `}
          benchmark cases makes live LLM calls and consumes provider quota.
        </p>
        {error && (
          <p className="text-xs text-rose-400 font-mono mt-4">{error}</p>
        )}
        <button
          onClick={handleRunLiveBenchmark}
          disabled={isExecutingLive}
          className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white text-black text-xs font-mono font-bold uppercase tracking-wider hover:bg-zinc-200 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${isExecutingLive ? 'animate-spin' : ''}`} />
          {isExecutingLive ? 'Running benchmark suite...' : 'Run benchmark suite'}
        </button>
      </div>
    );
  }

  const chartData = [
    { name: 'Localization Acc', value: scorecard.localization_accuracy_pct, fill: '#10b981' },
    { name: 'First Pass Success', value: scorecard.first_attempt_success_pct, fill: '#06b6d4' },
    { name: 'Overall Fix Rate', value: scorecard.overall_fix_rate_pct, fill: '#8b5cf6' },
  ];

  return (
    <div className="space-y-6 my-6">
      {/* Run Live Benchmark Suite Header */}
      <div className="glass-card p-5 rounded-3xl border border-zinc-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xs font-mono font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <Award className="w-4 h-4 text-emerald-400" />
            Autonomous Self-Healing Evaluation Scorecard
          </h2>
          <p className="text-xs text-zinc-500 font-mono mt-0.5">
            {recordedAt
              ? `Measured across ${scorecard.total_cases} repair cases on ${new Date(recordedAt).toLocaleString()}`
              : `Measured across ${scorecard.total_cases} repair cases`}
          </p>
        </div>

        <button
          onClick={handleRunLiveBenchmark}
          disabled={isExecutingLive}
          className="bg-emerald-500 hover:bg-emerald-400 text-black font-mono font-bold text-xs px-5 py-2.5 rounded-xl flex items-center gap-2 transition-all disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isExecutingLive ? 'animate-spin' : ''}`} />
          {isExecutingLive ? 'EXECUTING LIVE BENCHMARKS...' : 'RE-RUN LIVE BENCHMARKS'}
        </button>
      </div>

      {/* 4 Stat Cards Header */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="glass-card p-5 rounded-3xl border border-zinc-800 relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <Target className="w-4 h-4 text-emerald-400" /> Root Cause Localization
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
            {scorecard.localization_accuracy_pct}%
          </div>
          <div className="w-full bg-zinc-900 rounded-full h-1.5 mt-3 overflow-hidden border border-zinc-800">
            <div
              className="bg-emerald-400 h-full rounded-full"
              style={{ width: `${scorecard.localization_accuracy_pct}%` }}
            />
          </div>
        </div>

        <div className="glass-card p-5 rounded-3xl border border-zinc-800 relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <CheckCircle2 className="w-4 h-4 text-cyan-400" /> Overall Fix Pass Rate
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
            {scorecard.overall_fix_rate_pct}%
          </div>
          <div className="w-full bg-zinc-900 rounded-full h-1.5 mt-3 overflow-hidden border border-zinc-800">
            <div
              className="bg-cyan-400 h-full rounded-full"
              style={{ width: `${scorecard.overall_fix_rate_pct}%` }}
            />
          </div>
        </div>

        <div className="glass-card p-5 rounded-3xl border border-zinc-800 relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <Clock className="w-4 h-4 text-purple-400" /> Avg Attempts / Case
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
            {scorecard.average_attempts_per_case} <span className="text-xs text-zinc-500 font-normal">/ 3</span>
          </div>
          <p className="text-[10px] text-zinc-500 font-mono mt-3">Bounded Retry Cap: Max 3</p>
        </div>

        <div className="glass-card p-5 rounded-3xl border border-zinc-800 relative overflow-hidden">
          <div className="flex items-center gap-2 text-zinc-400 text-xs font-mono mb-2">
            <DollarSign className="w-4 h-4 text-emerald-400" /> Total Token Cost
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight font-mono">
            ${scorecard.total_token_cost_usd}
          </div>
          <p className="text-[10px] text-zinc-500 font-mono mt-3">Gemini 3.5 Flash Priority</p>
        </div>
      </div>

      {/* Bar Chart Card */}
      <div className="glass-card p-6 rounded-3xl border border-zinc-800">
        <h3 className="text-xs font-mono font-bold text-emerald-400 uppercase tracking-widest mb-6 flex items-center gap-2">
          <Award className="w-4 h-4 text-emerald-400" />
          Benchmark Scorecard Metric Distribution
        </h3>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="name" stroke="#a1a1aa" fontSize={12} tickLine={false} />
              <YAxis stroke="#a1a1aa" fontSize={12} domain={[0, 100]} tickLine={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#09090b',
                  borderColor: '#27272a',
                  borderRadius: '12px',
                  fontSize: '12px',
                  color: '#fff',
                }}
              />
              <Bar dataKey="value" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Case-by-Case Breakdown Table */}
      {scorecard.case_results && scorecard.case_results.length > 0 && (
        <div className="glass-card p-6 rounded-3xl border border-zinc-800">
          <h3 className="text-xs font-mono font-bold text-white uppercase tracking-widest mb-4">
            Benchmark Case Breakdown ({scorecard.case_results.length} Cases)
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-400 text-[11px]">
                  <th className="py-2.5 px-3">CASE ID</th>
                  <th className="py-2.5 px-3">BUG CATEGORY</th>
                  <th className="py-2.5 px-3">LOCALIZATION</th>
                  <th className="py-2.5 px-3">FIX VERIFIED</th>
                  <th className="py-2.5 px-3">ATTEMPTS</th>
                  <th className="py-2.5 px-3">COST</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {scorecard.case_results.map((c, idx) => (
                  <tr key={idx} className="hover:bg-zinc-900/50 transition-colors">
                    <td className="py-3 px-3 font-bold text-white">{c.case_id}</td>
                    <td className="py-3 px-3 text-zinc-300">{c.bug_category}</td>
                    <td className="py-3 px-3">
                      {c.localization_correct ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400 font-semibold">
                          <CheckCircle className="w-3.5 h-3.5" /> PASSED
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-rose-400 font-semibold">
                          <XCircle className="w-3.5 h-3.5" /> MISSED
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      {c.final_verified_passed ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400 font-semibold">
                          <CheckCircle className="w-3.5 h-3.5" /> PASSED
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-rose-400 font-semibold">
                          <XCircle className="w-3.5 h-3.5" /> FAILED
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-3 text-zinc-300">{c.attempts_used} / 3</td>
                    <td className="py-3 px-3 text-emerald-400">${c.estimated_token_cost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
