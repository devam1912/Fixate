import React, { useEffect, useState } from 'react';
import {
  Box,
  CheckCircle2,
  FileCode2,
  FolderGit2,
  GitBranch,
  Grid,
  Layers,
  Network,
  RefreshCw,
  Search,
} from 'lucide-react';
import { CodeGraphData, CodeGraphNode } from '../types';

interface GraphViewerProps {
  repoName: string;
  customRepoPath?: string;
}

const NODE_WIDTH = 214;
const NODE_HEIGHT = 60;
const GRAPH_WIDTH = 980;
const GRAPH_COLUMNS = 3;
const GRAPH_GAP_X = 44;
const GRAPH_GAP_Y = 28;
const GRAPH_START_X = 36;

const nodeKindLabel = (node: CodeGraphNode) => {
  if (node.is_test) return 'Test';
  if (node.symbol_type === 'class') return 'Class';
  if (node.symbol_type === 'method') return 'Method';
  return 'Function';
};

const fileNameFromPath = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() || path;

const folderNameFromPath = (path: string) => {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 2] : 'root';
};

const compactTarget = (target: string) => {
  if (!target) return 'sample repository';
  const clean = target.replace(/\/$/, '');
  if (clean.includes('github.com/')) {
    return clean.split('github.com/')[1] || clean;
  }
  return clean.length > 56 ? `...${clean.slice(-53)}` : clean;
};

