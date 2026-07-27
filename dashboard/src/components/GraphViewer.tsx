import React, { useEffect, useState } from 'react';
import { GitBranch, Box, FileText, CheckCircle2 } from 'lucide-react';
import { CodeGraphData, CodeGraphNode } from '../types';

interface GraphViewerProps {
  repoName: string;
}

export const GraphViewer: React.FC<GraphViewerProps> = ({ repoName }) => {
  const [graphData, setGraphData] = useState<CodeGraphData | null>(null);
  const [selectedNode, setSelectedNode] = useState<CodeGraphNode | null>(null);

  useEffect(() => {
    fetch(`/api/graph?repo_name=${repoName}`)
      .then((res) => res.json())
      .then((data) => {
        setGraphData(data);
        if (data.nodes && data.nodes.length > 0) {
          setSelectedNode(data.nodes[0]);
        }
      })
      .catch((err) => console.error('Error fetching graph:', err));
  }, [repoName]);

  if (!graphData) {
    return <div className="glass-panel p-8 text-center text-slate-500">Loading codebase dependency graph...</div>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 my-6">
      <div className="md:col-span-2 glass-panel p-6 rounded-2xl border border-slate-800">
        <h2 className="text-sm font-semibold text-slate-200 mb-4 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-cyan-400" /> AST Dependency Call Graph ({graphData.nodes.length} Nodes, {graphData.edges.length} Edges)
          </span>
          <span className="text-xs text-slate-500 font-mono">Repo: {repoName}</span>
        </h2>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 max-h-[450px] overflow-y-auto pr-2">
          {graphData.nodes.map((node) => {
            const isSelected = selectedNode?.id === node.id;
            return (
              <button
                key={node.id}
                onClick={() => setSelectedNode(node)}
                className={`p-3 rounded-xl border text-left transition-all ${
                  isSelected
                    ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-200 shadow-md shadow-cyan-500/10'
                    : node.is_test
                    ? 'bg-slate-900/60 border-slate-800 text-purple-300 hover:border-slate-700'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Box className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                  <span className="font-semibold text-xs truncate">{node.label}</span>
                </div>
                <div className="text-[10px] text-slate-500 font-mono truncate">{node.file_path}</div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="glass-panel p-6 rounded-2xl border border-slate-800">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Symbol Inspector</h3>
        {selectedNode ? (
          <div className="space-y-4 text-xs font-mono">
            <div>
              <span className="text-slate-500 block mb-1">Qualified Identifier:</span>
              <span className="text-cyan-300 font-bold break-all bg-slate-900 p-2 rounded block border border-slate-800">
                {selectedNode.id}
              </span>
            </div>
            <div>
              <span className="text-slate-500 block mb-1">Symbol Type:</span>
              <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 uppercase font-bold text-[10px]">
                {selectedNode.symbol_type}
              </span>
            </div>
            <div>
              <span className="text-slate-500 block mb-1">File Location:</span>
              <span className="text-slate-300 break-all">{selectedNode.file_path}</span>
            </div>
            <div>
              <span className="text-slate-500 block mb-1">Is Test Symbol:</span>
              <span className={selectedNode.is_test ? 'text-purple-400' : 'text-slate-400'}>
                {selectedNode.is_test ? 'True (Pytest Suite)' : 'False (Application Core)'}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-slate-500">Select a node from the call graph to inspect details.</p>
        )}
      </div>
    </div>
  );
};
