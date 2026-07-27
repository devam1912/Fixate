import React, { useEffect, useState } from 'react';
import { GitBranch, Box, Layers, Search, FolderCog } from 'lucide-react';
import { CodeGraphData, CodeGraphNode } from '../types';

interface GraphViewerProps {
  repoName: string;
  customRepoPath?: string;
}

export const GraphViewer: React.FC<GraphViewerProps> = ({ repoName, customRepoPath }) => {
  const [graphData, setGraphData] = useState<CodeGraphData | null>(null);
  const [selectedNode, setSelectedNode] = useState<CodeGraphNode | null>(null);
  const [filterType, setFilterType] = useState<'all' | 'functions' | 'tests'>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    setIsLoading(true);
    const query = customRepoPath
      ? `repo_path=${encodeURIComponent(customRepoPath)}`
      : `repo_name=${encodeURIComponent(repoName)}`;

    fetch(`/api/graph?${query}`)
      .then((res) => res.json())
      .then((data) => {
        setGraphData(data);
        if (data.nodes && data.nodes.length > 0) {
          setSelectedNode(data.nodes[0]);
        }
        setIsLoading(false);
      })
      .catch((err) => {
        console.error('Error fetching graph:', err);
        setIsLoading(false);
      });
  }, [repoName, customRepoPath]);

  if (isLoading || !graphData) {
    return (
      <div className="glass-card p-12 text-center text-zinc-500 rounded-3xl my-6">
        <GitBranch className="w-8 h-8 mx-auto mb-3 text-violet-400 animate-spin" />
        Constructing Dynamic AST Codebase Dependency Graph...
      </div>
    );
  }

  const filteredNodes = (graphData.nodes || []).filter((node) => {
    if (filterType === 'functions' && node.is_test) return false;
    if (filterType === 'tests' && !node.is_test) return false;
    if (
      searchTerm &&
      !node.label.toLowerCase().includes(searchTerm.toLowerCase()) &&
      !node.file_path.toLowerCase().includes(searchTerm.toLowerCase())
    ) {
      return false;
    }
    return true;
  });

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 my-6">
      {/* Left 2 Cols: Graph Symbol Grid & Visual Map */}
      <div className="lg:col-span-2 glass-card p-6 rounded-3xl border border-white/[0.08]">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6 pb-4 border-b border-white/[0.08]">
          <div>
            <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-violet-400 flex items-center gap-2">
              <GitBranch className="w-4 h-4 text-cyan-400" />
              AST Symbol Graph ({graphData.nodes?.length || 0} Nodes, {graphData.edges?.length || 0} Call Edges)
            </h2>
            <p className="text-xs text-zinc-400 font-sans mt-0.5 truncate max-w-md">
              Target: <span className="text-cyan-300 font-mono font-semibold">{customRepoPath || repoName}</span>
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setFilterType('all')}
              className={`px-3 py-1 rounded-xl text-xs font-mono transition-all ${
                filterType === 'all'
                  ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30 font-semibold'
                  : 'bg-white/[0.03] text-zinc-400 hover:text-white'
              }`}
            >
              All ({graphData.nodes?.length || 0})
            </button>
            <button
              onClick={() => setFilterType('functions')}
              className={`px-3 py-1 rounded-xl text-xs font-mono transition-all ${
                filterType === 'functions'
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-semibold'
                  : 'bg-white/[0.03] text-zinc-400 hover:text-white'
              }`}
            >
              Functions
            </button>
            <button
              onClick={() => setFilterType('tests')}
              className={`px-3 py-1 rounded-xl text-xs font-mono transition-all ${
                filterType === 'tests'
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 font-semibold'
                  : 'bg-white/[0.03] text-zinc-400 hover:text-white'
              }`}
            >
              Pytest
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className="relative mb-4">
          <Search className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3" />
          <input
            type="text"
            placeholder="Search AST symbols or file paths..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-[#090a0f] border border-white/[0.08] rounded-2xl pl-10 pr-4 py-2 text-xs font-mono text-white focus:outline-none focus:border-cyan-500/50"
          />
        </div>

        {/* Symbols Grid */}
        {filteredNodes.length === 0 ? (
          <div className="text-center text-zinc-500 py-10 text-xs font-mono">
            No matching AST symbols found in codebase.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[460px] overflow-y-auto pr-2">
            {filteredNodes.map((node) => {
              const isSelected = selectedNode?.id === node.id;
              return (
                <button
                  key={node.id}
                  onClick={() => setSelectedNode(node)}
                  className={`p-3.5 rounded-2xl border text-left transition-all duration-200 ${
                    isSelected
                      ? 'bg-gradient-to-r from-violet-600/30 to-cyan-500/30 border-cyan-500/50 text-white shadow-lg shadow-cyan-500/10'
                      : node.is_test
                      ? 'bg-[#12101b]/60 border-purple-500/20 text-purple-300 hover:border-purple-500/40'
                      : 'bg-zinc-900/40 border-white/[0.06] text-zinc-300 hover:border-white/20'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <Box className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                    <span className="font-mono font-semibold text-xs truncate">{node.label}</span>
                  </div>
                  <div className="text-[10px] text-zinc-500 font-mono truncate">{node.file_path}</div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Right Col: AST Symbol Inspector */}
      <div className="glass-card p-6 rounded-3xl border border-white/[0.08] flex flex-col justify-between">
        <div>
          <h3 className="text-xs font-mono font-bold text-zinc-400 uppercase tracking-widest mb-4 flex items-center gap-2">
            <Layers className="w-4 h-4 text-violet-400" />
            Symbol Inspector
          </h3>

          {selectedNode ? (
            <div className="space-y-4 text-xs font-mono">
              <div className="p-3 rounded-2xl bg-[#090a0f] border border-white/[0.08]">
                <span className="text-zinc-500 block text-[10px] uppercase mb-1">Symbol ID</span>
                <span className="text-cyan-300 font-bold break-all">{selectedNode.id}</span>
              </div>

              <div className="p-3 rounded-2xl bg-[#090a0f] border border-white/[0.08]">
                <span className="text-zinc-500 block text-[10px] uppercase mb-1">Symbol Type</span>
                <span className="px-2.5 py-1 rounded-lg bg-violet-500/10 text-violet-300 border border-violet-500/20 font-bold text-[10px] inline-block">
                  {selectedNode.symbol_type.toUpperCase()}
                </span>
              </div>

              <div className="p-3 rounded-2xl bg-[#090a0f] border border-white/[0.08]">
                <span className="text-zinc-500 block text-[10px] uppercase mb-1">File Location</span>
                <span className="text-zinc-300 break-all">{selectedNode.file_path}</span>
              </div>

              <div className="p-3 rounded-2xl bg-[#090a0f] border border-white/[0.08]">
                <span className="text-zinc-500 block text-[10px] uppercase mb-1">Classification</span>
                <span className={selectedNode.is_test ? 'text-purple-400 font-semibold' : 'text-emerald-400 font-semibold'}>
                  {selectedNode.is_test ? 'Pytest Unit Test Symbol' : 'Core Application Symbol'}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-zinc-500 text-center py-10">Select an AST node to inspect symbol details.</p>
          )}
        </div>

        <div className="pt-4 border-t border-white/[0.08] text-[11px] text-zinc-500 font-mono flex items-center justify-between">
          <span>Language AST: Python 3.11</span>
          <FolderCog className="w-3.5 h-3.5 text-cyan-400" />
        </div>
      </div>
    </div>
  );
};
