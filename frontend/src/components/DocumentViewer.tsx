import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { message, Tree, Spin, Modal, Input, Select, Button, Tag, Switch } from 'antd';
import {
  FolderOutlined,
  FileOutlined,
  PlusOutlined,
  DeleteOutlined,
  UndoOutlined,
  NodeIndexOutlined,
  TeamOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { logger } from '../services/logger';
import { API_CONFIG } from '../config/apiConfig';

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

interface Entity {
  name: string;
  type: string;
  confidence: number;
  count?: number;
}

interface SummaryNode {
  title: string;
  node_id?: string;
  summary?: string;
  text?: string;
  start_index?: number;
  end_index?: number;
  nodes?: SummaryNode[];
}

interface SummaryData {
  doc_name?: string;
  doc_description?: string;
  structure?: SummaryNode[];
}

const DocumentViewer: React.FC = () => {
  // Source state
  const [sources, setSources] = useState<Source[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [addSourceModalVisible, setAddSourceModalVisible] = useState(false);
  const [newSourceName, setNewSourceName] = useState('');
  const [newSourcePath, setNewSourcePath] = useState('');
  const [newSourceType, setNewSourceType] = useState<'local' | 's3'>('local');
  const [addingSource, setAddingSource] = useState(false);
  const [sourceSearchText, setSourceSearchText] = useState('');
  const [showDeletedSources, setShowDeletedSources] = useState(false);
  const [restoringSourceId, setRestoringSourceId] = useState<string | null>(null);

  // File browser state
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [currentPath, setCurrentPath] = useState('');
  const [filesLoading, setFilesLoading] = useState(false);

  // Selected file & summary state
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Task polling state
  const [taskId, setTaskId] = useState<string | null>(null);

  // Entity state
  const [entities, setEntities] = useState<Entity[]>([]);
  const [extracting, setExtracting] = useState(false);

  const filteredSources = sources.filter(s =>
    s.name.toLowerCase().includes(sourceSearchText.toLowerCase()) ||
    s.path.toLowerCase().includes(sourceSearchText.toLowerCase())
  );
  const selectedSourceData = sources.find(s => s.id === selectedSourceId) || null;

  // ── Fetch sources ──────────────────────────────────────────────

  const fetchSources = useCallback(async () => {
    setSourcesLoading(true);
    try {
      const res = await axios.get(API_CONFIG.endpoints.source.list, {
        params: { include_deleted: showDeletedSources }
      });
      setSources(res.data.sources || []);
    } catch (err) {
      logger.error('DocumentViewer', '获取文档源列表失败', err);
    } finally {
      setSourcesLoading(false);
    }
  }, [showDeletedSources]);

  useEffect(() => {
    fetchSources();
  }, [fetchSources]);

  // ── Source CRUD ────────────────────────────────────────────────

  const handleAddSource = async () => {
    if (!newSourceName.trim() || !newSourcePath.trim()) return;
    setAddingSource(true);
    try {
      await axios.post(API_CONFIG.endpoints.source.create, {
        name: newSourceName.trim(),
        path: newSourcePath.trim(),
        source_type: newSourceType,
      });
      message.success('文档源添加成功');
      setAddSourceModalVisible(false);
      setNewSourceName('');
      setNewSourcePath('');
      await fetchSources();
    } catch (err: any) {
      message.error(`添加失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setAddingSource(false);
    }
  };

  const handleDeleteSource = async (sourceId: string) => {
    try {
      await axios.delete(API_CONFIG.endpoints.source.delete(sourceId));
      message.success('文档源已删除');
      if (selectedSourceId === sourceId) {
        setSelectedSourceId(null);
        setFiles([]);
        setSelectedFile(null);
        setSummary(null);
        setEntities([]);
      }
      await fetchSources();
    } catch (err: any) {
      message.error(`删除失败: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleRestoreSource = async (sourceId: string) => {
    setRestoringSourceId(sourceId);
    try {
      await axios.post(API_CONFIG.endpoints.source.restore(sourceId));
      message.success('文档源已恢复');
      await fetchSources();
    } catch (err: any) {
      message.error(`恢复失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setRestoringSourceId(null);
    }
  };

  // ── Source selection / file browsing ──────────────────────────

  const handleSourceChange = async (sourceId: string | null) => {
    setSelectedSourceId(sourceId);
    setSelectedFile(null);
    setSummary(null);
    setEntities([]);
    setCurrentPath('');

    if (!sourceId) {
      setFiles([]);
      return;
    }

    await browseFiles(sourceId, '');
  };

  const browseFiles = async (sourceId: string, prefix: string) => {
    setFilesLoading(true);
    try {
      const res = await axios.get(API_CONFIG.endpoints.source.browse(sourceId), {
        params: { prefix },
      });
      setFiles(res.data.entries || []);
      setCurrentPath(res.data.current_path || '');
    } catch (err: any) {
      message.error(`浏览失败: ${err.response?.data?.detail || err.message}`);
      setFiles([]);
    } finally {
      setFilesLoading(false);
    }
  };

  const handleDirClick = (entry: FileEntry) => {
    if (!selectedSourceId) return;
    browseFiles(selectedSourceId, entry.path);
  };

  const handleFileClick = async (entry: FileEntry) => {
    if (!selectedSourceId) return;
    setSelectedFile(entry.path);
    setSummary(null);
    setEntities([]);
    setTaskId(null);
    setSummarizing(false);

    await Promise.all([
      loadSummary(selectedSourceId, entry.path),
      loadEntities(selectedSourceId, entry.path),
    ]);
  };

  const handlePathUp = () => {
    if (!selectedSourceId || !currentPath) return;
    const parts = currentPath.split('/');
    parts.pop();
    const parent = parts.join('/');
    browseFiles(selectedSourceId, parent);
  };

  // ── Summary ────────────────────────────────────────────────────

  const loadSummary = async (sourceId: string, file: string) => {
    setSummaryLoading(true);
    try {
      const res = await axios.get(API_CONFIG.endpoints.source.summary(sourceId), {
        params: { file },
      });
      const data = res.data.summary;
      setSummary(data);
    } catch {
      setSummary(null);
    } finally {
      setSummaryLoading(false);
    }
  };

  const loadEntities = async (sourceId: string, file: string) => {
    try {
      const res = await axios.get(API_CONFIG.endpoints.source.entities(sourceId), {
        params: { file },
      });
      const data = res.data.entities || [];
      if (data.length > 0) {
        setEntities(data);
      }
    } catch {
      // Entities don't exist yet — that's fine
    }
  };

  const handleBuildSummary = async () => {
    if (!selectedSourceId || !selectedFile) return;
    setSummarizing(true);
    try {
      const res = await axios.post(
        API_CONFIG.endpoints.source.summarize(selectedSourceId),
        { file: selectedFile }
      );
      setTaskId(res.data.task_id);
    } catch (err: any) {
      message.error(`提交概要生成任务失败: ${err.response?.data?.detail || err.message}`);
      setSummarizing(false);
    }
  };

  // Poll task status for document summary generation
  useEffect(() => {
    if (!taskId) return;

    const interval = setInterval(async () => {
      try {
        const response = await axios.get(API_CONFIG.endpoints.task.get(taskId));
        const status = response.data.status;

        if (status === 'completed') {
          clearInterval(interval);
          setTaskId(null);
          setSummarizing(false);
          if (selectedSourceId && selectedFile) {
            await loadSummary(selectedSourceId, selectedFile);
          }
          message.success('概要生成成功');
        } else if (status === 'failed') {
          clearInterval(interval);
          setTaskId(null);
          setSummarizing(false);
          message.error(`概要生成失败: ${response.data.error || '未知错误'}`);
        }
      } catch (error) {
        clearInterval(interval);
        setTaskId(null);
        setSummarizing(false);
        message.error('获取任务状态失败');
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [taskId, selectedSourceId, selectedFile]);

  const handleExtract = async () => {
    if (!selectedSourceId || !selectedFile) return;
    setExtracting(true);
    try {
      const res = await axios.post(
        API_CONFIG.endpoints.source.extract(selectedSourceId),
        { file: selectedFile }
      );
      setEntities(res.data.entities || []);
      message.success(`实体提取完成: ${res.data.entity_count} 个实体, ${res.data.relationship_count} 个关系`);
    } catch (err: any) {
      message.error(`提取失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setExtracting(false);
    }
  };

  // ── Tree rendering helpers ────────────────────────────────────

  const renderFileTree = (entries: FileEntry[]): any[] => {
    return entries.map((entry) => ({
      key: entry.path,
      title: entry.name,
      icon: entry.type === 'dir' ? <FolderOutlined /> : <FileOutlined />,
      isLeaf: entry.type === 'file',
      isDir: entry.type === 'dir',
      entry,
    }));
  };

  const convertSummaryToTree = (nodes: SummaryNode[] | undefined): any[] => {
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
          <Button icon={<ReloadOutlined />} onClick={fetchSources}>
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
                treeData={renderFileTree(files)}
                showIcon
                defaultExpandAll
                onSelect={(_keys, info) => {
                  const node = info.node as any;
                  if (node.isDir) {
                    handleDirClick(node.entry);
                  } else {
                    handleFileClick(node.entry);
                  }
                }}
              />
            )}
          </div>
        </div>

        {/* Right: content panel */}
        <div className="dv-content-panel">
          {!selectedFile ? (
            <div className="dv-empty-state">请选择一个文件</div>
          ) : (
            <div className="dv-summary-view">
              <div className="dv-file-info">
                <span className="dv-selected-file">{selectedFile}</span>
                <div className="dv-actions">
                  <Button
                    type="primary"
                    icon={<NodeIndexOutlined />}
                    onClick={handleBuildSummary}
                    loading={summarizing}
                    disabled={!selectedSourceId}
                  >
                    {summarizing ? '生成中...' : '生成概要'}
                  </Button>
                  <Button
                    icon={<TeamOutlined />}
                    onClick={handleExtract}
                    loading={extracting}
                    disabled={!selectedSourceId || !summary}
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
                    {summary.doc_description && (
                      <div className="dv-doc-description">
                        <strong>文档描述：</strong>
                        <p>{summary.doc_description}</p>
                      </div>
                    )}

                    {summary.structure && summary.structure.length > 0 && (
                      <div className="dv-summary-tree">
                        <h5>目录结构</h5>
                        <Tree
                          treeData={convertSummaryToTree(summary.structure)}
                          showIcon
                          defaultExpandAll
                          titleRender={(node: any) => (
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
                  </>
                ) : (
                  <div className="dv-empty-state">概要未生成，请点击"生成概要"</div>
                )}
              </div>

              {/* Entities */}
              {entities.length > 0 && (
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
                        {entity.name} ({entity.type})
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
    </div>
  );
};

export default DocumentViewer;