const inferLanguage = (nodes: CodeGraphNode[]) => {
  const joined = nodes.map((node) => node.file_path.toLowerCase()).join(' ');
  if (/\.(tsx?|jsx?)\b/.test(joined)) return 'TypeScript / JavaScript';
  if (/\.(cpp|cc|cxx|hpp|h)\b/.test(joined)) return 'C++';
  if (/\.py\b/.test(joined)) return 'Python';
  return 'Mixed codebase';
};

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

  const testNodes = nodes.filter((n) => n.is_test);
  const funcNodes = nodes.filter((n) => !n.is_test);
  const visibleTestNodes = filteredNodes.filter((n) => n.is_test);
  const visibleFuncNodes = filteredNodes.filter((n) => !n.is_test);
  const visibleNodeIds = new Set(filteredNodes.map((node) => node.id));
  const visibleEdges = edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target));
  const activeTargetLabel = compactTarget(customPathInput || activeTargetRepo);
  const languageLabel = inferLanguage(nodes);

  const nodePositions: { [id: string]: { x: number; y: number } } = {};
  const positionLane = (laneNodes: CodeGraphNode[], startY: number) => {
    laneNodes.forEach((node, index) => {
      const col = index % GRAPH_COLUMNS;
      const row = Math.floor(index / GRAPH_COLUMNS);
      nodePositions[node.id] = {
        x: GRAPH_START_X + col * (NODE_WIDTH + GRAPH_GAP_X),
        y: startY + row * (NODE_HEIGHT + GRAPH_GAP_Y),
      };
    });
    return startY + Math.max(1, Math.ceil(laneNodes.length / GRAPH_COLUMNS)) * (NODE_HEIGHT + GRAPH_GAP_Y);
  };

  const firstLaneLabel = visibleFuncNodes.length > 0 ? 'Product code' : 'Detected checks';
  const firstLaneNodes = visibleFuncNodes.length > 0 ? visibleFuncNodes : visibleTestNodes;
  const secondLaneNodes = visibleFuncNodes.length > 0 ? visibleTestNodes : [];
  const firstLaneY = 112;
  const secondLaneY = positionLane(firstLaneNodes, firstLaneY) + 52;
  const layoutEndY = secondLaneNodes.length > 0 ? positionLane(secondLaneNodes, secondLaneY) : secondLaneY;
  const canvasHeight = Math.max(440, layoutEndY + 42);

  const selectedIncoming = selectedNode ? edges.filter((edge) => edge.target === selectedNode.id).length : 0;
  const selectedOutgoing = selectedNode ? edges.filter((edge) => edge.source === selectedNode.id).length : 0;

  return (
    <div className="space-y-6 my-4 sm:my-6 min-w-0">
      {/* Target Repository Selector Toolbar */}
      <div className="glass-card p-4 rounded-lg border border-zinc-800 flex flex-col xl:flex-row items-start xl:items-center justify-between gap-4 min-w-0">
        <div className="flex items-center gap-3 min-w-0">
          <FolderGit2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <div className="min-w-0">
            <span className="text-xs font-mono font-bold text-white uppercase tracking-wider block">
              AST Target Codebase Repository
            </span>
            <span className="text-[11px] text-zinc-400 font-mono block truncate max-w-full">
              Switch repository to parse dynamic AST nodes & call dependency edges
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full xl:w-auto min-w-0">
          {['enterprise_app', 'calculator_app', 'ecommerce_api', 'data_processor'].map((repo) => (
            <button
              key={repo}
              onClick={() => handleSelectRepo(repo)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all ${
                activeTargetRepo === repo && !customPathInput
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold'
                  : 'bg-zinc-950 text-zinc-400 border border-zinc-800 hover:text-white'
              }`}
            >
              {repo}
            </button>
          ))}

          <div className="flex items-center gap-1.5 flex-1 basis-full sm:basis-auto min-w-0">
            <input
              type="text"
              placeholder="Or custom GitHub URL / local path..."
              value={customPathInput}
              onChange={(e) => setCustomPathInput(e.target.value)}
              className="bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-zinc-500 w-full sm:w-72 min-w-0"
            />
            <button
              onClick={handleLoadCustomPath}
              className="bg-zinc-800 hover:bg-zinc-700 text-white p-1.5 rounded-lg border border-zinc-700 transition-colors shrink-0"
              title="Parse custom repository AST"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Main Graph Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 min-w-0">
        {/* Left 2 Cols: Interactive Graph Canvas & Controls */}
        <div className="xl:col-span-2 glass-card p-4 sm:p-6 rounded-lg border border-zinc-800 min-w-0">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6 pb-4 border-b border-zinc-800">
            <div className="min-w-0">
              <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-emerald-400" />
                AST Dependency Topology ({nodes.length} Nodes, {edges.length} Call Edges)
              </h2>
              <p className="text-xs text-zinc-400 font-sans mt-0.5 truncate max-w-full sm:max-w-md">
                Active codebase: <span className="text-emerald-300 font-mono font-semibold">{activeTargetLabel}</span>
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
              {/* View Mode Switcher */}
              <div className="flex items-center gap-1 bg-zinc-950 p-1 rounded-lg border border-zinc-800 sm:mr-2">
                <button
                  onClick={() => setViewMode('visual')}
                  className={`p-1.5 rounded-md text-xs font-mono transition-all ${
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
                  className={`p-1.5 rounded-md text-xs font-mono transition-all ${
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
                className={`px-3 py-1 rounded-lg text-xs font-mono transition-all ${
                  filterType === 'all'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold'
                    : 'bg-zinc-900 text-zinc-400 hover:text-white'
                }`}
              >
                All ({nodes.length})
              </button>
              <button
                onClick={() => setFilterType('functions')}
                className={`px-3 py-1 rounded-lg text-xs font-mono transition-all ${
                  filterType === 'functions'
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-semibold'
                    : 'bg-zinc-900 text-zinc-400 hover:text-white'
                }`}
              >
                Functions ({funcNodes.length})
              </button>
              <button
                onClick={() => setFilterType('tests')}
                className={`px-3 py-1 rounded-lg text-xs font-mono transition-all ${
                  filterType === 'tests'
                    ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 font-semibold'
                    : 'bg-zinc-900 text-zinc-400 hover:text-white'
                }`}
              >
                Tests ({testNodes.length})
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
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg pl-10 pr-4 py-2 text-xs font-mono text-white focus:outline-none focus:border-zinc-500"
            />
          </div>

          {/* VISUAL SVG TOPOLOGY GRAPH */}
          {viewMode === 'visual' && (
            <div className="relative bg-zinc-950/90 border border-zinc-800 rounded-lg overflow-auto max-h-[560px]">
              {isLoading ? (
                <div className="text-xs font-mono text-emerald-400 flex items-center justify-center gap-2 py-16">
                  <RefreshCw className="w-4 h-4 animate-spin" /> Parsing AST Directed Dependency Graph...
                </div>
              ) : nodes.length === 0 ? (
                <div className="empty-panel m-4">
                  <FileCode2 className="w-7 h-7 text-zinc-600 mx-auto mb-2" />
                  <p>No symbols were found in {activeTargetLabel}. Try a repository with Python, JS/TS, or C++ source files.</p>
                </div>
              ) : (
                <svg viewBox={`0 0 ${GRAPH_WIDTH} ${canvasHeight}`} className="w-[980px] max-w-none lg:w-full h-auto min-h-[430px]">
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
                    <filter id="node-shadow" x="-20%" y="-20%" width="140%" height="140%">
                      <feDropShadow dx="0" dy="10" stdDeviation="10" floodColor="#000000" floodOpacity="0.28" />
                    </filter>
                    <pattern id="graph-grid" width="36" height="36" patternUnits="userSpaceOnUse">
                      <path d="M 36 0 L 0 0 0 36" fill="none" stroke="#27272a" strokeWidth="1" />
                    </pattern>
                  </defs>

                  <rect x="0" y="0" width={GRAPH_WIDTH} height={canvasHeight} fill="url(#graph-grid)" opacity="0.28" />
                  <text x="36" y="36" fill="#f4f4f5" className="text-[14px] font-sans font-semibold">
                    {visibleEdges.length > 0 ? 'Dependency path' : 'Symbol map'}
                  </text>
                  <text x="36" y="58" fill="#a1a1aa" className="text-[11px] font-sans">
                    {visibleEdges.length > 0
                      ? 'Click a symbol to inspect its call links and file location.'
                      : 'No call links were detected in this view, so symbols are grouped for easier scanning.'}
                  </text>
                  <g transform="translate(760 24)">
                    <rect width="178" height="34" rx="8" fill={visibleEdges.length > 0 ? '#052e25' : '#18181b'} stroke={visibleEdges.length > 0 ? '#047857' : '#3f3f46'} />
                    <text x="14" y="21" fill={visibleEdges.length > 0 ? '#6ee7b7' : '#a1a1aa'} className="text-[11px] font-mono font-bold">
                      {visibleEdges.length} visible edge{visibleEdges.length === 1 ? '' : 's'}
                    </text>
                  </g>

                  <text x="36" y={firstLaneY - 24} fill="#34d399" className="text-[11px] font-mono font-bold uppercase tracking-wider">
                    {firstLaneLabel}
                  </text>
                  {secondLaneNodes.length > 0 && (
                    <text x="36" y={secondLaneY - 24} fill="#c084fc" className="text-[11px] font-mono font-bold uppercase tracking-wider">
                      Verification checks
                    </text>
                  )}

                  {/* Render Directed Call Edges */}
                  {visibleEdges.map((edge, idx) => {
                    const srcPos = nodePositions[edge.source];
                    const tgtPos = nodePositions[edge.target];
                    if (!srcPos || !tgtPos) return null;

                    const isConnectedToSelected =
                      selectedNode?.id === edge.source || selectedNode?.id === edge.target;

                    return (
                      <g key={`edge-${idx}`}>
                        <line
                          x1={srcPos.x + NODE_WIDTH / 2}
                          y1={srcPos.y + NODE_HEIGHT / 2}
                          x2={tgtPos.x + NODE_WIDTH / 2}
                          y2={tgtPos.y + NODE_HEIGHT / 2}
                          stroke={isConnectedToSelected ? '#10b981' : '#3f3f46'}
                          strokeWidth={isConnectedToSelected ? '2.2' : '1.1'}
                          strokeDasharray={isConnectedToSelected ? 'none' : '4 5'}
                          markerEnd="url(#arrowhead-dynamic)"
                          className="transition-all duration-300"
                        />
                      </g>
                    );
                  })}

                  {/* Render Node Symbols */}
                  {filteredNodes.map((node) => {
                    const pos = nodePositions[node.id] || { x: GRAPH_WIDTH / 2, y: canvasHeight / 2 };
                    const isSelected = selectedNode?.id === node.id;
                    const isLinked =
                      selectedNode?.id === node.id ||
                      visibleEdges.some((edge) =>
                        (edge.source === selectedNode?.id && edge.target === node.id) ||
                        (edge.target === selectedNode?.id && edge.source === node.id)
                      );
                    const label = node.label.length > 34 ? `${node.label.slice(0, 31)}...` : node.label;
                    const fileLabel = fileNameFromPath(node.file_path);

                    return (
                      <g
                        key={node.id}
                        onClick={() => setSelectedNode(node)}
                        className="cursor-pointer group"
                      >
                        <rect
                          x={pos.x}
                          y={pos.y}
                          width={NODE_WIDTH}
                          height={NODE_HEIGHT}
                          rx="10"
                          fill={isSelected ? '#082f24' : node.is_test ? '#1c0f2e' : '#071d2a'}
                          stroke={isSelected ? '#34d399' : isLinked ? '#10b981' : node.is_test ? '#6d28d9' : '#0e7490'}
                          strokeWidth={isSelected ? '2' : '1'}
                          filter={isSelected ? 'url(#node-shadow)' : undefined}
                          className="transition-all duration-200 group-hover:opacity-95"
                        />
                        <circle
                          cx={pos.x + 22}
                          cy={pos.y + 30}
                          r="8"
                          fill={node.is_test ? '#a855f7' : '#06b6d4'}
                        />
                        <text
                          x={pos.x + 40}
                          y={pos.y + 25}
                          fill="#f4f4f5"
                          className="text-[11px] font-sans font-semibold select-none"
                        >
                          {label}
                        </text>
                        <text
                          x={pos.x + 40}
                          y={pos.y + 43}
                          fill="#a1a1aa"
                          className="text-[10px] font-mono select-none"
                        >
                          {nodeKindLabel(node)} / {fileLabel.length > 23 ? `${fileLabel.slice(0, 20)}...` : fileLabel}
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
                        className={`p-3.5 rounded-lg border text-left transition-all duration-200 ${
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
                        <div className="text-[10px] text-zinc-600 mt-1">{folderNameFromPath(node.file_path)}</div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Col: AST Symbol Inspector */}
        <div className="glass-card p-4 sm:p-6 rounded-lg border border-zinc-800 flex flex-col justify-between min-w-0">
          <div>
            <h3 className="text-xs font-mono font-bold text-zinc-400 uppercase tracking-widest mb-4 flex items-center gap-2">
              <Layers className="w-4 h-4 text-emerald-400" />
              Symbol Inspector
            </h3>

            {selectedNode ? (
              <div className="space-y-4 font-mono">
                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">Symbol Name</span>
                  <div className="text-xs font-bold text-white bg-zinc-950 p-2.5 rounded-lg border border-zinc-800 break-words">
                    {selectedNode.label}
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">Symbol Type</span>
                  <div className="inline-block text-xs font-bold px-2.5 py-1 rounded-md bg-zinc-900 text-emerald-300 border border-zinc-800 uppercase">
                    {nodeKindLabel(selectedNode)}
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">File Location</span>
                  <div className="text-xs text-zinc-300 bg-zinc-950 p-2.5 rounded-lg border border-zinc-800 break-all leading-relaxed">
                    {selectedNode.file_path}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-2.5">
                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider block">Calls out</span>
                    <span className="text-lg font-semibold text-white">{selectedOutgoing}</span>
                  </div>
                  <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-2.5">
                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider block">Called by</span>
                    <span className="text-lg font-semibold text-white">{selectedIncoming}</span>
                  </div>
                </div>

                <div>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-1">Classification</span>
                  <div
                    className={`text-xs px-2.5 py-1.5 rounded-lg border ${
                      selectedNode.is_test
                        ? 'bg-purple-950/40 text-purple-300 border-purple-800/50'
                        : 'bg-emerald-950/40 text-emerald-300 border-emerald-800/50'
                    }`}
                  >
                    {selectedNode.is_test ? 'Verification check' : 'Product code symbol'}
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
            <span>Language graph: {languageLabel}</span>
            <GitBranch className="w-3.5 h-3.5 text-emerald-400" />
          </div>
        </div>
      </div>
    </div>
  );
};
