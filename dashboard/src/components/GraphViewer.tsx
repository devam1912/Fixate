import React, { useEffect, useState } from 'react';
import { GitBranch, Box, Layers, Search, Network, Grid, RefreshCw, FolderGit2 } from 'lucide-react';
import { CodeGraphData, CodeGraphNode } from '../types';

interface GraphViewerProps {
  repoName: string;
  customRepoPath?: string;
}

export const GraphViewer: React.FC<GraphViewerProps> = ({ repoName: initialRepoName, customRepoPath: initialCustomPath }) => {
  const [graphData, setGraphData] = useState<CodeGraphData | null>(null);
  const [selectedNode, setSelectedNode] = useState<CodeGraphNode | null>(null);
  const [filterType, setFilterType] = useState<'all' | 'functions' | 'tests'>('all');
  const [viewMode, setViewMode] = useState<'visual' | 'grid'>('visual');
  const [searchTerm, setSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  
  // Dynamic target repository selection inside AST Graph view
  const [activeTargetRepo, setActiveTargetRepo] = useState<string>(initialRepoName || 'enterprise_app');
  const [customPathInput, setCustomPathInput] = useState<string>(initialCustomPath || '');

  const fetchGraph = (repo: string, customPath?: string) => {
    setIsLoading(true);
    let query = '';
    if (customPath && customPath.trim()) {
      query = `repo_path=${encodeURIComponent(customPath.trim())}`;
    } else {
      query = `repo_name=${encodeURIComponent(repo)}`;
    }

    fetch(`/api/graph?${query}`)
      .then((res) => res.json())
      .then((data) => {
        setGraphData(data);
        if (data.nodes && data.nodes.length > 0) {
          setSelectedNode(data.nodes[0]);
        } else {
          setSelectedNode(null);
        }
        setIsLoading(false);
      })
      .catch((err) => {
        console.error('Error fetching graph:', err);
        setIsLoading(false);
      });
  };

  useEffect(() => {
    fetchGraph(activeTargetRepo, customPathInput);
  }, [activeTargetRepo]);

  const handleSelectRepo = (repo: string) => {
    setActiveTargetRepo(repo);
    setCustomPathInput('');
  };

  const handleLoadCustomPath = () => {
    if (customPathInput.trim()) {
      fetchGraph(activeTargetRepo, customPathInput);
    }
  };

  const nodes = graphData?.nodes || [];
  const edges = graphData?.edges || [];

  const filteredNodes = nodes.filter((node) => {
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

  // Calculate multi-tiered multi-row layout coordinates to prevent overlapping nodes
  const testNodes = nodes.filter((n) => n.is_test);
  const funcNodes = nodes.filter((n) => !n.is_test);

  const nodePositions: { [id: string]: { x: number; y: number } } = {};
  const width = 840;

  // Tier 1: Pytest nodes on top row
  testNodes.forEach((node, idx) => {
    const total = testNodes.length || 1;
    const spacing = width / (total + 1);
    nodePositions[node.id] = { x: spacing * (idx + 1), y: 70 };
  });

  // Tier 2: Multi-row wrapped grid layout for Application Function nodes
  const cols = Math.min(8, Math.max(4, Math.ceil(Math.sqrt(funcNodes.length))));
  const numRows = Math.ceil(funcNodes.length / cols) || 1;
  const colSpacing = width / (cols + 1);
  const rowSpacing = 80;
  const startY = 180;

  funcNodes.forEach((node, idx) => {
    const c = idx % cols;
    const r = Math.floor(idx / cols);
    nodePositions[node.id] = {
      x: colSpacing * (c + 1),
      y: startY + r * rowSpacing,
    };
  });

  const canvasHeight = Math.max(450, startY + numRows * rowSpacing + 50);

  return (
    <div className="space-y-6 my-6">
      {/* Target Repository Selector Toolbar */}
      <div className="glass-card p-4 rounded-2xl border border-zinc-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <FolderGit2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <div>
            <span className="text-xs font-mono font-bold text-white uppercase tracking-wider block">
              AST Target Codebase Repository
            </span>
            <span className="text-[11px] text-zinc-400 font-mono">
              Switch repository to parse dynamic AST nodes & call dependency edges
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          {['enterprise_app', 'calculator_app', 'ecommerce_api', 'data_processor'].map((repo) => (
            <button
              key={repo}
              onClick={() => handleSelectRepo(repo)}
              className={`px-3 py-1.5 rounded-xl text-xs font-mono transition-all ${
                activeTargetRepo === repo && !customPathInput
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold'
                  : 'bg-zinc-950 text-zinc-400 border border-zinc-800 hover:text-white'
              }`}
            >
              {repo}
            </button>
          ))}

          <div className="flex items-center gap-1.5 flex-1 md:flex-initial">
            <input
              type="text"
              placeholder="Or custom GitHub URL / local path..."
              value={customPathInput}
              onChange={(e) => setCustomPathInput(e.target.value)}
              className="bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-1 text-xs font-mono text-white focus:outline-none focus:border-zinc-500 w-48"
            />
            <button
              onClick={handleLoadCustomPath}
              className="bg-zinc-800 hover:bg-zinc-700 text-white p-1.5 rounded-xl border border-zinc-700 transition-colors"
              title="Parse custom repository AST"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Main Graph Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Interactive Graph Canvas & Controls */}
        <div className="lg:col-span-2 glass-card p-6 rounded-3xl border border-zinc-800">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6 pb-4 border-b border-zinc-800">
            <div>
              <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-emerald-400" />
                AST Dependency Topology ({nodes.length} Nodes, {edges.length} Call Edges)
              </h2>
              <p className="text-xs text-zinc-400 font-sans mt-0.5 truncate max-w-md">
                Active Codebase: <span className="text-emerald-300 font-mono font-semibold">{customPathInput || activeTargetRepo}</span>
              </p>
            </div>

            <div className="flex items-center gap-2">
              {/* View Mode Switcher */}
              <div className="flex items-center gap-1 bg-zinc-950 p-1 rounded-xl border border-zinc-800 mr-2">
                <button
                  onClick={() => setViewMode('visual')}
                  className={`p-1.5 rounded-lg text-xs font-mono transition-all ${
                    viewMode === 'visual'
                      ? 'bg-zinc-800 text-white border border-zinc-700'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                  title="Visual Topology Graph Map"
                >
                  <Network className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setViewMode('grid')}
                  className={`p-1.5 rounded-lg text-xs font-mono transition-all ${
                    viewMode === 'grid'
                      ? 'bg-zinc-800 text-white border border-zinc-700'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                  title="Grid Directory Cards"
                >
                  <Grid className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Filter Buttons */}
              <button
                onClick={() => setFilterType('all')}
                className={`px-3 py-1 rounded-xl text-xs font-mono transition-all ${
                  filterType === 'all'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold'
                    : 'bg-zinc-900 text-zinc-400 hover:text-white'
                }`}
              >
                All ({nodes.length})
              </button>
              <button
                onClick={() => setFilterType('functions')}
                className={`px-3 py-1 rounded-xl text-xs font-mono transition-all ${
                  filterType === 'functions'
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-semibold'
                    : 'bg-zinc-900 text-zinc-400 hover:text-white'
                }`}
              >
                Functions ({funcNodes.length})
              </button>
              <button
                onClick={() => setFilterType('tests')}
                className={`px-3 py-1 rounded-xl text-xs font-mono transition-all ${
                  filterType === 'tests'
                    ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 font-semibold'
                    : 'bg-zinc-900 text-zinc-400 hover:text-white'
                }`}
              >
                Pytest ({testNodes.length})
              </button>
            </div>
          </div>

          {/* Search Input */}
          <div className="relative mb-4">
            <Search className="w-4 h-4 text-zinc-500 absolute left-3.5 top-3" />
            <input
              type="text"
              placeholder="Search AST symbols or file paths..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-2xl pl-10 pr-4 py-2 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
            />
          </div>

          {/* VISUAL SVG TOPOLOGY GRAPH */}
          {viewMode === 'visual' && (
            <div className="relative bg-zinc-950/90 border border-zinc-800 rounded-2xl p-4 overflow-auto max-h-[520px] flex items-center justify-center">
              {isLoading ? (
                <div className="text-xs font-mono text-emerald-400 flex items-center gap-2 py-12">
                  <RefreshCw className="w-4 h-4 animate-spin" /> Parsing AST Directed Dependency Graph...
                </div>
              ) : nodes.length === 0 ? (
                <div className="text-xs font-mono text-zinc-500 py-12">No AST nodes found in {activeTargetRepo}.</div>
              ) : (
                <svg viewBox={`0 0 ${width} ${canvasHeight}`} className="w-full h-auto min-h-[420px]">
                  <defs>
                    <marker
                      id="arrowhead-dynamic"
                      markerWidth="8"
                      markerHeight="6"
                      refX="7"
                      refY="3"
                      orient="auto"
                    >
                      <polygon points="0 0, 8 3, 0 6" fill="#10b981" />
                    </marker>
                  </defs>

                  {/* Render Directed Call Edges */}
                  {edges.map((edge, idx) => {
                    const srcPos = nodePositions[edge.source];
                    const tgtPos = nodePositions[edge.target];
                    if (!srcPos || !tgtPos) return null;

                    const isConnectedToSelected =
                      selectedNode?.id === edge.source || selectedNode?.id === edge.target;

                    return (
                      <g key={`edge-${idx}`}>
                        <line
                          x1={srcPos.x}
                          y1={srcPos.y}
                          x2={tgtPos.x}
                          y2={tgtPos.y}
                          stroke={isConnectedToSelected ? '#10b981' : '#3f3f46'}
                          strokeWidth={isConnectedToSelected ? '2.5' : '1.2'}
                          strokeDasharray={isConnectedToSelected ? 'none' : '3 3'}
                          markerEnd="url(#arrowhead-dynamic)"
                          className="transition-all duration-300"
                        />
                      </g>
                    );
                  })}

                  {/* Render Node Symbols */}
                  {nodes.map((node) => {
                    const pos = nodePositions[node.id] || { x: width / 2, y: canvasHeight / 2 };
                    const isSelected = selectedNode?.id === node.id;
                    const isFiltered = filteredNodes.some((fn) => fn.id === node.id);

                    if (!isFiltered) return null;

                    const displayLabel = node.label.length > 16 ? node.label.slice(0, 13) + '...' : node.label;

                    return (
                      <g
                        key={node.id}
                        onClick={() => setSelectedNode(node)}
                        className="cursor-pointer group"
                      >
                        {isSelected && (
                          <circle
                            cx={pos.x}
                            cy={pos.y}
                            r="24"
                            fill="none"
                            stroke="#10b981"
                            strokeWidth="2"
                            className="animate-pulse"
                          />
                        )}

                        <circle
                          cx={pos.x}
                          cy={pos.y}
                          r="16"
                          fill={isSelected ? '#059669' : node.is_test ? '#6b21a8' : '#0284c7'}
                          stroke={isSelected ? '#34d399' : '#18181b'}
                          strokeWidth="2"
                          className="transition-all duration-200 group-hover:scale-125"
                        />

                        <text
                          x={pos.x}
                          y={pos.y + 28}
                          textAnchor="middle"
                          fill={isSelected ? '#10b981' : '#e4e4e7'}
                          className="text-[10px] font-mono font-bold select-none"
                        >
                          {displayLabel}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
            </div>
          )}

          {/* GRID CARDS MODE */}
          {viewMode === 'grid' && (
            <div>
              {filteredNodes.length === 0 ? (
                <div className="text-center text-zinc-500 py-10 text-xs font-mono">
                  No matching AST symbols found in codebase.
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[400px] overflow-y-auto pr-2">
                  {filteredNodes.map((node) => {
                    const isSelected = selectedNode?.id === node.id;
                    return (
                      <button
                        key={node.id}
                        onClick={() => setSelectedNode(node)}
                        className={`p-3.5 rounded-2xl border text-left transition-all duration-200 ${
                          isSelected
                            ? 'bg-zinc-900 border-emerald-500/50 text-white shadow-lg'
                            : node.is_test
                            ? 'bg-purple-950/30 border-purple-800/40 text-purple-300 hover:border-purple-600'
                            : 'bg-zinc-900/40 border-zinc-800 text-zinc-300 hover:border-zinc-700'
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-1.5">
                          <Box className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          <span className="font-mono font-semibold text-xs truncate">{node.label}</span>
                        </div>
                        <div className="text-[10px] text-zinc-500 font-mono truncate">{node.file_path}</div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Col: AST Symbol Inspector */}
        <div className="glass-card p-6 rounded-3xl border border-zinc-800 flex flex-col justify-between">
          <div>
            <h3 className="text-xs font-mono font-bold text-zinc-400 uppercase tracking-widest mb-4 flex items-center gap-2">
              <Layers className="w-4 h-4 text-emerald-400" />
              Symbol Inspector
            </h3>

            {selectedNode ? (
              <div className="space-y-4 font-mono">
                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">Symbol Name</span>
                  <div className="text-xs font-bold text-white bg-zinc-950 p-2.5 rounded-xl border border-zinc-800">
                    {selectedNode.label}
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">Symbol Type</span>
                  <div className="inline-block text-xs font-bold px-2.5 py-1 rounded-lg bg-zinc-900 text-emerald-300 border border-zinc-800 uppercase">
                    {selectedNode.symbol_type}
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">File Location</span>
                  <div className="text-xs text-zinc-300 bg-zinc-950 p-2.5 rounded-xl border border-zinc-800 break-all leading-relaxed">
                    {selectedNode.file_path}
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">Classification</span>
                  <div
                    className={`text-xs px-2.5 py-1.5 rounded-xl border ${
                      selectedNode.is_test
                        ? 'bg-purple-950/40 text-purple-300 border-purple-800/50'
                        : 'bg-emerald-950/40 text-emerald-300 border-emerald-800/50'
                    }`}
                  >
                    {selectedNode.is_test ? 'Pytest Unit Verification Case' : 'Core Application Symbol'}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-xs text-zinc-500 font-mono py-12 text-center">
                Select an AST node to inspect symbol details.
              </div>
            )}
          </div>

          <div className="pt-4 border-t border-zinc-800 mt-6 flex items-center justify-between text-[11px] font-mono text-zinc-500">
            <span>Language AST: Python 3.11</span>
            <GitBranch className="w-3.5 h-3.5 text-emerald-400" />
          </div>
        </div>
      </div>
    </div>
  );
};
