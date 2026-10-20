import React, { useState, useEffect, useCallback } from 'react';
import { message, Tree, Spin, Modal, Input, Select, Button, Tag, Switch, Progress, Table } from 'antd';
import {
  FolderOutlined, FileOutlined, PlusOutlined, DeleteOutlined,
  UndoOutlined, NodeIndexOutlined, TeamOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { logger } from '../services/logger';
import { API_CONFIG } from '../config/apiConfig';
import { httpGet, httpPost } from '../services/httpClient';
import { useSourceStore } from '../stores/sourceStore';
import { useOntologyLabels } from '../stores/ontologyStore';
import { useAbortController } from '../hooks/useAbortController';
import { useSafePolling } from '../hooks/useSafePolling';
import type { BatchStats, FileStat } from '../stores/types';

interface Source {
  id: string;
  name: string;
  path: string;
  source_type: string;
  created_at: string | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
}

interface FileEntry {
  name: string;
  type: 'file' | 'dir';
  path: string;
  size?: number;
  ext?: string;
}

interface SummaryTableColumn {
  /** 列名（源文件表头的原文） */
  n: string;
  /** ③ 的列标注：实体列 / 属性列 / 无意义 */
  r?: string;
  /** 业务解释 */
  d?: string;
  /** 属性挂载的主列 */
  primary?: boolean;
  /** 实体列的归一类型（本体 ObjectType key，仅 r=entity 时有值） */
  t?: string;
}

interface SummarySheet {
  key: string;
  title: string;
  summary?: string;
  columns: SummaryTableColumn[];
  entity_count: number;
  row_count?: number;
  col_count?: number;
  rels: { s?: string; p?: string; o?: string }[];
  skipped_reason?: string | null;
}

interface SummaryNode {
  title: string;
  node_id?: string;
  summary?: string;
  text?: string;
  start_index?: number;
  end_index?: number;
  page_start?: number;
  page_end?: number;
  nodes?: SummaryNode[];
  table_columns?: SummaryTableColumn[];
  table_meta?: {
    row_count?: number;
    col_count?: number;
    rels?: { s?: string; p?: string; o?: string }[];
    skipped_reason?: string | null;
  };
}

const COLUMN_ROLE_LABELS: Record<string, string> = {
  entity: '实体列',
  attribute: '属性列',
  none: '无意义',
};

const COLUMN_ROLE_CLASSES: Record<string, string> = {
  entity: 'table-role-entity',
  attribute: 'table-role-attribute',
  none: 'table-role-none',
};

/** 摘要树里带列标注的节点 = 表格文件的 sheet（正文摘要没有 table_columns 字段，返回空） */
function collectSummarySheets(nodes: SummaryNode[] | undefined): SummarySheet[] {
  const sheets: SummarySheet[] = [];
  const walk = (list: SummaryNode[] | undefined) => {
    (list || []).forEach((node) => {
      if (Array.isArray(node.table_columns)) {
        sheets.push({
          key: node.node_id || node.title || `sheet-${sheets.length}`,
          title: node.title,
          summary: node.summary,
          columns: node.table_columns,
          entity_count: node.table_columns.filter(c => c.r === 'entity').length,
          row_count: node.table_meta?.row_count,
          col_count: node.table_meta?.col_count,
          rels: node.table_meta?.rels || [],
          skipped_reason: node.table_meta?.skipped_reason,
        });
      }
      walk(node.nodes);
    });
  };
  walk(nodes);
  return sheets;
}

type AxiosErrorLike = { response?: { data?: { detail?: string } }; message?: string };

interface OntologyDomain {
  name: string;
  description: string;
  object_type_count: number;
  link_type_count: number;
}

/** 进行中的批量任务（一次只允许一个批量任务在跑，提交前有互斥） */
interface BatchRun {
  kind: 'summary' | 'extract';
  taskId: string;
}

const EXTRACT_DOMAIN_KEY = 'extract_domain';

const DocumentViewer: React.FC = () => {
  const {
    sources, selectedSourceId, fetchSources, createSource, browseFiles: storeBrowseFiles,
    deleteSource: deleteSourceAction, restoreSource: restoreSourceAction,
    setSelectedSourceId, setSelectedFile, setSummary, setEntities,
    summarizeBatch, extractBatch, fetchInventory, setInventory,
  } = useSourceStore();

  // 直接从 store 订阅，消除双重状态
  const files = useSourceStore((s) => s.files) as unknown as FileEntry[];
  const currentPath = useSourceStore((s) => s.currentPath);

  const { getComponentSignal, getLatestSignal } = useAbortController();
  const { labelType, labelDomain } = useOntologyLabels();

  // UI state
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [addSourceModalVisible, setAddSourceModalVisible] = useState(false);
  const [newSourceName, setNewSourceName] = useState('');
  const [newSourcePath, setNewSourcePath] = useState('');
  const [newSourceType, setNewSourceType] = useState<'local' | 's3'>('local');
  const [addingSource, setAddingSource] = useState(false);
  const [sourceSearchText, setSourceSearchText] = useState('');
  const [showDeletedSources, setShowDeletedSources] = useState(false);
  const [restoringSourceId, setRestoringSourceId] = useState<string | null>(null);

  // File browser loading state
  const [filesLoading, setFilesLoading] = useState(false);

  // Selected file & summary state (mirrored from store)
  const selectedFile = useSourceStore((s) => s.selectedFile);
  const summary = useSourceStore((s) => s.summary);
  const entities = useSourceStore((s) => s.entities);
  const inventory = useSourceStore((s) => s.inventory);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [selectedSheet, setSelectedSheet] = useState<string | null>(null);

  // Task polling state
  const [taskId, setTaskId] = useState<string | null>(null);

  // Entity extraction state（异步任务：提交后轮询，完成后从查询口刷新）
  const [extracting, setExtracting] = useState(false);
  const [extractTaskId, setExtractTaskId] = useState<string | null>(null);
  const [ontologyDomains, setOntologyDomains] = useState<OntologyDomain[]>([]);
  const [extractDomain, setExtractDomain] = useState<string>(() => {
    return localStorage.getItem(EXTRACT_DOMAIN_KEY) || 'general';
  });

  // Batch（摘要/抽取共用一个批量任务槽位与一个进度弹窗）
  const [checkedKeys, setCheckedKeys] = useState<React.Key[]>([]);
  const [batchRun, setBatchRun] = useState<BatchRun | null>(null);
  const [batchPercent, setBatchPercent] = useState(0);
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchFinished, setBatchFinished] = useState<BatchStats | null>(null);
  const [batchStoppedFlag, setBatchStoppedFlag] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchKind, setBatchKind] = useState<'summary' | 'extract'>('summary');

  useEffect(() => {
    const loadDomains = async () => {
      try {
        const signal = getLatestSignal('ontology-domains');
        const res = await httpGet<{ domains?: OntologyDomain[] }>(
          API_CONFIG.endpoints.ontology.domains, { signal });
        const list = res.data.domains || [];
        if (list.length === 0) return;
        setOntologyDomains(list);
        setExtractDomain(prev => {
          if (list.some(d => d.name === prev)) return prev;
          const fallback = list.some(d => d.name === 'general') ? 'general' : list[0].name;
          localStorage.setItem(EXTRACT_DOMAIN_KEY, fallback);
          return fallback;
        });
      } catch (err) {
        logger.warning('DocumentViewer', '获取本体域列表失败', err);
      }
    };
    loadDomains();
  }, [getLatestSignal]);

  const filteredSources = (sources as Source[]).filter(s =>
    s.name.toLowerCase().includes(sourceSearchText.toLowerCase()) ||
    s.path.toLowerCase().includes(sourceSearchText.toLowerCase())
  );
  const selectedSourceData = (sources as Source[]).find(s => s.id === selectedSourceId) || null;

  const summarySheets = collectSummarySheets(
    (summary?.structure as unknown as SummaryNode[] | undefined));
  const activeSheet = summarySheets.find(s => s.key === selectedSheet) || null;

  useEffect(() => {
    setSelectedSheet(null);
  }, [summary]);

  // ── Fetch sources ──────────────────────────────────────────────

  const loadSources = useCallback(async (signal?: AbortSignal) => {
    setSourcesLoading(true);
    try {
      await fetchSources(showDeletedSources, signal);
    } catch (err) {
      logger.error('DocumentViewer', '获取文档源列表失败', err);
    } finally {
      setSourcesLoading(false);
    }
  }, [fetchSources, showDeletedSources]);

  useEffect(() => {
    const signal = getComponentSignal();
    loadSources(signal);
  }, [loadSources, getComponentSignal]);

  // ── File inventory（批量面板的状态列 + 完成后刷新）──────────────
  const loadInventory = useCallback(async (sourceId: string, signal?: AbortSignal) => {
    const map = await fetchInventory(sourceId, signal);
    setInventory(map);
  }, [fetchInventory, setInventory]);

  useEffect(() => {
    if (selectedSourceId) {
      void loadInventory(selectedSourceId);
    }
  }, [selectedSourceId, loadInventory]);

  // ── Source CRUD ────────────────────────────────────────────────

  const handleAddSource = async () => {
    if (!newSourceName.trim() || !newSourcePath.trim()) return;
    setAddingSource(true);
    try {
      await createSource(newSourceName.trim(), newSourcePath.trim(), newSourceType);
      message.success('文档源添加成功');
      setAddSourceModalVisible(false);
      setNewSourceName('');
      setNewSourcePath('');
      await loadSources();
    } catch (err: unknown) {
      const e = err as AxiosErrorLike;
      message.error(`添加失败: ${e.response?.data?.detail || e.message}`);
    } finally {
      setAddingSource(false);
    }
  };

  const handleDeleteSource = async (sourceId: string) => {
    try {
      await deleteSourceAction(sourceId);
      message.success('文档源已删除');
      if (selectedSourceId === sourceId) {
        setSelectedSourceId(null);
        useSourceStore.setState({ files: [], currentPath: '' });
        setSelectedFile(null);
        setSummary(null);
        setEntities([]);
      }
      await loadSources();
    } catch (err: unknown) {
      const e = err as AxiosErrorLike;
      message.error(`删除失败: ${e.response?.data?.detail || e.message}`);
    }
  };

  const handleRestoreSource = async (sourceId: string) => {
    setRestoringSourceId(sourceId);
    try {
      await restoreSourceAction(sourceId);
      message.success('文档源已恢复');
      await loadSources();
    } catch (err: unknown) {
      const e = err as AxiosErrorLike;
      message.error(`恢复失败: ${e.response?.data?.detail || e.message}`);
    } finally {
      setRestoringSourceId(null);
    }
  };

  // ── Summary / entities loading ─────────────────────────────────

  const loadSummary = useCallback(async (sourceId: string, file: string, signal?: AbortSignal) => {
    setSummaryLoading(true);
    try {
      const res = await httpGet(API_CONFIG.endpoints.source.summary(sourceId), {
        params: { file },
        signal,
      });
      const data = res.data.summary;
      setSummary(data);
    } catch {
      setSummary(null);
    } finally {
      setSummaryLoading(false);
    }
  }, [setSummary]);

  const loadEntities = useCallback(async (sourceId: string, file: string, signal?: AbortSignal) => {
    try {
      const res = await httpGet(API_CONFIG.endpoints.source.entities(sourceId), {
        params: { file },
        signal,
      });
      const data = res.data.entities || [];
      if (data.length > 0) {
        setEntities(data);
      }
    } catch {
      // Entities don't exist yet — that's fine
    }
  }, [setEntities]);

  // ── Source selection / file browsing ──────────────────────────

  const browseFiles = useCallback(async (sourceId: string, prefix: string, signal?: AbortSignal) => {
    setFilesLoading(true);
    try {
      await storeBrowseFiles(sourceId, prefix, signal);
      setCheckedKeys([]); // 勾选范围 = 当前目录视图，切目录即重置
      // 展开/进入目录时同步拉一次文件状态，避免切视图看到的 Tag 陈旧
      void loadInventory(sourceId, signal);
    } catch (err: unknown) {
      const e = err as AxiosErrorLike;
      message.error(`浏览失败: ${e.response?.data?.detail || e.message}`);
    } finally {
      setFilesLoading(false);
    }
  }, [storeBrowseFiles, loadInventory]);

  const handleSourceChange = useCallback(async (sourceId: string | null) => {
    setSelectedSourceId(sourceId);
    setSelectedFile(null);
    setSummary(null);
    setEntities([]);
    setInventory({});
    setCheckedKeys([]);

    if (!sourceId) {
      // 清空 store 的文件列表
      useSourceStore.setState({ files: [], currentPath: '' });
      return;
    }

    await browseFiles(sourceId, '');
  }, [setSelectedSourceId, setSelectedFile, setSummary, setEntities, setInventory, browseFiles]);

  const handleDirClick = (entry: FileEntry) => {
    if (!selectedSourceId) return;
    browseFiles(selectedSourceId, entry.path);
  };

  const handleFileClick = useCallback(async (entry: FileEntry) => {
    // 从 store 取当前源：异步链路里闭包值可能是切换源之前的旧值
    const sourceId = useSourceStore.getState().selectedSourceId;
    if (!sourceId) return;
    setSelectedFile(entry.path);
    setSummary(null);
    setEntities([]);
    setTaskId(null);
    setSummarizing(false);
    setExtractTaskId(null);
    setExtracting(false);

    const signal = getLatestSignal('file');
    await Promise.all([
      loadSummary(sourceId, entry.path, signal),
      loadEntities(sourceId, entry.path, signal),
    ]);
  }, [setSelectedFile, setSummary, setEntities, getLatestSignal, loadSummary, loadEntities]);

  const handlePathUp = () => {
    if (!selectedSourceId || !currentPath) return;
    const parts = currentPath.split('/');
    parts.pop();
    const parent = parts.join('/');
    browseFiles(selectedSourceId, parent);
  };

  // ── Wiki 引用锚点跳转：定位并打开被引用的文件 ──────────────────

  const applyPendingCitation = useCallback(async () => {
    const raw = sessionStorage.getItem('wiki_pending_doc');
    if (!raw) return;
    sessionStorage.removeItem('wiki_pending_doc');

    let target: { source_id?: string; file?: string };
    try {
      target = JSON.parse(raw);
    } catch {
      return;
    }
    if (!target.source_id || !target.file) return;

    await handleSourceChange(target.source_id);
    const entry = (useSourceStore.getState().files as unknown as FileEntry[])
      .find(f => f.path === target.file);
    if (!entry) {
      message.warning(`引用文件已不存在：${target.file}`);
      return;
    }
    await handleFileClick(entry);
  }, [handleSourceChange, handleFileClick]);

  useEffect(() => {
    void applyPendingCitation();
  }, [applyPendingCitation]);

  const handleBuildSummary = async () => {
    if (!selectedSourceId || !selectedFile) return;
    setSummarizing(true);
    try {
      const signal = getComponentSignal();
      const res = await httpPost(
        API_CONFIG.endpoints.source.summarize(selectedSourceId),
        { file: selectedFile },
        { signal }
      );
      setTaskId(res.data.task_id);
    } catch (err: unknown) {
      const e = err as AxiosErrorLike;
      message.error(`提交概要生成任务失败: ${e.response?.data?.detail || e.message}`);
      setSummarizing(false);
    }
  };

  // Poll task status for document summary generation — 使用 useSafePolling
  useSafePolling(async () => {
    const signal = getComponentSignal();
    const response = await httpGet(API_CONFIG.endpoints.task.get(taskId!), { signal });
    const status = response.data.status;

    if (status === 'completed') {
      setTaskId(null);
      setSummarizing(false);
      if (selectedSourceId && selectedFile) {
        await loadSummary(selectedSourceId, selectedFile);
      }
      if (selectedSourceId) void loadInventory(selectedSourceId);
      message.success('概要生成成功');
    } else if (status === 'failed') {
      setTaskId(null);
      setSummarizing(false);
      message.error(`概要生成失败: ${response.data.error || '未知错误'}`);
    }
  }, 2000, !!taskId);

  // ── 实体提取（异步任务化：提交 → 轮询 → 从查询口刷新结果）──────

  const parseBatchStats = (raw: unknown): BatchStats | null => {
    try {
      const obj = (typeof raw === 'string' ? JSON.parse(raw) : raw) as Partial<BatchStats> | null;
      if (!obj || typeof obj !== 'object') return null;
      return {
        total: Number(obj.total ?? 0),
        succeeded: Number(obj.succeeded ?? 0),
        skipped: Number(obj.skipped ?? 0),
        failed: Number(obj.failed ?? 0),
        failures: Array.isArray(obj.failures) ? obj.failures : [],
        entity_count: obj.entity_count,
        relationship_count: obj.relationship_count,
        wiki_pages: obj.wiki_pages as Record<string, number> | undefined,
      };
    } catch {
      return null;
    }
  };

  const handleExtract = async () => {
    if (!selectedSourceId || !selectedFile) return;
    setExtracting(true);
    try {
      const signal = getComponentSignal();
      const res = await httpPost(
        API_CONFIG.endpoints.source.extract(selectedSourceId),
        { file: selectedFile, domain: extractDomain },
        { signal }
      );
      setExtractTaskId(res.data.task_id);
      message.info('实体提取任务已提交，完成后自动刷新');
    } catch (err: unknown) {
      const e = err as AxiosErrorLike;
      message.error(`提交提取任务失败: ${e.response?.data?.detail || e.message}`);
      setExtracting(false);
    }
  };

  useSafePolling(async () => {
    if (!extractTaskId) return;
    const signal = getComponentSignal();
    try {
      const response = await httpGet(API_CONFIG.endpoints.task.get(extractTaskId), { signal });
      const status = response.data.status as string | undefined;
      if (status === 'completed') {
        setExtractTaskId(null);
        setExtracting(false);
        const stats = parseBatchStats(response.data.result);
        message.success(`实体提取完成: ${stats?.entity_count ?? 0} 个实体, ${stats?.relationship_count ?? 0} 个关系`);
        if (selectedSourceId) void loadInventory(selectedSourceId);
        if (selectedSourceId && selectedFile) await loadEntities(selectedSourceId, selectedFile);
      } else if (status === 'failed') {
        setExtractTaskId(null);
        setExtracting(false);
        message.error(`实体提取失败: ${response.data.error || '未知错误'}`);
      } else if (status === 'stopped') {
        setExtractTaskId(null);
        setExtracting(false);
        message.warning('实体提取任务已停止');
      }
    } catch {
      // 本轮轮询失败，下一轮再取
    }
  }, 2000, !!extractTaskId);

  // ── 批量摘要 / 批量抽取 ───────────────────────────────────────

  /** 批量任务展示标签：体现勾选语义（1 个条目 = 条目本身路径；多个 = 已选 N 项） */
  const buildBatchLabel = (entries: string[]): string => {
    if (entries.length === 1) {
      return entries[0].replace(/\/+$/, '');
    }
    return `已选 ${entries.length} 项`;
  };

  const doSubmitBatch = async (kind: BatchRun['kind'], files: string[]) => {
    if (!selectedSourceId) {
      message.warning('请先选择文档源');
      return;
    }
    setBatchSubmitting(true);
    setBatchKind(kind);
    try {
      const signal = getComponentSignal();
      const taskId = kind === 'summary'
        ? await summarizeBatch(selectedSourceId, files, false, buildBatchLabel(files), signal)
        : await extractBatch(selectedSourceId, files, extractDomain, buildBatchLabel(files), signal);
      setBatchRun({ kind, taskId });
      setBatchPercent(0);
      setBatchFinished(null);
      setBatchError(null);
      setBatchStoppedFlag(false);
      setBatchModalOpen(true);
    } catch (err: unknown) {
      const e = err as AxiosErrorLike;
      message.error(`提交批量任务失败: ${e.response?.data?.detail || e.message}`);
    } finally {
      setBatchSubmitting(false);
    }
  };

  // 统一动作入口：勾选（文件/目录）即批量；未勾选时作用于右侧已选文件
  const submitAction = (kind: BatchRun['kind']) => {
    if (batchRun || batchSubmitting) {
      message.info('已有批量任务在运行，可等待完成或先停止');
      return;
    }
    // 勾选范围 = 当前目录视图；勾到目录条目时由后端递归展开
    const visible = new Set(files.map((f) => f.path));
    const relFiles = checkedKeys.filter(
      (k) => typeof k === 'string' && visible.has(k)
    ) as string[];
    if (relFiles.length > 0) {
      void doSubmitBatch(kind, relFiles);
      return;
    }
    if (selectedFile) {
      if (kind === 'summary') void handleBuildSummary();
      else void handleExtract();
      return;
    }
    message.warning('请先勾选文件/目录，或在右侧点选一个文件');
  };

  const handleStopBatch = async () => {
    if (!batchRun) return;
    try {
      const signal = getComponentSignal();
      await httpPost(API_CONFIG.endpoints.task.stop(batchRun.taskId), undefined, { signal });
      message.info('已请求停止批量任务');
    } catch {
      // 停止失败不打断轮询
    }
  };

  useSafePolling(async () => {
    if (!batchRun) return;
    const signal = getComponentSignal();
    try {
      const response = await httpGet(API_CONFIG.endpoints.task.get(batchRun.taskId), { signal });
      if (typeof response.data.progress === 'number') {
        setBatchPercent(response.data.progress);
      }
      const status = response.data.status as string | undefined;
      if (status === 'completed' || status === 'failed' || status === 'stopped') {
        setBatchStoppedFlag(status === 'stopped');
        setBatchError(status === 'failed' ? (response.data.error as string) || '未知错误' : null);
        setBatchFinished(parseBatchStats(response.data.result));
        const kind = batchRun.kind;
        setBatchRun(null);
        if (selectedSourceId) void loadInventory(selectedSourceId);
        if (kind === 'summary' && selectedSourceId && selectedFile) {
          await loadSummary(selectedSourceId, selectedFile);
        }
        if (kind === 'extract' && selectedSourceId && selectedFile) {
          await loadEntities(selectedSourceId, selectedFile);
        }
      }
    } catch {
      // 本轮轮询失败，下一轮再取
    }
  }, 2000, !!batchRun);

  // 批量运行期间文件状态随进度持续刷新（每 5s 一次，成本 = 一次 inventory 聚合查询），
  // 已完成的文件 Tag 立刻翻转；结束后再由批量轮询器做一次终态刷新
  useSafePolling(async () => {
    if (!selectedSourceId) return;
    await loadInventory(selectedSourceId, getComponentSignal());
  }, 5000, !!batchRun);

  // ── Tree rendering helpers ────────────────────────────────────

  /** 状态标签：未摘要(灰) / 未抽取(蓝) / 已抽取 N(绿)，每文件最多一枚 */
  const fileStatTag = (stat: FileStat | undefined) => {
    if (!stat) return null;
    if (!stat.has_summary) {
      return <Tag className="dv-file-stat" color="default">未摘要</Tag>;
    }
    if (stat.extracted_count > 0) {
      return <Tag className="dv-file-stat" color="green">已抽取 {stat.extracted_count}</Tag>;
    }
    return <Tag className="dv-file-stat" color="blue">未抽取</Tag>;
  };

  const renderFileTree = (entries: FileEntry[]): Record<string, unknown>[] => {
    return entries.map((entry) => ({
      key: entry.path,
      title: (
        <span className="dv-file-title">
          <span className="dv-file-name" title={entry.name}>{entry.name}</span>
          {entry.type === 'file' && fileStatTag(inventory[entry.path])}
        </span>
      ),
      icon: entry.type === 'dir' ? <FolderOutlined /> : <FileOutlined />,
      isLeaf: entry.type === 'file',
      isDir: entry.type === 'dir',
      entry,
    }));
  };

  const convertSummaryToTree = (nodes: SummaryNode[] | undefined): Record<string, unknown>[] => {
    if (!nodes || !Array.isArray(nodes)) return [];
    return nodes.map((node, idx) => ({
      key: node.node_id || `node-${idx}`,
      title: node.title,
      icon: <FileOutlined />,
      children: node.nodes ? convertSummaryToTree(node.nodes) : undefined,
      isLeaf: !node.nodes || node.nodes.length === 0,
      summary: node.summary,
      text: node.text,
    }));
  };

  const ENTITY_COLORS: Record<string, { bg: string; text: string }> = {
    person: { bg: 'rgba(255, 107, 107, 0.2)', text: '#FF6B6B' },
    organization: { bg: 'rgba(78, 205, 196, 0.2)', text: '#4ECDC4' },
    location: { bg: 'rgba(69, 183, 209, 0.2)', text: '#45B7D1' },
    event: { bg: 'rgba(150, 206, 180, 0.2)', text: '#96CEB4' },
  };

  const getEntityColors = (type: string) => {
    const colors = ENTITY_COLORS[type.toLowerCase()];
    return colors || { bg: 'rgba(149, 165, 166, 0.2)', text: '#95A5A6' };
  };

  // ── Render ─────────────────────────────────────────────────────

  return (
    <div className="document-viewer">
      {/* Header: buttons + search */}
      <div className="dv-header">
        <div className="dv-header-row">
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setAddSourceModalVisible(true)}
          >
            添加源
          </Button>
          {selectedSourceData?.is_deleted ? (
            <Button
              icon={<UndoOutlined />}
              onClick={() => handleRestoreSource(selectedSourceId!)}
              loading={restoringSourceId === selectedSourceId}
            >
              恢复源
            </Button>
          ) : (
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={!selectedSourceId}
              onClick={() => selectedSourceId && handleDeleteSource(selectedSourceId)}
            >
              删除源
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={() => loadSources()}>
            刷新
          </Button>
          <Input.Search
            placeholder="搜索文档源..."
            value={sourceSearchText}
            onChange={(e) => setSourceSearchText(e.target.value)}
            className="dv-search-box"
            allowClear
          />
          <Switch
            checkedChildren="含已删除"
            unCheckedChildren="仅活跃"
            checked={showDeletedSources}
            onChange={setShowDeletedSources}
            style={{ marginLeft: 8 }}
          />
        </div>
      </div>

      {/* Body: 3 panels */}
      <div className="dv-body">
        {/* Left: source list */}
        <div className="dv-source-panel">
          <div className="dv-panel-header">
            <h4>文档源</h4>
          </div>
          <div className="dv-source-list">
            {sourcesLoading ? (
              <div className="dv-loading"><Spin /> 加载中...</div>
            ) : filteredSources.length === 0 ? (
              <div className="dv-empty">{sourceSearchText ? '无匹配源' : '暂无文档源'}</div>
            ) : (
              filteredSources.map((src) => (
                <div
                  key={src.id}
                  className={`dv-source-item${selectedSourceId === src.id ? ' selected' : ''}${src.is_deleted ? ' deleted' : ''}`}
                  onClick={() => handleSourceChange(src.id)}
                >
                  <div className="dv-source-name">
                    {src.is_deleted ? <span style={{ textDecoration: 'line-through', opacity: 0.6 }}>{src.name}</span> : src.name}
                  </div>
                  <span className={`dv-source-type ${src.source_type}`}>{src.source_type}</span>
                  {src.is_deleted && <span className="dv-deleted-badge">已删除</span>}
                  <div className="dv-source-path" title={src.path}>{src.path}</div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Middle: file browser */}
        <div className="dv-file-panel">
          <div className="dv-panel-header">
            <h4>文件浏览</h4>
            {currentPath && (
              <Button size="small" onClick={handlePathUp}>
                ...
              </Button>
            )}
          </div>
          <div className="dv-current-path" title={currentPath || '/'}>
            {currentPath || '/'}
          </div>
          <div className="dv-file-tree">
            {filesLoading ? (
              <div className="dv-loading"><Spin /> 加载中...</div>
            ) : files.length === 0 ? (
              <div className="dv-empty">该目录下无文件</div>
            ) : (
              <Tree
                checkable
                blockNode
                checkedKeys={checkedKeys}
                onCheck={(keys) => {
                  const checked = Array.isArray(keys) ? keys : keys.checked;
                  setCheckedKeys(checked as React.Key[]);
                }}
                treeData={renderFileTree(files)}
                showIcon
                defaultExpandAll
                onSelect={(_keys, info) => {
                  const node = info.node as { isDir?: boolean; entry?: FileEntry };
                  if (node.isDir && node.entry) {
                    handleDirClick(node.entry);
                  } else if (node.entry) {
                    handleFileClick(node.entry);
                  }
                }}
              />
            )}
          </div>
        </div>

        {/* Right: content panel */}
        <div className="dv-content-panel">
          {!selectedSourceId ? (
            <div className="dv-empty-state">请先选择文档源</div>
          ) : (
            <div className="dv-summary-view">
              <div className="dv-file-info">
                <span className="dv-selected-file" title={selectedFile || undefined}>
                  {selectedFile || `未选择文件（当前目录 ${currentPath && currentPath !== '.' ? currentPath : '/'}，可勾选左侧文件批量执行）`}
                </span>
                <div className="dv-actions">
                  <Select
                    value={extractDomain}
                    onChange={(value: string) => {
                      setExtractDomain(value);
                      localStorage.setItem(EXTRACT_DOMAIN_KEY, value);
                    }}
                    style={{ width: 160 }}
                    placeholder="本体域"
                    options={(ontologyDomains.length > 0
                      ? ontologyDomains
                      : [{ name: extractDomain, description: '', object_type_count: 0, link_type_count: 0 }]
                    ).map(d => ({
                      value: d.name,
                      label: labelDomain(d.name),
                      title: `${d.name}：${d.description}（${d.object_type_count} 类型 / ${d.link_type_count} 谓词）`,
                    }))}
                  />
                  <Button
                    type="primary"
                    icon={<NodeIndexOutlined />}
                    onClick={() => submitAction('summary')}
                    loading={summarizing || batchSubmitting}
                    disabled={!selectedSourceId}
                    title="勾选了文件/目录时按勾选批量执行；未勾选时针对当前已选文件生成概要"
                  >
                    {summarizing ? '生成中...' : '生成概要'}
                  </Button>
                  <Button
                    icon={<TeamOutlined />}
                    onClick={() => submitAction('extract')}
                    loading={extracting || batchSubmitting}
                    disabled={!selectedSourceId}
                    title="勾选了文件/目录时按勾选批量抽取（缺摘要的文件记失败继续）；未勾选时针对当前已选文件抽取"
                  >
                    {extracting ? '提取中...' : '提取实体关系'}
                  </Button>
                </div>
              </div>

              {/* Summary content */}
              <div className="dv-summary-content">
                {summaryLoading ? (
                  <div className="dv-loading"><Spin /> 加载概要...</div>
                ) : summary ? (
                  <>
                    {summary.doc_description != null && (
                      <div className="dv-doc-description">
                        <strong>文档描述：</strong>
                        <p>{String(summary.doc_description)}</p>
                      </div>
                    )}

                    {summary.structure != null && (summary.structure as unknown as SummaryNode[]).length > 0 && (
                      <div className="dv-summary-tree">
                        <h5>目录结构</h5>
                        <Tree
                          treeData={convertSummaryToTree(summary.structure as unknown as SummaryNode[])}
                          showIcon
                          defaultExpandAll
                          titleRender={(node: { title?: string; summary?: string }) => (
                            <span>
                              {node.title}
                              {node.summary && (
                                <span className="dv-summary-hint"> — {node.summary}</span>
                              )}
                            </span>
                          )}
                        />
                      </div>
                    )}

                    {summarySheets.length > 0 && (
                      <div className="dv-sheets-section">
                        <h5>表格 ({summarySheets.length} 个工作表)</h5>
                        <div className="tables-grid">
                          {summarySheets.map(sheet => (
                            <div
                              key={sheet.key}
                              className={`table-card ${activeSheet?.key === sheet.key ? 'selected' : ''}`}
                              onClick={() => setSelectedSheet(sheet.key)}
                            >
                              <div className="table-header">
                                <span className="table-name">{sheet.title}</span>
                                <span className={`table-role ${sheet.entity_count > 0
                                  ? 'table-role-entity' : 'table-role-none'}`}>
                                  {sheet.entity_count > 0 ? `${sheet.entity_count} 个实体列` : '无实体列'}
                                </span>
                              </div>
                              {sheet.summary && <p className="table-description">{sheet.summary}</p>}
                              <div className="table-meta">
                                <span>列: {sheet.col_count ?? sheet.columns.length}</span>
                                {sheet.row_count != null && <span>行: {sheet.row_count}</span>}
                                {sheet.skipped_reason && <span>标注跳过: {sheet.skipped_reason}</span>}
                              </div>
                              {sheet.rels.length > 0 && (
                                <div className="table-relations">
                                  <div className="relation-line">
                                    <span className="relation-label">列间关系:</span>
                                    {sheet.rels.map((rel, i) => (
                                      <span key={i} className="relation-tag">
                                        {rel.s} —{rel.p}→ {rel.o}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {activeSheet && (
                      <div className="columns-section">
                        <h3>字段详情: {activeSheet.title}</h3>
                        <table className="columns-table">
                          <thead>
                            <tr>
                              <th>列名</th>
                              <th>归一类型</th>
                              <th>角色</th>
                              <th>主列</th>
                              <th>业务解释</th>
                            </tr>
                          </thead>
                          <tbody>
                            {activeSheet.columns.map(col => (
                              <tr key={col.n}>
                                <td>{col.n}</td>
                                <td>{col.t ? labelType(col.t) : '-'}</td>
                                <td>
                                  <span className={`table-role ${COLUMN_ROLE_CLASSES[col.r || 'none']
                                    || 'table-role-none'}`}>
                                    {COLUMN_ROLE_LABELS[col.r || ''] || '未标注'}
                                  </span>
                                </td>
                                <td>{col.primary ? <span className="primary-tag">主列</span> : '-'}</td>
                                <td>{col.d || '-'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="dv-empty-state">
                    {selectedFile ? '概要未生成，请点击"生成概要"' : '点选左侧文件查看概要，或勾选文件/目录后点批量按钮'}
                  </div>
                )}
              </div>

              {/* Entities */}
              {selectedFile && entities.length > 0 && (
                <div className="dv-entities-section">
                  <h5>识别的实体 ({entities.length})</h5>
                  <div className="dv-entities-list">
                    {entities.map((entity, idx) => (
                      <Tag
                        key={idx}
                        color={getEntityColors(entity.type).text}
                        style={{
                          backgroundColor: getEntityColors(entity.type).bg,
                          border: `1px solid ${getEntityColors(entity.type).text}`,
                          color: getEntityColors(entity.type).text,
                          marginBottom: 4,
                        }}
                      >
                        {entity.name} ({labelType(entity.type)})
                      </Tag>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Add Source Modal */}
      <Modal
        title="添加文档源"
        open={addSourceModalVisible}
        onOk={handleAddSource}
        onCancel={() => {
          setAddSourceModalVisible(false);
          setNewSourceName('');
          setNewSourcePath('');
        }}
        confirmLoading={addingSource}
        okText="添加"
        cancelText="取消"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>名称</div>
            <Input
              placeholder="例如: 项目文档"
              value={newSourceName}
              onChange={(e) => setNewSourceName(e.target.value)}
            />
          </div>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>类型</div>
            <Select
              value={newSourceType}
              onChange={(v) => setNewSourceType(v)}
              style={{ width: '100%' }}
              options={[
                { value: 'local', label: '本地路径' },
                { value: 's3', label: 'S3 存储' },
              ]}
            />
          </div>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>路径</div>
            <Input
              placeholder={newSourceType === 'local' ? 'D:/docs' : 's3://bucket/path'}
              value={newSourcePath}
              onChange={(e) => setNewSourcePath(e.target.value)}
            />
          </div>
        </div>
      </Modal>

      {/* Batch 进度 / 结果 Modal */}
      <Modal
        title={batchKind === 'summary' ? '批量生成摘要' : '批量提取实体关系'}
        open={batchModalOpen}
        onCancel={() => setBatchModalOpen(false)}
        footer={[
          <Button key="stop" danger disabled={!batchRun} onClick={handleStopBatch}>停止</Button>,
          <Button key="close" type={batchFinished ? 'primary' : 'default'} onClick={() => setBatchModalOpen(false)}>关闭</Button>,
        ]}
      >
        {batchFinished ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {batchStoppedFlag && <div style={{ color: '#faad14' }}>任务已停止，已完成部分保留。</div>}
            {batchError && <div style={{ color: '#ff4d4f' }}>批量任务失败：{batchError}</div>}
            {batchFinished.total > 0 && (
              <>
                <div>
                  <span>共 {batchFinished.total} 个文件：</span>
                  <Tag color="green">成功 {batchFinished.succeeded}</Tag>
                  <Tag color="blue">跳过 {batchFinished.skipped}</Tag>
                  <Tag color={batchFinished.failed > 0 ? 'red' : 'default'}>失败 {batchFinished.failed}</Tag>
                </div>
                {batchKind === 'extract' && (
                  <div>
                    抽取总计：<strong>{batchFinished.entity_count ?? 0}</strong> 个实体、
                    <strong>{batchFinished.relationship_count ?? 0}</strong> 条关系；
                    Wiki：主题页 {batchFinished.wiki_pages?.topic_pages ?? 0}、
                    实体页 {batchFinished.wiki_pages?.entity_pages ?? 0}
                  </div>
                )}
              </>
            )}
            {batchFinished.failures.length > 0 && (
              <>
                <h5 style={{ marginBottom: 4 }}>失败清单</h5>
                <Table
                  size="small"
                  rowKey="key"
                  dataSource={batchFinished.failures.map((f, i) => ({ key: String(i), ...f }))}
                  columns={[
                    { title: '文件', dataIndex: 'file', ellipsis: true },
                    { title: '原因', dataIndex: 'reason', ellipsis: true },
                  ]}
                  pagination={{ pageSize: 5, size: 'small' }}
                />
              </>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Progress percent={batchPercent} status="active" />
            <div style={{ color: '#888' }}>
              任务在后台运行（文件间并发）。可以关闭弹窗稍后回来查看，也可以先做其他操作。
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default DocumentViewer;
