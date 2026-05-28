export interface GraphNode {
  id: string;
  label: string;
  value: number;
  tone: "cyan" | "violet" | "emerald" | "amber";
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  weight: number;
}

interface ForceGraphPanelProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  loading?: boolean;
}

const toneClassByNode: Record<GraphNode["tone"], string> = {
  cyan: "graph-node-cyan",
  violet: "graph-node-violet",
  emerald: "graph-node-emerald",
  amber: "graph-node-amber",
};

export function ForceGraphPanel({ nodes, edges, loading = false }: ForceGraphPanelProps) {
  if (loading) {
    return (
      <section className="nexus-panel">
        <header className="nexus-panel-header">
          <h2>Mission Graph</h2>
        </header>
        <div className="nexus-empty">Loading graph topology...</div>
      </section>
    );
  }

  if (!nodes.length) {
    return (
      <section className="nexus-panel">
        <header className="nexus-panel-header">
          <h2>Mission Graph</h2>
        </header>
        <div className="nexus-empty">No graph domains available yet.</div>
      </section>
    );
  }

  const positions = computeRadialLayout(nodes);
  const positionById = new Map(positions.map((entry) => [entry.id, entry]));

  return (
    <section className="nexus-panel">
      <header className="nexus-panel-header">
        <h2>Mission Graph</h2>
        <span>{nodes.length} domains</span>
      </header>
      <svg viewBox="0 0 1000 620" className="nexus-graph" role="img" aria-label="Nexus force graph">
        <defs>
          <linearGradient id="nexusEdgeGradient" x1="0%" x2="100%">
            <stop offset="0%" stopColor="rgba(104, 219, 255, 0.22)" />
            <stop offset="100%" stopColor="rgba(173, 113, 255, 0.35)" />
          </linearGradient>
        </defs>
        {edges.map((edge) => {
          const source = positionById.get(edge.source);
          const target = positionById.get(edge.target);
          if (!source || !target) {
            return null;
          }
          return (
            <line
              key={edge.id}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke="url(#nexusEdgeGradient)"
              strokeWidth={Math.max(1, Math.min(6, edge.weight))}
            />
          );
        })}
        {positions.map((node) => (
          <g key={node.id} transform={`translate(${node.x} ${node.y})`}>
            <circle className={`graph-node ${toneClassByNode[node.tone]}`} r={node.radius} />
            <text className="graph-node-label" textAnchor="middle" y={4}>
              {node.label}
            </text>
          </g>
        ))}
      </svg>
    </section>
  );
}

function computeRadialLayout(nodes: GraphNode[]) {
  const centerX = 500;
  const centerY = 310;
  const orbitRadius = 225;
  return nodes.map((node, index) => {
    if (index === 0) {
      return { ...node, x: centerX, y: centerY, radius: 58 };
    }
    const angle = (Math.PI * 2 * (index - 1)) / Math.max(1, nodes.length - 1);
    const radiusBump = Math.min(20, node.value * 0.5);
    return {
      ...node,
      x: centerX + Math.cos(angle) * orbitRadius,
      y: centerY + Math.sin(angle) * orbitRadius,
      radius: 34 + radiusBump,
    };
  });
}
