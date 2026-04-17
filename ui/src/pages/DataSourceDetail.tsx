import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { refreshAuthTokens, STORAGE_KEY_TOKENS, type Tokens } from '../api/auth';
import {
  ApiError,
  getDataSource,
  type DataSource,
} from '../api/dataSources';
import { getExcelSchema, type ExcelSchemaResponse } from '../api/excelAgent';
import Layout from '../components/Layout';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export default function DataSourceDetail() {
  const { id } = useParams<{ id: string }>();
  const { isAuthenticated, isLoading: authLoading, tokens, updateTokens, logout } = useAuth();
  const navigate = useNavigate();

  const [dataSource, setDataSource] = useState<DataSource | null>(null);
  const [schema, setSchema] = useState<ExcelSchemaResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const accessToken = tokens?.access_token ?? '';

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

  useEffect(() => {
    const fetchData = async () => {
      if (!id || !accessToken) return;
      setIsLoading(true);
      setError(null);

      try {
        const [source, workbookSchema] = await Promise.all([
          withAuthRetry((token) => getDataSource(token, id)),
          withAuthRetry((token) => getExcelSchema(token, id)).catch(() => null),
        ]);

        setDataSource(source);
        setSchema(workbookSchema);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load workbook');
      } finally {
        setIsLoading(false);
      }
    };

    if (isAuthenticated && accessToken) fetchData();
  }, [id, isAuthenticated, accessToken]);

  if (!authLoading && !isAuthenticated) {
    navigate('/');
    return null;
  }

  if (authLoading || isLoading) {
    return (
      <Layout activeNavItem="my-files" onNavItemClick={(navId) => navigate(`/dashboard/${navId}`)}>
        <div className="h-full flex items-center justify-center">
          <div className="animate-spin h-8 w-8 border-4 border-[#8243EA] border-t-transparent rounded-full" />
        </div>
      </Layout>
    );
  }

  if (error || !dataSource) {
    return (
      <Layout activeNavItem="my-files" onNavItemClick={(navId) => navigate(`/dashboard/${navId}`)}>
        <div className="m-4 rounded-2xl border border-red-400/30 bg-red-500/10 p-6 text-red-200">
          {error || 'Workbook not found'}
        </div>
      </Layout>
    );
  }

  const manifest = isRecord(schema?.manifest) ? schema?.manifest : {};
  const semanticSchema = isRecord(schema?.semantic_schema) ? schema?.semantic_schema : {};
  const enrichment = isRecord(schema?.enrichment) ? schema?.enrichment : {};
  const tables = asArray(semanticSchema.tables).filter(isRecord);
  const relationships = asArray(isRecord(enrichment.relationship_graph) ? enrichment.relationship_graph.relationships : []).filter(isRecord);
  const formulas = asArray(isRecord(enrichment.formula_catalog) ? enrichment.formula_catalog.derived_columns : []).filter(isRecord);
  const semanticModel = isRecord(enrichment.semantic_model) ? enrichment.semantic_model : {};
  const quality = isRecord(enrichment.data_quality) ? enrichment.data_quality : {};
  const kpis = asArray(enrichment.kpi_recommendations).filter(isRecord);

  return (
    <Layout activeNavItem="my-files" onNavItemClick={(navId) => navigate(`/dashboard/${navId}`)}>
      <div className="h-full overflow-auto p-4 space-y-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/dashboard/my-files')}
            className="px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white hover:bg-white/10"
          >
            Back
          </button>
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[#A78BFA] font-semibold">Workbook</p>
            <h1 className="text-white text-2xl font-bold mt-1">{dataSource.name}</h1>
            <p className="text-gray-400 text-sm mt-1">{dataSource.original_file_name}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-5">
            <p className="text-gray-400 text-xs uppercase tracking-wide">Sheets</p>
            <p className="text-white text-2xl font-bold mt-2">{dataSource.sheet_count}</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-5">
            <p className="text-gray-400 text-xs uppercase tracking-wide">Tables</p>
            <p className="text-white text-2xl font-bold mt-2">{Number(manifest.table_count ?? 0)}</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-5">
            <p className="text-gray-400 text-xs uppercase tracking-wide">Relationships</p>
            <p className="text-white text-2xl font-bold mt-2">{Number(manifest.relationship_count ?? 0)}</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-5">
            <p className="text-gray-400 text-xs uppercase tracking-wide">Formula Columns</p>
            <p className="text-white text-2xl font-bold mt-2">{Number(manifest.formula_column_count ?? 0)}</p>
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#A78BFA] font-semibold">Overview</p>
          <h2 className="text-white text-xl font-semibold mt-1">{schema?.workbook_title || dataSource.name}</h2>
          <p className="text-gray-300 mt-4 leading-7">
            {schema?.workbook_purpose || 'Process this workbook to generate a table-first reasoning model.'}
          </p>
          {schema?.context_header_for_qa && (
            <div className="mt-4 rounded-xl bg-[#252542] border border-white/10 p-4 text-sm text-gray-300">
              {schema.context_header_for_qa}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-6">
            <p className="text-xs uppercase tracking-[0.2em] text-[#A78BFA] font-semibold">Logical Tables</p>
            <div className="mt-4 space-y-3">
              {tables.length === 0 ? (
                <p className="text-sm text-gray-400">No structured schema is available yet.</p>
              ) : (
                tables.map((table) => (
                  <div key={String(table.table_name)} className="rounded-xl bg-[#252542] border border-white/10 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-white font-semibold">{String(table.table_name).replaceAll('_', ' ')}</h3>
                      {typeof table.primary_key === 'string' && (
                        <span className="px-2 py-1 rounded-full bg-[#8243EA]/20 text-[#C4B5FD] text-xs font-semibold">
                          PK: {table.primary_key}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-300 mt-3">{String(table.description ?? '')}</p>
                    <div className="flex flex-wrap gap-2 mt-3">
                      {asArray(table.columns).filter(isRecord).slice(0, 8).map((column) => (
                        <span key={String(column.name)} className="px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-xs text-gray-300">
                          {String(column.name)}
                        </span>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-6">
            <p className="text-xs uppercase tracking-[0.2em] text-[#A78BFA] font-semibold">Relationship Graph</p>
            <div className="mt-4 space-y-3">
              {relationships.length === 0 ? (
                <p className="text-sm text-gray-400">No inferred relationships yet.</p>
              ) : (
                relationships.map((relationship, index) => (
                  <div key={index} className="rounded-xl bg-[#252542] border border-white/10 p-4">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="px-3 py-1.5 rounded-lg bg-[#8243EA]/20 text-[#C4B5FD] text-sm font-semibold">
                        {String(relationship.left_table)}
                      </span>
                      <span className="text-gray-500">→</span>
                      <span className="px-3 py-1.5 rounded-lg bg-[#6366F1]/15 text-[#C7D2FE] text-sm font-semibold">
                        {String(relationship.right_table)}
                      </span>
                    </div>
                    <p className="text-sm text-gray-300 mt-3">
                      {String(relationship.left_column)} ↔ {String(relationship.right_column)}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">Confidence {Number(relationship.confidence ?? 0).toFixed(2)}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-6">
            <p className="text-xs uppercase tracking-[0.2em] text-[#A78BFA] font-semibold">Semantic Model</p>
            <p className="text-sm text-gray-300 mt-4">{String(semanticModel.summary ?? 'No semantic model has been generated yet.')}</p>
            <div className="mt-4">
              <p className="text-xs uppercase tracking-wide text-gray-500">Entities</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {asArray(semanticModel.entities).map((entity) => (
                  <span key={String(entity)} className="px-2.5 py-1 rounded-lg bg-[#8243EA]/20 text-[#C4B5FD] text-xs border border-[#8243EA]/20">
                    {String(entity)}
                  </span>
                ))}
              </div>
            </div>
            <div className="mt-4">
              <p className="text-xs uppercase tracking-wide text-gray-500">Metrics</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {asArray(semanticModel.metrics).slice(0, 10).map((metric) => (
                  <span key={String(metric)} className="px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-xs text-gray-300">
                    {String(metric)}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-6">
            <p className="text-xs uppercase tracking-[0.2em] text-[#A78BFA] font-semibold">Data Quality And KPIs</p>
            <p className="text-sm text-gray-300 mt-4">{String(quality.summary ?? 'No data quality report is available yet.')}</p>
            <div className="mt-4 space-y-2">
              {asArray(quality.warnings).slice(0, 5).map((warning, index) => (
                <div key={index} className="rounded-xl bg-[#252542] border border-white/10 p-3 text-sm text-yellow-300">
                  {String(warning)}
                </div>
              ))}
            </div>
            <div className="mt-5 space-y-3">
              {kpis.slice(0, 4).map((kpi) => (
                <div key={`${String(kpi.name)}-${String(kpi.formula)}`} className="rounded-xl bg-[#252542] border border-white/10 p-4">
                  <p className="text-white font-semibold">{String(kpi.name)}</p>
                  <p className="text-xs text-[#C4B5FD] mt-1">{String(kpi.formula)}</p>
                  <p className="text-sm text-gray-300 mt-2">{String(kpi.rationale ?? '')}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#1a1a2e]/70 p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#A78BFA] font-semibold">Formula Intelligence</p>
          <div className="mt-4 space-y-3">
            {formulas.length === 0 ? (
              <p className="text-sm text-gray-400">No derived columns were detected.</p>
            ) : (
              formulas.slice(0, 10).map((formula, index) => (
                <div key={index} className="rounded-xl bg-[#252542] border border-white/10 p-4">
                  <p className="text-white font-semibold">{String(formula.column_name)}</p>
                  <p className="text-sm text-gray-300 mt-2">{String(formula.logic ?? '')}</p>
                  <p className="text-xs text-gray-500 mt-2">{String(formula.table_name)} • {String(formula.formula_type)}</p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
