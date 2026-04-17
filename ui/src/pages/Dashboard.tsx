import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { refreshAuthTokens, STORAGE_KEY_TOKENS, type Tokens } from '../api/auth';
import {
  ApiError,
  deleteDataSource,
  listDataSources,
  uploadDataSource,
  type DataSource,
} from '../api/dataSources';
import {
  askQuestion,
  deleteConversation,
  getConversation,
  getExcelSchema,
  getSchemaInfo,
  getSuggestedQuestions,
  getUsageSummary,
  listConversations,
  processDataSource,
  type AskQuestionResponse,
  type Conversation,
  type ConversationListItem,
  type ExcelSchemaResponse,
  type SchemaInfoResponse,
  type UsageSummaryResponse,
} from '../api/excelAgent';
import Layout from '../components/Layout';

type ChatEntry =
  | { type: 'user'; content: string }
  | { type: 'assistant'; content: string; result?: AskQuestionResponse; error?: string | null };

type CapabilityMode = 'query' | 'diagnostic' | 'simulation' | 'monitoring';

const CAPABILITY_MODES: { id: CapabilityMode; label: string; tagline: string; available: boolean }[] = [
  { id: 'query', label: 'Query', tagline: 'Answer novel questions', available: true },
  { id: 'diagnostic', label: 'Diagnostic', tagline: 'Explain the variance', available: true },
  { id: 'simulation', label: 'Simulation', tagline: 'Stress-test before committing', available: true },
  { id: 'monitoring', label: 'Monitoring', tagline: 'Catch issues before reports', available: false },
];


const REASONING_STAGES: { agent: string; message: string }[] = [
  { agent: 'Planner', message: 'Decomposing the query · identifying tables and required joins.' },
  { agent: 'Data Agent', message: 'Executing pandas operations on the live workbook.' },
  { agent: 'Insight', message: 'Quantifying drivers, deltas, and statistical significance.' },
  { agent: 'Simulation', message: 'Recomputing the model under counterfactual parameters.' },
  { agent: 'Validator', message: 'Cross-checking every output. Refusing what cannot be defended.' },
];

const MODE_FALLBACK_PROMPTS: Record<CapabilityMode, string[]> = {
  query: [
    'Which revenue stream contributes the most?',
    'Show total revenue by line item.',
    'List the top 10 records by value.',
  ],
  diagnostic: [
    'Why is Used Vehicle Sales underperforming?',
    'Which segments are driving the variance?',
    'What changed most versus average?',
  ],
  simulation: [
    'What if Used Vehicle Sales increase by 15%?',
    'What if margins improve by 5%?',
    'What if volume drops by 10%?',
  ],
  monitoring: [
    'Which metrics are drifting this week?',
    'Has any column changed type or scale?',
    'Recommend KPIs from current usage.',
  ],
};

interface TableView {
  name: string;
  description: string;
  rowCount: number;
  columns: string[];
  primaryKey?: string | null;
}

