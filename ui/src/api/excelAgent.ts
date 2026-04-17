import { API_BASE_URL } from './auth';
import { ApiError } from './dataSources';

export interface ProcessDataSourceResponse {
  schema_id: string;
  data_source_id: string;
  processing_status: string;
  is_ready_for_queries: boolean;
  workbook_title: string | null;
  workbook_purpose: string | null;
  domain: string | null;
  context_header_for_qa: string | null;
  table_count: number;
  relationship_count: number;
  formula_column_count: number;
  queryable_questions: string[];
  data_quality_notes: string[];
  processing_error: string | null;
  processed_at: string | null;
}

export interface ExcelSchemaResponse {
  id: string;
  data_source_id: string;
  processing_status: string;
  is_ready_for_queries: boolean;
  workbook_title: string | null;
  workbook_purpose: string | null;
  domain: string | null;
  context_header_for_qa: string | null;
  manifest: Record<string, unknown>;
  semantic_schema: Record<string, unknown>;
  enrichment: Record<string, unknown>;
  query_routing: Record<string, unknown>;
  queryable_questions: string[];
  data_quality_notes: string[];
  processing_error: string | null;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
}

export interface SchemaInfoResponse {
  data_source_id: string;
  processing_status: string;
  is_ready_for_queries: boolean;
  workbook_title: string | null;
  workbook_purpose: string | null;
  domain: string | null;
  context_header_for_qa: string | null;
  table_count: number;
  relationship_count: number;
  formula_column_count: number;
  queryable_questions_count: number;
  has_data_quality_notes: boolean;
  has_enrichment: boolean;
}

export interface AgentLog {
  agent: string;
  message: string;
}

export interface QueryLogic {
  pandas: string;
  sql_like: string;
}

export interface InsightCard {
  title: string;
  message: string;
}

export interface SimulationResult {
  before_rows: Array<Record<string, unknown>>;
  after_rows: Array<Record<string, unknown>>;
  summary: string;
}

export interface NarrativeStep {
  title: string;
  body: string;
}

export interface Reasoning {
  intent: string | null;
  metric_column: string | null;
  dimension_column: string | null;
  aggregation_op: string | null;
  target_entity: string | null;
  selected_tables: string[];
  row_count: number;
  narrative: NarrativeStep[];
}

export interface AskQuestionResponse {
  success: boolean;
  answer: string;
  answer_text: string | null;
  answer_title: string | null;
  agent_logs: AgentLog[];
  query_logic: QueryLogic;
  supporting_data: Array<Record<string, unknown>>;
  insight_card: InsightCard | null;
  simulation: SimulationResult | null;
  reasoning: Reasoning | null;
  warnings: string[];
  selected_tables: string[];
  execution_time_ms: number;
  query_id: string;
  conversation_id: string | null;
}

export interface SuggestedQuestionsResponse {
  questions: string[];
  data_source_id: string;
}

export interface QueryHistoryItem {
  id: string;
  question: string;
  answer: unknown;
  code_used: string | null;
  success: boolean;
  error_message: string | null;
  execution_time_ms: number | null;
  iterations_used: number;
  created_at: string;
}

export interface QueryHistoryResponse {
  items: QueryHistoryItem[];
  total: number;
}

export interface ConversationMessage {
  id: string;
  role: string;
  content: string;
  code_used: string | null;
  execution_time_ms: number | null;
  is_error: boolean;
  error_message: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  created_at: string;
}

export interface Conversation {
  id: string;
  data_source_id: string;
  title: string;
  is_active: boolean;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  messages: ConversationMessage[];
}

export interface ConversationListItem {
  id: string;
  data_source_id: string;
  title: string;
  total_cost_usd: number;
  message_count: number;
  created_at: string;
  last_message_at: string | null;
}

export interface ConversationListResponse {
  items: ConversationListItem[];
  total: number;
}

export interface UsageSummaryResponse {
  period_days: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_calls: number;
  by_call_type: Record<string, { cost: number; count: number }>;
}

async function parseOrThrow(response: Response, fallbackMessage: string) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, error?.detail || fallbackMessage);
  }

  return response.json();
}

export async function processDataSource(
  accessToken: string,
  dataSourceId: string,
  forceReprocess = false
): Promise<ProcessDataSourceResponse> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/data-sources/${dataSourceId}/process`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ force_reprocess: forceReprocess }),
  });

  return parseOrThrow(response, 'Failed to process data source');
}

export async function getExcelSchema(
  accessToken: string,
  dataSourceId: string
): Promise<ExcelSchemaResponse> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/data-sources/${dataSourceId}/schema`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseOrThrow(response, 'Failed to get schema');
}

export async function getSchemaInfo(
  accessToken: string,
  dataSourceId: string
): Promise<SchemaInfoResponse> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/data-sources/${dataSourceId}/schema/info`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseOrThrow(response, 'Failed to get schema info');
}

export async function askQuestion(
  accessToken: string,
  dataSourceId: string,
  question: string,
  conversationId?: string | null
): Promise<AskQuestionResponse> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/data-sources/${dataSourceId}/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      question,
      conversation_id: conversationId || null,
    }),
  });

  return parseOrThrow(response, 'Failed to ask question');
}

export async function getSuggestedQuestions(
  accessToken: string,
  dataSourceId: string
): Promise<SuggestedQuestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/data-sources/${dataSourceId}/questions/suggested`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseOrThrow(response, 'Failed to get suggested questions');
}

export async function getQueryHistory(
  accessToken: string,
  dataSourceId: string,
  limit = 50
): Promise<QueryHistoryResponse> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/data-sources/${dataSourceId}/queries/history?limit=${limit}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseOrThrow(response, 'Failed to get query history');
}

export async function listConversations(
  accessToken: string,
  dataSourceId?: string | null,
  skip = 0,
  limit = 50
): Promise<ConversationListResponse> {
  const query = new URLSearchParams();
  if (dataSourceId) query.set('data_source_id', dataSourceId);
  query.set('skip', String(skip));
  query.set('limit', String(limit));

  const response = await fetch(`${API_BASE_URL}/excel-agent/conversations?${query.toString()}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseOrThrow(response, 'Failed to list conversations');
}

export async function getConversation(
  accessToken: string,
  conversationId: string
): Promise<Conversation> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/conversations/${conversationId}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseOrThrow(response, 'Failed to get conversation');
}

export async function deleteConversation(
  accessToken: string,
  conversationId: string
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/conversations/${conversationId}`, {
    method: 'DELETE',
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, error?.detail || 'Failed to delete conversation');
  }
}

export async function getUsageSummary(
  accessToken: string,
  days = 30
): Promise<UsageSummaryResponse> {
  const response = await fetch(`${API_BASE_URL}/excel-agent/usage/summary?days=${days}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseOrThrow(response, 'Failed to get usage summary');
}