interface RelationshipView {
  from: string;
  to: string;
  key: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function getWorkbookTables(schema: ExcelSchemaResponse | null): TableView[] {
  if (!schema || !isRecord(schema.semantic_schema)) return [];
  const semanticTables = asArray(schema.semantic_schema.tables).filter(isRecord);

  return semanticTables.map((table) => ({
    name: String(table.table_name ?? ''),
    description: String(table.description ?? ''),
    rowCount: Number(table.row_count ?? 0),
    primaryKey: typeof table.primary_key === 'string' ? table.primary_key : null,
    columns: asArray(table.columns)
      .filter(isRecord)
      .map((column) => String(column.name ?? ''))
      .filter(Boolean),
  }));
}

function getSemanticSummary(schema: ExcelSchemaResponse | null) {
  if (!schema || !isRecord(schema.enrichment)) {
    return { summary: '', entities: [] as string[], metrics: [] as string[] };
  }
  const semanticModel = isRecord(schema.enrichment.semantic_model) ? schema.enrichment.semantic_model : {};
  return {
    summary: String(semanticModel.summary ?? ''),
    entities: asArray(semanticModel.entities).map(String),
    metrics: asArray(semanticModel.metrics).map(String),
  };
}

function inferRelationships(tables: TableView[]): RelationshipView[] {
  const ignored = new Set(['month', 'date', 'notes', 'type', 'name']);
  const relationships: RelationshipView[] = [];

  for (let i = 0; i < tables.length; i += 1) {
    for (let j = i + 1; j < tables.length; j += 1) {
      const left = tables[i];
      const right = tables[j];
      const shared = left.columns.find((column) => {
        const normalized = column.trim().toLowerCase();
        return right.columns.some((candidate) => candidate.trim().toLowerCase() === normalized) && !ignored.has(normalized);
      });

      if (shared) {
        relationships.push({ from: left.name, to: right.name, key: shared });
      }
    }
  }

  return relationships.slice(0, 8);
}

function ModeTabs({
  active,
  onChange,
}: {
  active: CapabilityMode;
  onChange: (mode: CapabilityMode) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {CAPABILITY_MODES.map((mode) => {
        const isActive = mode.id === active;
        return (
          <button
            key={mode.id}
            onClick={() => mode.available && onChange(mode.id)}
            disabled={!mode.available}
            title={mode.tagline}
            className={`rounded-md px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] transition ${
              isActive
                ? 'bg-[#8243EA]/15 text-[#d8c9ff] shadow-[inset_0_0_0_1px_rgba(130,67,234,0.4)]'
                : 'text-gray-500 hover:text-gray-200'
            } ${!mode.available ? 'cursor-not-allowed opacity-40' : ''}`}
          >
            {mode.label}
            {!mode.available && <span className="ml-1.5 text-[9px] text-gray-600">soon</span>}
          </button>
        );
      })}
    </div>
  );
}

function ChatCanvas({
  entries,
  scrollRef,
  emptyState,
  isAsking,
  theater,
  onViewReasoning,
}: {
  entries: ChatEntry[];
  scrollRef: React.RefObject<HTMLDivElement | null>;
  emptyState: React.ReactNode;
  isAsking: boolean;
  theater?: React.ReactNode;
  onViewReasoning?: (result: AskQuestionResponse) => void;
}) {
  return (
    <div ref={scrollRef} className="flex-1 overflow-auto px-6">
      <div className="mx-auto w-full max-w-4xl space-y-6 py-6">
        {entries.length === 0 && !isAsking ? emptyState : null}
        {entries.map((entry, index) => (
          <MessageRow key={`${entry.type}-${index}`} entry={entry} onViewReasoning={onViewReasoning} />
        ))}
        {isAsking && theater}
      </div>
    </div>
  );
}

function MessageRow({ entry, onViewReasoning }: { entry: ChatEntry; onViewReasoning?: (result: AskQuestionResponse) => void }) {
  if (entry.type === 'user') {
    return (
      <div className="agentic-slide-up flex justify-end">
        <div className="max-w-[88%] rounded-2xl rounded-br-md bg-[linear-gradient(135deg,#1c1335,#16182a)] px-4 py-2.5 text-[15px] leading-6 text-white shadow-[0_8px_24px_rgba(77,35,165,0.18)]">
          {entry.content}
        </div>
      </div>
    );
  }
  return <AssistantMessage entry={entry} onViewReasoning={onViewReasoning} />;
}

function AssistantMessage({ entry, onViewReasoning }: { entry: Extract<ChatEntry, { type: 'assistant' }>; onViewReasoning?: (result: AskQuestionResponse) => void }) {
  const result = entry.result;

  return (
    <div className="agentic-slide-up">
      <div className="mb-3 flex h-6 w-6 items-center justify-center rounded-md bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[9px] font-bold uppercase tracking-wide text-white">
        DI
      </div>

      <p className="text-[19px] font-medium leading-8 text-white">{entry.content}</p>

      {result?.insight_card && (
        <div className="mt-4 rounded-xl border border-[#8243EA]/30 bg-[linear-gradient(135deg,rgba(130,67,234,0.14),rgba(37,99,235,0.06))] p-4">
          <p className="text-[10px] uppercase tracking-[0.22em] text-[#d8c9ff]">Insight</p>
          <p className="mt-1 text-sm leading-6 text-gray-100">{result.insight_card.message}</p>
        </div>
      )}

      {result?.simulation && (
        <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <p className="text-[10px] uppercase tracking-[0.22em] text-gray-500">Scenario</p>
          <p className="mt-1.5 text-sm leading-6 text-gray-200">{result.simulation.summary}</p>
        </div>
      )}

      {result && onViewReasoning && (
        <button
          onClick={() => onViewReasoning(result)}
          className="mt-4 inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-gray-500 hover:text-[#bca7ff] transition"
        >
          View reasoning
          <span aria-hidden>→</span>
        </button>
      )}

      {entry.error && !result && (
        <p className="mt-3 rounded-xl border border-amber-400/25 bg-amber-500/10 p-3 text-xs text-amber-200">{entry.error}</p>
      )}
    </div>
  );
}

const AGENT_NODES = [
  { id: 'planner', symbol: 'P', label: 'Planner', role: 'Decomposes the query into sub-tasks.' },
  { id: 'data', symbol: 'D', label: 'Data Agent', role: 'Executes SQL · pandas · UDFs on source data.' },
  { id: 'insight', symbol: 'I', label: 'Insight', role: 'Quantifies drivers, deltas, significance.' },
  { id: 'simulation', symbol: 'S', label: 'Simulation', role: 'Recomputes the model under counterfactuals.' },
  { id: 'validator', symbol: 'V', label: 'Validator', role: 'Cross-checks every output. Refuses orphan answers.' },
];

function classifyAgentNode(agent: string): string | null {
  const normalized = agent.toLowerCase();
  if (normalized.includes('planner')) return 'planner';
  if (normalized.includes('data')) return 'data';
  if (normalized.includes('insight')) return 'insight';
  if (normalized.includes('simulation')) return 'simulation';
  if (normalized.includes('validator')) return 'validator';
  return null;
}

function ReasoningTheater({
  progress,
  pendingResult,
  question,
}: {
  progress: number;
  pendingResult: AskQuestionResponse | null | undefined;
  question: string;
}) {
  const N = AGENT_NODES.length;
  const clamped = Math.min(Math.max(progress, 0), N);
  const currentIdx = Math.min(Math.floor(clamped), N - 1);
  const activeNode = AGENT_NODES[currentIdx];
  const activeMessage = REASONING_STAGES[currentIdx]?.message ?? '';
  const overallPct = (clamped / N) * 100;

  return (
    <div className="agentic-slide-up cockpit-glow-border relative overflow-hidden rounded-3xl border-2 bg-[linear-gradient(180deg,#fdfcff,#f3f1fb)] text-[#0f1020] shadow-[0_30px_80px_rgba(130,67,234,0.18)]">
      <div className="cockpit-grid-light absolute inset-0 opacity-100" />

      <div className="relative flex items-center justify-between border-b border-[#e3e5ee] bg-white/85 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-3 min-w-0">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold uppercase text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">DI</span>
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-[0.32em] text-[#7a7d92] font-bold">Agent Engine · live</p>
            <p className="truncate text-sm font-semibold text-[#0f1020]">"{question}"</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-md bg-[#8243EA]/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-[#5b21b6]">
            Step {Math.min(currentIdx + 1, N)} / {N}
          </span>
          <span className="hidden font-mono text-[10px] text-[#9ea0b3] md:inline">
            {pendingResult ? 'response staged' : 'awaiting response…'}
          </span>
        </div>
      </div>

      <div className="relative h-1 overflow-hidden bg-[#eef0f7]">
        <div
          className="h-full bg-[linear-gradient(90deg,#8243EA,#2563EB)]"
          style={{ width: `${overallPct}%` }}
        />
      </div>

      <div className="relative px-6 pt-6 pb-2">
        <div className="relative grid grid-cols-5 items-start gap-0">
          {AGENT_NODES.map((node, index) => {
            const activation = Math.max(0, Math.min(2, clamped - index));

            const pendingOpacity = Math.max(0, 1 - activation * 2.2);
            const activeOpacity = activation <= 1
              ? Math.min(1, activation * 2)
              : Math.max(0, (1.6 - activation) * 1.8);
            const doneOpacity = Math.max(0, Math.min(1, (activation - 0.85) * 2.2));

            const graySymbolOpacity = pendingOpacity;
            const whiteSymbolOpacity = activation <= 1
              ? Math.min(1, activation * 2.5)
              : Math.max(0, (1.4 - activation) * 2);
            const checkOpacity = Math.max(0, Math.min(1, (activation - 1) * 2.5));

            const scale = 0.92 + Math.min(activation, 1) * 0.08;
            const glowStrength = Math.min(1, activation <= 1 ? activation : Math.max(0, 1.8 - activation));

            const labelDarkness = Math.min(1, activation * 1.5);
            const labelColor = `rgba(15, 16, 32, ${0.38 + labelDarkness * 0.62})`;
            const numberColor = activation >= 1
              ? `rgba(4, 120, 87, ${Math.min(1, (activation - 0.8) * 2)})`
              : activation > 0
                ? `rgba(91, 33, 182, ${Math.min(1, activation * 1.5)})`
                : '#cfd1de';

            const connectorFill = Math.max(0, Math.min(1, clamped - index));
            const connectorGreen = Math.max(0, Math.min(1, (clamped - index - 1) * 2));

            return (
              <div key={node.id} className="relative flex flex-col items-center">
                {index < N - 1 && (
                  <div className="absolute left-1/2 top-7 z-0 h-1 w-full -translate-y-1/2 overflow-hidden rounded-full bg-[#e7e9f1]">
                    <div
                      className="absolute inset-y-0 left-0 bg-[linear-gradient(90deg,#8243EA,#2563EB)]"
                      style={{ width: `${connectorFill * 100}%` }}
                    />
                    <div
                      className="absolute inset-y-0 left-0 bg-emerald-500"
                      style={{ width: `${connectorFill * 100}%`, opacity: connectorGreen }}
                    />
                  </div>
                )}
                <div className="relative z-10 h-14 w-14" style={{ transform: `scale(${scale})`, transformOrigin: 'center' }}>
                  <div
                    className="absolute inset-0 rounded-2xl bg-white"
                    style={{ opacity: pendingOpacity, boxShadow: 'inset 0 0 0 2px #dadcea' }}
                  />
                  <div
                    className="absolute inset-0 rounded-2xl"
                    style={{
                      opacity: activeOpacity,
                      background: 'linear-gradient(135deg,#8243EA,#2563EB)',
                      boxShadow: `0 ${18 * glowStrength}px ${40 * glowStrength}px rgba(130,67,234,${0.45 * glowStrength})`,
                    }}
                  />
                  <div
                    className="absolute inset-0 rounded-2xl"
                    style={{
                      opacity: doneOpacity,
                      background: '#10b981',
                      boxShadow: `0 ${10 * doneOpacity}px ${22 * doneOpacity}px rgba(16,185,129,${0.32 * doneOpacity})`,
                    }}
                  />
                  <div className="relative flex h-full w-full items-center justify-center text-xl font-bold">
                    <span className="absolute text-[#9ea0b3]" style={{ opacity: graySymbolOpacity }}>{node.symbol}</span>
                    <span className="absolute text-white" style={{ opacity: whiteSymbolOpacity }}>{node.symbol}</span>
                    <span className="absolute text-white" style={{ opacity: checkOpacity }}>✓</span>
                  </div>
                </div>
                <p className="mt-2 font-mono text-[10px] font-bold" style={{ color: numberColor }}>0{index + 1}</p>
                <p className="mt-0.5 text-[10px] uppercase tracking-[0.18em] font-bold" style={{ color: labelColor }}>{node.label}</p>
              </div>
            );
          })}
        </div>
      </div>

      <div className="relative grid grid-cols-1 gap-0 lg:grid-cols-[1.2fr_1fr]">
        <div className="relative border-t border-[#e3e5ee] px-6 py-5">
          <p className="text-[10px] font-bold uppercase tracking-[0.32em] text-[#5b21b6]">Now executing</p>
          <div key={currentIdx} className="cockpit-trace mt-3 flex items-start gap-4">
            <div className="cockpit-active-pulse flex h-16 w-16 flex-none items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-2xl font-bold text-white">
              {activeNode.symbol}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xl font-semibold leading-tight text-[#0f1020]">{activeNode.label}</p>
              <p className="mt-1.5 text-[15px] leading-6 text-[#3d3f55]">{activeMessage || activeNode.role}</p>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-2 text-[11px] text-[#7a7d92]">
            <div className="flex items-center gap-1">
              <span className="cockpit-dot h-1.5 w-1.5 rounded-full bg-[#8243EA]" style={{ animationDelay: '0s' }} />
              <span className="cockpit-dot h-1.5 w-1.5 rounded-full bg-[#8243EA]" style={{ animationDelay: '0.18s' }} />
              <span className="cockpit-dot h-1.5 w-1.5 rounded-full bg-[#8243EA]" style={{ animationDelay: '0.36s' }} />
            </div>
            <span className="uppercase tracking-[0.18em]">Reasoning</span>
          </div>
        </div>

        <div className="relative border-t border-[#e3e5ee] bg-white/70 px-6 py-5 lg:border-l">
          <p className="text-[10px] font-bold uppercase tracking-[0.32em] text-[#7a7d92]">Timeline</p>
          <ol className="mt-3 space-y-2.5">
            {AGENT_NODES.map((node, index) => {
              const activation = Math.max(0, Math.min(2, clamped - index));
              const itemOpacity = 0.35 + Math.min(1, activation * 1.5) * 0.65;
              const badgePending = Math.max(0, 1 - activation * 2);
              const badgeActive = activation <= 1
                ? Math.min(1, activation * 2)
                : Math.max(0, (1.4 - activation) * 2);
              const badgeDone = Math.max(0, Math.min(1, (activation - 1) * 2));
              const labelCol = activation > 0.3 ? '#5b21b6' : '#9ea0b3';
              const bodyCol = `rgba(61, 63, 85, ${0.4 + Math.min(1, activation * 1.2) * 0.6})`;
              return (
                <li key={node.id} className="flex gap-3" style={{ opacity: itemOpacity }}>
                  <div className="relative mt-0.5 h-6 w-6 flex-none">
                    <span className="absolute inset-0 flex items-center justify-center rounded-md border-2 border-dashed border-[#cfd1de] text-[10px] font-bold text-[#cfd1de]" style={{ opacity: badgePending }}>
                      {index + 1}
                    </span>
                    <span className="absolute inset-0 flex items-center justify-center rounded-md bg-[#8243EA]/15 text-[10px] font-bold text-[#5b21b6]" style={{ opacity: badgeActive }}>
                      {index + 1}
                    </span>
                    <span className="absolute inset-0 flex items-center justify-center rounded-md bg-emerald-500 text-[10px] font-bold text-white" style={{ opacity: badgeDone }}>
                      ✓
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: labelCol }}>
                      {node.label}
                    </p>
                    <p className="text-[12px] leading-snug" style={{ color: bodyCol }}>
                      {REASONING_STAGES[index]?.message}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}


function ReasoningModal({
  result,
  question,
  onClose,
}: {
  result: AskQuestionResponse;
  question: string;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<'narrative' | 'timeline' | 'rows' | 'code'>('narrative');
  const firedIds = new Set<string>();
  for (const log of result.agent_logs) {
    const id = classifyAgentNode(log.agent);
    if (id) firedIds.add(id);
  }
  const narrative = result.reasoning?.narrative ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        className="agentic-slide-up relative w-full max-w-4xl max-h-[85vh] overflow-hidden rounded-3xl border-2 border-[#e3e5ee] bg-[linear-gradient(180deg,#fdfcff,#f3f1fb)] text-[#0f1020] shadow-[0_40px_100px_rgba(0,0,0,0.5)] flex flex-col"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="cockpit-grid-light absolute inset-0 opacity-100 pointer-events-none" />

        <div className="relative flex items-center justify-between border-b border-[#e3e5ee] bg-white/85 px-6 py-4 backdrop-blur">
          <div className="flex items-center gap-3 min-w-0">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold uppercase text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">DI</span>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-[0.32em] text-[#7a7d92] font-bold">Reasoning · defensibility</p>
              <p className="truncate text-sm font-semibold text-[#0f1020]">"{question}"</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition"
          >
            Close
          </button>
        </div>

        <div className="relative border-b border-[#e3e5ee] bg-white/70 px-6 py-5">
          <div className="grid grid-cols-5 items-start">
            {AGENT_NODES.map((node, index) => {
              const fired = firedIds.has(node.id);
              const symbolTone = fired
                ? 'bg-emerald-500 text-white shadow-[0_8px_20px_rgba(16,185,129,0.3)]'
                : 'bg-white text-[#cfd1de] border-2 border-dashed border-[#dadcea]';
              return (
                <div key={node.id} className="relative flex flex-col items-center">
                  {index < AGENT_NODES.length - 1 && (
                    <div className="absolute left-1/2 top-6 z-0 h-1 w-full -translate-y-1/2 overflow-hidden rounded-full bg-[#e7e9f1]">
                      <div className={`h-full transition-all duration-500 ${fired ? 'w-full bg-emerald-500' : 'w-0'}`} />
                    </div>
                  )}
                  <div className={`relative z-10 flex h-12 w-12 items-center justify-center rounded-2xl text-lg font-bold ${symbolTone}`}>
                    {fired ? '✓' : node.symbol}
                  </div>
                  <p className="mt-2 text-[10px] font-bold uppercase tracking-[0.18em] text-[#0f1020]">{node.label}</p>
                </div>
              );
            })}
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Verdict" value={result.success ? 'Verified' : 'Needs review'} tone={result.success ? 'emerald' : 'amber'} />
            <StatCard label="Latency" value={`${result.execution_time_ms} ms`} />
            <StatCard label="Source rows" value={String(result.supporting_data.length)} />
            <StatCard label="Steps" value={String(result.agent_logs.length)} />
          </div>
        </div>

        <div className="relative flex flex-none items-center gap-1 border-b border-[#e3e5ee] bg-white/60 px-4 py-2">
          {(['narrative', 'timeline', 'rows', 'code'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`rounded-md px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.18em] transition ${
                activeTab === tab
                  ? 'bg-[#8243EA]/10 text-[#5b21b6]'
                  : 'text-[#7a7d92] hover:text-[#0f1020]'
              }`}
            >
              {tab === 'narrative' ? 'How it works' :
               tab === 'timeline' ? 'Agent timeline' :
               tab === 'rows' ? `Source rows · ${result.supporting_data.length}` :
               'Executed code'}
            </button>
          ))}
        </div>

        <div className="relative flex-1 overflow-auto bg-white/50 px-6 py-5">
          {activeTab === 'narrative' && (
            narrative.length === 0 ? (
              <p className="text-sm text-[#7a7d92]">No narrative available — try re-running the query after the latest backend build.</p>
            ) : (
              <ol className="space-y-5">
                {narrative.map((step, index) => (
                  <li key={`${step.title}-${index}`} className="relative pl-11">
                    <span className="absolute left-0 top-0 flex h-8 w-8 items-center justify-center rounded-full bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-xs font-bold text-white shadow-[0_6px_16px_rgba(130,67,234,0.3)]">
                      {index + 1}
                    </span>
                    <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[#5b21b6]">
                      {step.title}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-[14px] leading-7 text-[#1f2037]">{step.body}</p>
                  </li>
                ))}
              </ol>
            )
          )}

          {activeTab === 'timeline' && (
            <ol className="space-y-3">
              {result.agent_logs.map((log, index) => (
                <li key={`${log.agent}-${index}`} className="flex gap-3">
                  <span className="mt-0.5 inline-flex h-6 w-6 flex-none items-center justify-center rounded-md bg-emerald-500 text-[10px] font-bold text-white">
                    ✓
                  </span>
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#5b21b6]">{log.agent}</p>
                    <p className="text-[13px] leading-snug text-[#3d3f55]">{log.message}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}

          {activeTab === 'rows' && <LightTable rows={result.supporting_data} />}

          {activeTab === 'code' && (
            <div className="space-y-3">
              <p className="text-[12px] text-[#5a5c70] leading-5">These are the exact operations the Data Agent ran against your workbook. Useful for engineers; the <strong>How it works</strong> tab explains the same thing in plain English.</p>
              <LightCodeBlock label="Pandas (executed)" content={result.query_logic.pandas} />
              <LightCodeBlock label="SQL · translation" content={result.query_logic.sql_like} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: 'emerald' | 'amber' }) {
  const toneClass =
    tone === 'emerald' ? 'text-emerald-700' : tone === 'amber' ? 'text-amber-700' : 'text-[#0f1020]';
  return (
    <div className="rounded-xl border border-[#e3e5ee] bg-white px-3.5 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-[#7a7d92]">{label}</p>
      <p className={`mt-1 font-mono text-base font-bold ${toneClass}`}>{value}</p>
    </div>
  );
}

function LightTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) return <p className="text-sm text-[#7a7d92]">No rows returned.</p>;
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 8);
  return (
    <div className="overflow-x-auto rounded-xl border border-[#e3e5ee] bg-white">
      <table className="w-full min-w-[420px] text-[12px]">
        <thead className="bg-[#f5f6fb]">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 text-left font-bold uppercase tracking-[0.14em] text-[#5a5c70]">
                {column.replaceAll('_', ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-t border-[#e3e5ee]">
              {columns.map((column) => (
                <td key={column} className="px-3 py-2 align-top text-[#0f1020]">
                  {String(row[column] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LightCodeBlock({ label, content }: { label: string; content: string }) {
  return (
    <div className="rounded-xl border border-[#e3e5ee] bg-white p-3.5">
      <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-[#7a7d92]">{label}</p>
      <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-[#0f1020]">
        {content || '— no code —'}
      </pre>
    </div>
  );
}

const TABLE_PALETTE = [
  { band: '#a78bfa', text: '#5b21b6', glow: 'rgba(167,139,250,0.3)' },
  { band: '#60a5fa', text: '#1e40af', glow: 'rgba(96,165,250,0.3)' },
  { band: '#34d399', text: '#047857', glow: 'rgba(52,211,153,0.3)' },
  { band: '#fbbf24', text: '#a16207', glow: 'rgba(251,191,36,0.3)' },
  { band: '#f87171', text: '#b91c1c', glow: 'rgba(248,113,113,0.3)' },
  { band: '#2dd4bf', text: '#0f766e', glow: 'rgba(45,212,191,0.3)' },
  { band: '#f472b6', text: '#9d174d', glow: 'rgba(244,114,182,0.3)' },
];

function WorkbookInspector({
  open,
  onClose,
  tables,
  relationships,
  semanticSummary,
}: {
  open: boolean;
  onClose: () => void;
  tables: TableView[];
  relationships: RelationshipView[];
  semanticSummary: { entities: string[]; metrics: string[] };
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        className="agentic-slide-up relative flex h-[92vh] w-full max-w-[1200px] flex-col overflow-hidden rounded-3xl border-2 border-[#e3e5ee] bg-[linear-gradient(180deg,#fdfcff,#f3f1fb)] text-[#0f1020] shadow-[0_40px_100px_rgba(0,0,0,0.5)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="cockpit-grid-light absolute inset-0 opacity-100 pointer-events-none" />

        <div className="relative flex items-center justify-between border-b border-[#e3e5ee] bg-white/85 px-6 py-4 backdrop-blur">
          <div className="flex items-center gap-3 min-w-0">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] text-[10px] font-bold uppercase text-white shadow-[0_8px_22px_rgba(130,67,234,0.45)]">DI</span>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-[0.32em] text-[#7a7d92] font-bold">Semantic Layer</p>
              <p className="text-base font-semibold text-[#0f1020]">Workbook schema · relationships</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="hidden items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#7a7d92] md:flex">
              <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-sm bg-[#8243EA]" />PK</span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-sm bg-[#f59e0b]" />Dim</span>
              <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-sm bg-[#10b981]" />Metric</span>
            </div>
            <button onClick={onClose} className="rounded-lg border border-[#e3e5ee] bg-white px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-[#5a5c70] hover:border-[#8243EA]/40 hover:text-[#5b21b6] transition">
              Close
            </button>
          </div>
        </div>

        <div className="relative flex-1 overflow-auto px-6 py-6">
          {tables.length === 0 ? (
            <p className="text-sm text-[#7a7d92]">Prepare the workbook to inspect its schema.</p>
          ) : (
            <ERDiagram tables={tables} relationships={relationships} />
          )}
        </div>

        <div className="relative border-t border-[#e3e5ee] bg-white/75 px-6 py-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] text-[#5a5c70]">
            <span><span className="font-bold text-[#0f1020]">{tables.length}</span> tables</span>
            <span><span className="font-bold text-[#0f1020]">{relationships.length}</span> inferred joins</span>
            {semanticSummary.entities.length > 0 && (
              <span className="truncate"><span className="font-bold text-[#0f1020]">Entities:</span> {semanticSummary.entities.slice(0, 6).join(', ')}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

interface TablePositioned extends TableView {
  x: number;
  y: number;
  width: number;
  height: number;
  paletteIndex: number;
}

function ERDiagram({
  tables,
  relationships,
}: {
  tables: TableView[];
  relationships: RelationshipView[];
}) {
  const MAX_COLUMNS = 7;
  const CARD_WIDTH = 260;
  const ROW_HEIGHT = 22;
  const HEADER_HEIGHT = 64;
  const CELL_PADDING_X = 56;
  const CELL_PADDING_Y = 44;
  const cols = Math.min(3, Math.max(1, tables.length));
  const rows = Math.ceil(tables.length / cols);

  const positioned: TablePositioned[] = tables.map((table, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    const visibleColCount = Math.min(table.columns.length, MAX_COLUMNS);
    const height = HEADER_HEIGHT + visibleColCount * ROW_HEIGHT + (table.columns.length > MAX_COLUMNS ? ROW_HEIGHT : 0);
    const cardCellWidth = CARD_WIDTH + CELL_PADDING_X;
    const cardCellHeight = HEADER_HEIGHT + MAX_COLUMNS * ROW_HEIGHT + ROW_HEIGHT + CELL_PADDING_Y;
    return {
      ...table,
      x: col * cardCellWidth + CELL_PADDING_X / 2,
      y: row * cardCellHeight + CELL_PADDING_Y / 2,
      width: CARD_WIDTH,
      height,
      paletteIndex: index % TABLE_PALETTE.length,
    };
  });

  const byName = new Map(positioned.map((table) => [table.name, table]));
  const viewBoxWidth = cols * (CARD_WIDTH + CELL_PADDING_X);
  const viewBoxHeight = rows * (HEADER_HEIGHT + MAX_COLUMNS * ROW_HEIGHT + ROW_HEIGHT + CELL_PADDING_Y);

  const edges = relationships.flatMap((relationship) => {
    const from = byName.get(relationship.from);
    const to = byName.get(relationship.to);
    if (!from || !to) return [];
    const fromCx = from.x + from.width / 2;
    const toCx = to.x + to.width / 2;
    const fromRightSide = toCx > fromCx;
    const fromX = fromRightSide ? from.x + from.width : from.x;
    const toX = fromRightSide ? to.x : to.x + to.width;
    const fromY = from.y + HEADER_HEIGHT / 2;
    const toY = to.y + HEADER_HEIGHT / 2;
    const midX = (fromX + toX) / 2;
    const path = `M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`;
    const labelX = (fromX + toX) / 2;
    const labelY = (fromY + toY) / 2 - 6;
    return [{ key: `${relationship.from}-${relationship.to}-${relationship.key}`, path, labelX, labelY, label: relationship.key }];
  });

  return (
    <svg
      viewBox={`0 0 ${viewBoxWidth} ${viewBoxHeight}`}
      className="block w-full"
      style={{ minHeight: '540px' }}
    >
      <defs>
        <marker id="erArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 Z" fill="#8243EA" />
        </marker>
      </defs>

      {edges.map((edge) => (
        <g key={edge.key}>
          <path d={edge.path} fill="none" stroke="#8243EA" strokeWidth="1.5" strokeDasharray="4 3" markerEnd="url(#erArrow)" opacity={0.75} />
          <g transform={`translate(${edge.labelX - 46}, ${edge.labelY - 10})`}>
            <rect rx="6" ry="6" width="92" height="20" fill="#ffffff" stroke="#e3e5ee" />
            <text x="46" y="14" textAnchor="middle" fontSize="11" fontFamily="monospace" fill="#5b21b6" fontWeight="700">
              {edge.label.length > 14 ? `${edge.label.slice(0, 13)}…` : edge.label}
            </text>
          </g>
        </g>
      ))}

      {positioned.map((table) => {
        const palette = TABLE_PALETTE[table.paletteIndex];
        const visibleCols = table.columns.slice(0, MAX_COLUMNS);
        const extraCount = Math.max(0, table.columns.length - MAX_COLUMNS);
        return (
          <g key={table.name} transform={`translate(${table.x}, ${table.y})`}>
            <rect
              x="0"
              y="0"
              width={table.width}
              height={table.height}
              rx="12"
              ry="12"
              fill="#ffffff"
              stroke={palette.band}
              strokeWidth="1.5"
              style={{ filter: `drop-shadow(0 8px 20px ${palette.glow})` }}
            />
            <rect x="0" y="0" width={table.width} height={HEADER_HEIGHT} rx="12" ry="12" fill={palette.band} />
            <rect x="0" y={HEADER_HEIGHT - 8} width={table.width} height="8" fill={palette.band} />
            <text x="16" y="26" fontSize="13" fontWeight="700" fill="#ffffff">
              {table.name.length > 24 ? `${table.name.slice(0, 23)}…` : table.name}
            </text>
            <text x="16" y="48" fontSize="11" fill="rgba(255,255,255,0.88)">
              {table.rowCount} rows · {table.columns.length} cols
            </text>
            {table.primaryKey && (
              <g transform={`translate(${table.width - 12}, 20)`}>
                <rect x="-52" y="-11" width="52" height="18" rx="4" fill="rgba(255,255,255,0.22)" />
                <text x="-26" y="2" textAnchor="middle" fontSize="10" fontFamily="monospace" fontWeight="700" fill="#ffffff">
                  PK
                </text>
              </g>
            )}

            {visibleCols.map((column, columnIndex) => {
              const y = HEADER_HEIGHT + columnIndex * ROW_HEIGHT;
              const isPk = table.primaryKey === column;
              const dot = isPk ? '#8243EA' : /[$#]|rev|cost|price|total|amount|sale|gross|margin/i.test(column) ? '#10b981' : '#f59e0b';
              const textColor = isPk ? palette.text : '#1f2037';
              const fontWeight = isPk ? '700' : '500';
              return (
                <g key={column} transform={`translate(0, ${y})`}>
                  {columnIndex > 0 && <line x1="12" x2={table.width - 12} y1="0" y2="0" stroke="#eef0f7" />}
                  <circle cx="18" cy={ROW_HEIGHT / 2} r="3" fill={dot} />
                  <text x="32" y={ROW_HEIGHT / 2 + 4} fontSize="11.5" fill={textColor} fontWeight={fontWeight}>
                    {column.length > 26 ? `${column.slice(0, 25)}…` : column}
                  </text>
                </g>
              );
            })}
            {extraCount > 0 && (
              <g transform={`translate(0, ${HEADER_HEIGHT + MAX_COLUMNS * ROW_HEIGHT})`}>
                <text x="32" y={ROW_HEIGHT / 2 + 4} fontSize="11" fill="#7a7d92" fontStyle="italic">
                  + {extraCount} more column{extraCount === 1 ? '' : 's'}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export default function Dashboard() {
  const { isAuthenticated, isLoading, tokens, updateTokens, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [dataSourceTotal, setDataSourceTotal] = useState(0);
  const [isDataSourcesLoading, setIsDataSourcesLoading] = useState(false);
  const [selectedDataSourceId, setSelectedDataSourceId] = useState<string | null>(null);
  const [schemaInfo, setSchemaInfo] = useState<SchemaInfoResponse | null>(null);
  const [workbookSchema, setWorkbookSchema] = useState<ExcelSchemaResponse | null>(null);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isAskingQuestion, setIsAskingQuestion] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatEntry[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [dataSourceName, setDataSourceName] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploadLoading, setIsUploadLoading] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationListItem[]>([]);
  const [conversationsTotal, setConversationsTotal] = useState(0);
  const [isConversationsLoading, setIsConversationsLoading] = useState(false);
  const [usageSummary, setUsageSummary] = useState<UsageSummaryResponse | null>(null);
  const [capabilityMode, setCapabilityMode] = useState<CapabilityMode>('query');
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);
  const [reasoningProgress, setReasoningProgress] = useState(0);
  const [pendingAssistantEntry, setPendingAssistantEntry] = useState<Extract<ChatEntry, { type: 'assistant' }> | null>(null);
  const [animationDone, setAnimationDone] = useState(false);
  const [reasoningModal, setReasoningModal] = useState<AskQuestionResponse | null>(null);
  const rafRef = useRef<number | null>(null);
  const conversationScrollRef = useRef<HTMLDivElement | null>(null);

  const accessToken = tokens?.access_token ?? '';
  const section = location.pathname.split('/')[2] || 'ask-ai';
  const selectedFileSummary = selectedFile ? `${selectedFile.name} (${(selectedFile.size / (1024 * 1024)).toFixed(2)} MB)` : null;
  const latestAssistantEntry = [...chatHistory].reverse().find((entry) => entry.type === 'assistant') as Extract<ChatEntry, { type: 'assistant' }> | undefined;
  const latestResult = latestAssistantEntry?.result;
  const workbookTables = getWorkbookTables(workbookSchema);
  const relationshipViews = useMemo(() => inferRelationships(workbookTables), [workbookTables]);
  const semanticSummary = getSemanticSummary(workbookSchema);
  const workbookReady = Boolean(schemaInfo?.is_ready_for_queries);
  const selectedSource = useMemo(
    () => dataSources.find((source) => source.id === selectedDataSourceId) ?? null,
    [dataSources, selectedDataSourceId]
  );

  const modePrompts = useMemo(() => {
    const fallback = MODE_FALLBACK_PROMPTS[capabilityMode];
    if (capabilityMode === 'monitoring') return fallback;
    if (suggestedQuestions.length === 0) return fallback;

    const filtered = suggestedQuestions.filter((prompt) => {
      const lowered = prompt.toLowerCase();
      if (capabilityMode === 'simulation') return lowered.startsWith('what if');
      if (capabilityMode === 'diagnostic') return lowered.startsWith('why') || lowered.includes('underperform') || lowered.includes('driving') || lowered.includes('variance');
      return !lowered.startsWith('what if') && !lowered.startsWith('why');
    });
    return filtered.length > 0 ? filtered.slice(0, 4) : fallback;
  }, [capabilityMode, suggestedQuestions]);

  const withAuthRetry = async <T,>(requestFn: (token: string) => Promise<T>): Promise<T> => {
    const currentAccessToken = tokens?.access_token;
    if (!currentAccessToken) throw new Error('You must be logged in to continue');

    try {
      return await requestFn(currentAccessToken);
    } catch (error) {
      const status =
        error instanceof ApiError
          ? error.status
          : (typeof error === 'object' && error && 'status' in error ? Number((error as { status: unknown }).status) : 0);
      const isUnauthorized = status === 401;

      let refreshToken: string | undefined = tokens?.refresh_token;
      if (!refreshToken) {
        const storedTokensRaw = localStorage.getItem(STORAGE_KEY_TOKENS);
        if (storedTokensRaw) {
          try {
            const parsed = JSON.parse(storedTokensRaw) as Partial<Tokens>;
            refreshToken = parsed.refresh_token ?? undefined;
          } catch {
            refreshToken = undefined;
          }
        }
      }

      if (!isUnauthorized || !refreshToken) throw error;

      try {
        const refreshed = await refreshAuthTokens(refreshToken);
        const refreshedTokens: Tokens = {
          access_token: refreshed.access_token,
          refresh_token: refreshed.refresh_token,
          token_type: refreshed.token_type,
          expires_in: refreshed.expires_in,
        };
        updateTokens(refreshedTokens);
        return await requestFn(refreshedTokens.access_token);
      } catch {
        logout();
        navigate('/');
        throw new Error('Your session has expired. Please sign in again.');
      }
    }
  };

  const resetAskAI = (dataSourceId: string | null) => {
    setSelectedDataSourceId(dataSourceId);
    setSchemaInfo(null);
    setWorkbookSchema(null);
    setSuggestedQuestions([]);
    setChatHistory([]);
    setCurrentConversationId(null);
    setAskError(null);
    setCapabilityMode('query');
  };

  const fetchDataSources = async () => {
    if (!accessToken) return;
    setIsDataSourcesLoading(true);
    setUploadError(null);
    try {
      const response = await withAuthRetry((token) => listDataSources(token, 0, 50));
      setDataSources(response.items);
      setDataSourceTotal(response.total);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Failed to load data sources');
    } finally {
      setIsDataSourcesLoading(false);
    }
  };

  const fetchConversations = async () => {
    if (!accessToken) return;
    setIsConversationsLoading(true);
    try {
      const response = await withAuthRetry((token) => listConversations(token, null, 0, 50));
      setConversations(response.items);
      setConversationsTotal(response.total);
    } catch (error) {
      console.error('Failed to load conversations', error);
    } finally {
      setIsConversationsLoading(false);
    }
  };

  const fetchUsage = async () => {
    if (!accessToken) return;
    try {
      const summary = await withAuthRetry((token) => getUsageSummary(token, 30));
      setUsageSummary(summary);
    } catch (error) {
      console.error('Failed to load usage summary', error);
    }
  };

  const fetchWorkbookContext = async (dataSourceId: string) => {
    try {
      const info = await withAuthRetry((token) => getSchemaInfo(token, dataSourceId));
      setSchemaInfo(info);

      if (info.is_ready_for_queries) {
        const [schema, suggestions] = await Promise.all([
          withAuthRetry((token) => getExcelSchema(token, dataSourceId)),
          withAuthRetry((token) => getSuggestedQuestions(token, dataSourceId)),
        ]);
        setWorkbookSchema(schema);
        setSuggestedQuestions(suggestions.questions);
      }
    } catch {
      setSchemaInfo(null);
      setWorkbookSchema(null);
      setSuggestedQuestions([]);
    }
  };

  useEffect(() => {
    if (isAuthenticated && accessToken && (section === 'ask-ai' || section === 'my-files')) {
      void fetchDataSources();
    }
    if (isAuthenticated && accessToken && section === 'conversations') {
      void fetchConversations();
      void fetchUsage();
    }
  }, [isAuthenticated, accessToken, section]);

  useEffect(() => {
    if (selectedDataSourceId && accessToken) {
      void fetchWorkbookContext(selectedDataSourceId);
    }
  }, [selectedDataSourceId, accessToken]);

  useEffect(() => {
    if (isAuthenticated && location.pathname === '/dashboard') {
      navigate('/dashboard/ask-ai', { replace: true });
    }
  }, [isAuthenticated, location.pathname, navigate]);

  useEffect(() => {
    if (!conversationScrollRef.current) return;
    conversationScrollRef.current.scrollTop = conversationScrollRef.current.scrollHeight;
  }, [chatHistory.length, latestResult?.query_id]);

  useEffect(() => {
    if (!isAskingQuestion) return;
    setReasoningProgress(0);
    setAnimationDone(false);

    const totalDuration = 6800;
    const startTime = performance.now();

    const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

    const tick = (now: number) => {
      const elapsed = now - startTime;
      const raw = Math.min(elapsed / totalDuration, 1);
      const eased = easeInOutCubic(raw);
      setReasoningProgress(eased * REASONING_STAGES.length);
      if (raw < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setReasoningProgress(REASONING_STAGES.length);
        window.setTimeout(() => setAnimationDone(true), 300);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [isAskingQuestion]);

  useEffect(() => {
    if (animationDone && pendingAssistantEntry) {
      setChatHistory((prev) => [...prev, pendingAssistantEntry]);
      setPendingAssistantEntry(null);
      setIsAskingQuestion(false);
      setAnimationDone(false);
    }
  }, [animationDone, pendingAssistantEntry]);

  const handleProcessDataSource = async () => {
    if (!selectedDataSourceId || !accessToken) return;
    setIsProcessing(true);
    setAskError(null);
    try {
      await withAuthRetry((token) => processDataSource(token, selectedDataSourceId, false));
      await fetchWorkbookContext(selectedDataSourceId);
    } catch (error) {
      setAskError(error instanceof Error ? error.message : 'Failed to process workbook');
    } finally {
      setIsProcessing(false);
    }
  };

  const decoratePromptForMode = (prompt: string): string => {
    const trimmed = prompt.trim();
    const lowered = trimmed.toLowerCase();
    if (capabilityMode === 'simulation' && !lowered.startsWith('what if')) return `What if ${trimmed.replace(/[?.!]+$/, '')}?`;
    if (capabilityMode === 'diagnostic' && !lowered.startsWith('why') && !lowered.includes('underperform')) return `Why ${trimmed.replace(/[?.!]+$/, '').replace(/^(what|how|which|show)\s+/i, '')}?`;
    return trimmed;
  };

  const handleAskQuestion = async (providedQuestion?: string) => {
    const baseQuestion = providedQuestion ?? question;
    if (!baseQuestion.trim() || !selectedDataSourceId || !accessToken) return;
    const nextQuestion = decoratePromptForMode(baseQuestion);

    setIsAskingQuestion(true);
    setAnimationDone(false);
    setPendingAssistantEntry(null);
    setAskError(null);
    setChatHistory((prev) => [...prev, { type: 'user', content: nextQuestion }]);
    setQuestion('');

    try {
      const response = await withAuthRetry((token) =>
        askQuestion(token, selectedDataSourceId, nextQuestion, currentConversationId)
      );
      if (response.conversation_id) setCurrentConversationId(response.conversation_id);

      setPendingAssistantEntry({
        type: 'assistant',
        content: response.answer_text || response.answer || 'No answer returned',
        result: response,
        error: response.success ? null : response.warnings[0] || null,
      });
      void fetchConversations();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to answer question';
      setAskError(message);
      setPendingAssistantEntry({ type: 'assistant', content: message, error: message });
    }
  };

  const handleLoadConversation = async (conversationId: string) => {
    if (!accessToken) return;
    try {
      const conversation: Conversation = await withAuthRetry((token) => getConversation(token, conversationId));
      resetAskAI(conversation.data_source_id);
      setCurrentConversationId(conversation.id);
      setChatHistory(
        conversation.messages.map((message) =>
          message.role === 'user'
            ? { type: 'user', content: message.content }
            : { type: 'assistant', content: message.content, error: message.is_error ? message.error_message : null }
        )
      );
      navigate('/dashboard/ask-ai');
    } catch (error) {
      console.error('Failed to load conversation', error);
    }
  };

  const handleDeleteConversation = async (conversationId: string) => {
    if (!accessToken) return;
    try {
      await withAuthRetry((token) => deleteConversation(token, conversationId));
      await fetchConversations();
    } catch (error) {
      console.error('Failed to delete conversation', error);
    }
  };

  const handleDeleteDataSource = async (dataSource: DataSource) => {
    if (!accessToken) return;
    const confirmed = window.confirm(`Delete "${dataSource.name}"? This cannot be undone.`);
    if (!confirmed) return;
    try {
      await withAuthRetry((token) => deleteDataSource(token, dataSource.id));
      if (selectedDataSourceId === dataSource.id) resetAskAI(null);
      await fetchDataSources();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Failed to delete data source');
    }
  };

  const handleUpload = async () => {
    if (!accessToken) {
      setUploadError('You must be signed in to upload a workbook');
      return;
    }
    setUploadError(null);
    setUploadSuccess(null);
    if (!dataSourceName.trim()) {
      setUploadError('Please provide a data source name');
      return;
    }
    if (!selectedFile) {
      setUploadError('Please select an Excel file');
      return;
    }

    setIsUploadLoading(true);
    try {
      const created = await withAuthRetry((token) => uploadDataSource(token, dataSourceName.trim(), selectedFile));
      setUploadSuccess(`Created data source: ${created.name}`);
      setDataSourceName('');
      setSelectedFile(null);
      setIsCreateModalOpen(false);
      await fetchDataSources();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Upload failed');
    } finally {
      setIsUploadLoading(false);
    }
  };

  if (!isLoading && !isAuthenticated) {
    navigate('/');
    return null;
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#07080f] flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-[#8243EA] border-t-transparent rounded-full" />
      </div>
    );
  }

  const renderAskAI = () => {
    const placeholder = !selectedDataSourceId
      ? 'Select a workbook to begin…'
      : !workbookReady
        ? 'Prepare the workbook to enable execution…'
        : capabilityMode === 'simulation'
          ? 'Describe a scenario, e.g. "Used Vehicle Sales increase by 15%"'
          : capabilityMode === 'diagnostic'
            ? 'Ask why a metric moved, e.g. "Why is Q3 margin off plan?"'
            : 'Ask a question about your data…';

    const statusLabel = workbookReady ? 'Ready' : isProcessing ? 'Preparing…' : selectedSource ? 'Needs prep' : 'No workbook';
    const statusTone = workbookReady ? 'text-emerald-300' : 'text-amber-300';
    const composerDisabled = !selectedDataSourceId || !workbookReady || isAskingQuestion;

    const emptyState = (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-[10px] uppercase tracking-[0.32em] text-[#bca7ff] font-semibold">Ready</p>
        <h2 className="mt-3 text-3xl font-semibold leading-tight text-white">
          Ask a question. <span className="text-gray-500">Get a defensible answer.</span>
        </h2>
        <p className="mt-3 max-w-lg text-sm text-gray-400">
          Every result comes paired with the executed code, the source rows, and a validator trace — inline.
        </p>
        {workbookReady && modePrompts.length > 0 && (
          <div className="mt-8 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
            {modePrompts.slice(0, 4).map((prompt) => (
              <button
                key={prompt}
                onClick={() => void handleAskQuestion(prompt)}
                disabled={isAskingQuestion}
                className="group rounded-xl border border-white/8 bg-[#0d0e18] px-4 py-3 text-left text-sm text-gray-300 transition hover:border-[#8243EA]/40 hover:bg-[#11121d] hover:text-white disabled:opacity-50"
              >
                <span className="block text-[10px] uppercase tracking-[0.18em] text-gray-500 group-hover:text-[#bca7ff]">Try</span>
                <span className="mt-1 block leading-snug">{prompt}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    );

    return (
      <div className="relative flex h-full flex-col">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-64 overflow-hidden">
          <div className="agentic-orb absolute left-[8%] top-10 h-48 w-48 rounded-full bg-[#8243EA]/10" />
          <div className="agentic-orb absolute right-[12%] top-6 h-56 w-56 rounded-full bg-[#2563EB]/8 [animation-delay:1.4s]" />
        </div>

        <header className="relative px-6 pt-5 pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-baseline gap-3">
                <h1 className="text-2xl font-semibold leading-tight text-white">Data Intelligence Platform</h1>
                <span className="hidden text-[10px] uppercase tracking-[0.28em] text-gray-600 sm:inline">Hackathon 2026</span>
              </div>
              <p className="mt-0.5 text-xs text-gray-500">A reasoning layer for structured data — schema-aware, execution-based, multi-agent, explainable.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={selectedDataSourceId || ''}
                onChange={(event) => resetAskAI(event.target.value || null)}
                className="min-w-[200px] rounded-lg border border-white/10 bg-[#0d0e18] px-3 py-1.5 text-sm text-white outline-none focus:border-[#8243EA]/50"
              >
                <option value="">Select a workbook…</option>
                {dataSources.map((source) => (
                  <option key={source.id} value={source.id}>{source.name}</option>
                ))}
              </select>
              {selectedSource && !workbookReady && (
                <button
                  onClick={handleProcessDataSource}
                  disabled={isProcessing}
                  className="rounded-lg border border-[#8243EA]/40 bg-[#8243EA]/15 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#d8c9ff] hover:bg-[#8243EA]/25 disabled:opacity-50"
                >
                  {isProcessing ? 'Preparing…' : 'Prepare'}
                </button>
              )}
              <button
                onClick={() => setIsInspectorOpen(true)}
                disabled={!workbookReady}
                className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-300 hover:border-[#8243EA]/40 hover:text-white disabled:opacity-40"
              >
                Schema
              </button>
              {chatHistory.length > 0 && (
                <button
                  onClick={() => {
                    setChatHistory([]);
                    setCurrentConversationId(null);
                  }}
                  className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-300 hover:text-white"
                >
                  New session
                </button>
              )}
            </div>
          </div>
        </header>

        <div className="relative border-y border-white/8 bg-[#08090f]/60 px-6 py-2">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-gray-500">
            {selectedSource ? (
              <>
                <span className="font-semibold uppercase tracking-[0.18em] text-gray-300">{selectedSource.name}</span>
                <span><span className="font-mono text-gray-300">{selectedSource.sheet_count}</span> sheets</span>
                <span><span className="font-mono text-gray-300">{schemaInfo?.table_count ?? selectedSource.sheet_count}</span> tables</span>
                <span><span className="font-mono text-gray-300">{schemaInfo?.formula_column_count ?? 0}</span> metrics</span>
                <span className="ml-auto inline-flex items-center gap-1.5">
                  <span className={`h-1.5 w-1.5 rounded-full ${workbookReady ? 'bg-emerald-300' : 'bg-amber-300'}`} />
                  <span className={`uppercase tracking-[0.18em] ${statusTone}`}>{statusLabel}</span>
                </span>
              </>
            ) : (
              <span className="text-gray-600">No workbook selected</span>
            )}
          </div>
        </div>

        {(askError || uploadError) && (
          <div className="mx-6 mt-3 rounded-xl border border-red-400/25 bg-red-500/10 p-3 text-sm text-red-200">
            {askError || uploadError}
          </div>
        )}

        <div className="relative flex flex-1 min-h-0 flex-col overflow-hidden">
          {capabilityMode === 'monitoring' ? (
            <div className="flex flex-1 items-center justify-center px-6">
              <div className="max-w-md rounded-2xl border border-dashed border-white/10 bg-[#0d0e18] p-8 text-center">
                <p className="text-[10px] uppercase tracking-[0.32em] text-[#8b8da3] font-semibold">Roadmap · 2027</p>
                <h3 className="mt-3 text-xl font-semibold text-white">Continuous monitoring & alerting</h3>
                <p className="mt-2 text-sm text-gray-400">
                  Schema-drift detection, KPI recommendations, and scheduled executive briefings — shipping next on the enterprise data fabric.
                </p>
              </div>
            </div>
          ) : (
            <ChatCanvas
              entries={chatHistory}
              scrollRef={conversationScrollRef}
              emptyState={emptyState}
              isAsking={isAskingQuestion}
              onViewReasoning={(result) => setReasoningModal(result)}
              theater={
                isAskingQuestion ? (
                  <ReasoningTheater
                    progress={reasoningProgress}
                    pendingResult={pendingAssistantEntry?.result}
                    question={[...chatHistory].reverse().find((entry) => entry.type === 'user')?.content || ''}
                  />
                ) : null
              }
            />
          )}

          <div className="border-t border-white/8 bg-[#08090f]/85 px-6 py-3 backdrop-blur">
            <div className="mx-auto w-full max-w-4xl">
              <div className="rounded-2xl border border-white/10 bg-[#0d0e18] focus-within:border-[#8243EA]/40">
                <div className="flex items-center justify-between border-b border-white/8 px-3 pt-2 pb-1.5">
                  <ModeTabs active={capabilityMode} onChange={setCapabilityMode} />
                </div>
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      void handleAskQuestion();
                    }
                  }}
                  disabled={composerDisabled}
                  placeholder={placeholder}
                  rows={1}
                  className="block w-full resize-none bg-transparent px-4 pt-3 text-[15px] leading-6 text-white outline-none placeholder:text-gray-500"
                />
                <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-2.5 pt-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {modePrompts.slice(0, 3).map((prompt) => (
                      <button
                        key={prompt}
                        onClick={() => void handleAskQuestion(prompt)}
                        disabled={composerDisabled}
                        className="max-w-[260px] truncate rounded-md border border-white/8 bg-white/[0.02] px-2 py-1 text-[11px] text-gray-400 hover:border-[#8243EA]/30 hover:text-white disabled:opacity-50"
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={() => void handleAskQuestion()}
                    disabled={!question.trim() || composerDisabled}
                    className="rounded-md bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-white shadow-[0_8px_20px_rgba(130,67,234,0.3)] disabled:opacity-40"
                  >
                    {isAskingQuestion ? 'Reasoning…' : 'Send'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <WorkbookInspector
          open={isInspectorOpen}
          onClose={() => setIsInspectorOpen(false)}
          tables={workbookTables}
          relationships={relationshipViews}
          semanticSummary={{ entities: semanticSummary.entities, metrics: semanticSummary.metrics }}
        />

        {reasoningModal && (
          <ReasoningModal
            result={reasoningModal}
            question={(() => {
              const userIndex = chatHistory.findLastIndex?.(
                (entry) => entry.type === 'assistant' && entry.result?.query_id === reasoningModal.query_id
              );
              if (typeof userIndex === 'number' && userIndex > 0) {
                const prev = chatHistory[userIndex - 1];
                if (prev.type === 'user') return prev.content;
              }
              return '';
            })()}
            onClose={() => setReasoningModal(null)}
          />
        )}
      </div>
    );
  };

  const renderMyFiles = () => (
    <div className="h-full px-6 pb-8 pt-6 flex flex-col gap-5">
      <header>
        <p className="text-[10px] uppercase tracking-[0.32em] text-[#bca7ff] font-semibold">Library</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">Workbooks ({dataSourceTotal})</h1>
      </header>

      <div className="rounded-2xl border border-white/8 bg-[#0d0e18] flex-1 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/8 flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-[0.22em] text-gray-500">All sources</p>
          <div className="flex gap-2">
            <button
              onClick={() => void fetchDataSources()}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-gray-300 hover:text-white"
            >
              Refresh
            </button>
            <button
              onClick={() => {
                setUploadError(null);
                setUploadSuccess(null);
                setIsCreateModalOpen(true);
              }}
              className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-white"
            >
              + Upload
            </button>
          </div>
        </div>

        {uploadError && <div className="mx-4 mt-4 p-3 rounded-xl bg-red-500/10 border border-red-400/30 text-red-200 text-sm">{uploadError}</div>}
        {uploadSuccess && <div className="mx-4 mt-4 p-3 rounded-xl bg-emerald-500/10 border border-emerald-400/30 text-emerald-200 text-sm">{uploadSuccess}</div>}

        {isDataSourcesLoading ? (
          <div className="h-full flex items-center justify-center">
            <div className="animate-spin h-8 w-8 border-4 border-[#8243EA] border-t-transparent rounded-full" />
          </div>
        ) : dataSources.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <h3 className="text-white font-semibold text-lg">No workbooks yet</h3>
              <p className="text-gray-400 text-sm mt-2">Upload an Excel file to start the demo.</p>
            </div>
          </div>
        ) : (
          <div className="p-4 overflow-auto h-full">
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {dataSources.map((source) => (
                <div key={source.id} className="rounded-2xl border border-white/8 bg-[#11121d] p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-white font-semibold text-base">{source.name}</h3>
                      <p className="text-gray-500 text-xs mt-1">{source.original_file_name}</p>
                    </div>
                    <button
                      onClick={() => void handleDeleteDataSource(source)}
                      className="px-3 py-1 rounded-lg border border-red-400/25 text-red-300 text-xs uppercase tracking-[0.16em] hover:bg-red-500/10"
                    >
                      Delete
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-3 mt-4">
                    {[
                      { label: 'Size', value: `${(source.file_size_bytes / (1024 * 1024)).toFixed(2)} MB` },
                      { label: 'Sheets', value: source.sheet_count },
                      { label: 'Type', value: source.file_extension },
                    ].map((fact) => (
                      <div key={fact.label} className="border-l border-white/8 pl-3">
                        <p className="text-[10px] uppercase tracking-[0.18em] text-gray-500">{fact.label}</p>
                        <p className="text-white font-mono text-sm mt-1">{fact.value}</p>
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {source.sheet_names.slice(0, 6).map((sheet) => (
                      <span key={sheet} className="px-2 py-0.5 rounded border border-white/8 text-[11px] text-gray-400 bg-[#0a0b14]">
                        {sheet}
                      </span>
                    ))}
                    {source.sheet_names.length > 6 && (
                      <span className="px-2 py-0.5 text-[11px] text-gray-500">+{source.sheet_names.length - 6}</span>
                    )}
                  </div>
                  <div className="mt-5 flex gap-2">
                    <button
                      onClick={() => navigate(`/data-source/${source.id}`)}
                      className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-gray-300 hover:text-white"
                    >
                      Inspect
                    </button>
                    <button
                      onClick={() => {
                        navigate('/dashboard/ask-ai');
                        resetAskAI(source.id);
                      }}
                      className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-white"
                    >
                      Query →
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-white/8 bg-[#0d0e18]">
            <div className="px-6 py-4 border-b border-white/8 flex items-center justify-between">
              <h3 className="text-white font-semibold text-lg">Upload Workbook</h3>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="text-gray-400 hover:text-white text-sm"
              >
                Close
              </button>
            </div>
            <form
              className="p-6 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void handleUpload();
              }}
            >
              {uploadError && (
                <div className="rounded-xl bg-red-500/10 border border-red-400/30 p-3 text-sm text-red-200">
                  {uploadError}
                </div>
              )}
              {uploadSuccess && (
                <div className="rounded-xl bg-emerald-500/10 border border-emerald-400/30 p-3 text-sm text-emerald-200">
                  {uploadSuccess}
                </div>
              )}

              <label className="block">
                <span className="text-[10px] uppercase tracking-[0.18em] text-gray-500 font-semibold">Data Source Name</span>
                <input
                  type="text"
                  value={dataSourceName}
                  onChange={(event) => setDataSourceName(event.target.value)}
                  className="mt-2 w-full px-4 py-3 bg-[#11121d] border border-white/8 rounded-xl text-white"
                  placeholder="Dealership Sales Model"
                />
              </label>
              <label className="block">
                <span className="text-[10px] uppercase tracking-[0.18em] text-gray-500 font-semibold">Excel File</span>
                <input
                  type="file"
                  accept=".xlsx,.xls,.xlsm"
                  onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                  className="mt-2 w-full px-4 py-2.5 bg-[#11121d] border border-white/8 rounded-xl text-gray-300 file:mr-4 file:px-3 file:py-1.5 file:rounded-md file:border-0 file:bg-[#8243EA]/25 file:text-[#C4B5FD] file:font-semibold"
                />
                {selectedFileSummary && <p className="text-xs text-gray-500 mt-2">{selectedFileSummary}</p>}
              </label>
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-4 py-2 rounded-lg border border-white/10 text-gray-300 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isUploadLoading || !dataSourceName.trim() || !selectedFile}
                  className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
                >
                  {isUploadLoading ? 'Uploading…' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );

  const renderConversations = () => (
    <div className="h-full px-6 pb-8 pt-6 flex flex-col gap-5">
      <header>
        <p className="text-[10px] uppercase tracking-[0.32em] text-[#bca7ff] font-semibold">History</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">Conversations ({conversationsTotal})</h1>
      </header>

      {usageSummary && (
        <div className="rounded-2xl border border-white/8 bg-[#0d0e18] p-5">
          <p className="text-[10px] uppercase tracking-[0.32em] text-[#8b8da3] font-semibold">Usage · last 30 days</p>
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mt-4">
            {[
              { label: 'Calls', value: usageSummary.total_calls },
              { label: 'Input tokens', value: usageSummary.total_input_tokens.toLocaleString() },
              { label: 'Output tokens', value: usageSummary.total_output_tokens.toLocaleString() },
              { label: 'Cost', value: `$${usageSummary.total_cost_usd.toFixed(4)}` },
            ].map((fact) => (
              <div key={fact.label} className="border-l border-white/8 pl-4">
                <p className="text-[10px] uppercase tracking-[0.22em] text-gray-500">{fact.label}</p>
                <p className="text-white text-2xl font-mono mt-1">{fact.value}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-white/8 bg-[#0d0e18] flex-1 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/8 flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-[0.22em] text-gray-500">All sessions</p>
          <button
            onClick={() => void fetchConversations()}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-gray-300 hover:text-white"
          >
            Refresh
          </button>
        </div>

        {isConversationsLoading ? (
          <div className="h-full flex items-center justify-center">
            <div className="animate-spin h-8 w-8 border-4 border-[#8243EA] border-t-transparent rounded-full" />
          </div>
        ) : conversations.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <h3 className="text-white font-semibold text-lg">No conversations yet</h3>
              <p className="text-gray-400 text-sm mt-2">Run workbook queries to populate your history.</p>
            </div>
          </div>
        ) : (
          <div className="p-4 space-y-3 overflow-auto h-full">
            {conversations.map((conversation) => {
              const source = dataSources.find((dataSource) => dataSource.id === conversation.data_source_id);
              return (
                <div key={conversation.id} className="rounded-2xl border border-white/8 bg-[#11121d] p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-white font-semibold text-sm">{conversation.title}</h3>
                      <p className="text-gray-500 text-xs mt-1">{source?.name || 'Unknown workbook'}</p>
                      <div className="flex flex-wrap gap-4 mt-3 text-[11px] text-gray-500 uppercase tracking-[0.16em]">
                        <span>{conversation.message_count} msgs</span>
                        <span>${conversation.total_cost_usd.toFixed(4)}</span>
                        <span>{new Date(conversation.last_message_at || conversation.created_at).toLocaleString()}</span>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => void handleLoadConversation(conversation.id)}
                        className="rounded-lg bg-[linear-gradient(135deg,#8243EA,#2563EB)] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-white"
                      >
                        Continue
                      </button>
                      <button
                        onClick={() => void handleDeleteConversation(conversation.id)}
                        className="rounded-lg border border-red-400/25 px-3 py-1.5 text-xs uppercase tracking-[0.18em] text-red-300 hover:bg-red-500/10"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  const renderContent = () => {
    switch (section) {
      case 'my-files':
        return renderMyFiles();
      case 'conversations':
        return renderConversations();
      case 'ask-ai':
      default:
        return renderAskAI();
    }
  };

  return <Layout activeNavItem={section} onNavItemClick={(id) => navigate(`/dashboard/${id}`)}>{renderContent()}</Layout>;
}
