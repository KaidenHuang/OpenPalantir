import { useState, useEffect } from 'react';
import axios from 'axios';
import { Button, Input, Switch } from 'antd';
import { ReloadOutlined, UndoOutlined } from '@ant-design/icons';
import { API_CONFIG } from '../config/apiConfig';
import { logger } from '../services/logger';
import ERDiagram from './ERDiagram';

const DB_STATUS = { EXTRACTED: 'extracted', DELETED: 'deleted' } as const;

interface DatabaseConnection {
  id: string;
  name: string;
  type: string;
  host: string;
  port: number;
  database: string;
  username: string;
  service_name?: string;
  description?: string;
  created_at?: string;
  updated_at?: string;
  is_deleted?: boolean;
  deleted_at?: string | null;
}

interface TableInfo {
  id: string;
  connection_id: string;
  table_name: string;
  table_type?: string;
  engine?: string;
  row_count?: number;
  business_description?: string;
  entity_type?: string;
}

interface ColumnInfo {
  id: string;
  connection_id: string;
  table_name: string;
  column_name: string;
  data_type: string;
  is_nullable?: string;
  column_type?: string;
  column_key?: string;
  business_description?: string;
  semantic_type?: string;
}

interface ForeignKeyInfo {
  id: string;
  connection_id: string;
  table_name: string;
  column_name: string;
  referenced_table_name: string;
  referenced_column_name: string;
  constraint_name?: string;
}

interface SchemaResult {
  tables: TableInfo[];
  columns: ColumnInfo[];
  foreign_keys: ForeignKeyInfo[];
  inferred_relationships?: any[];
}

interface DatabaseItem {
  name: string;
  status: string | null;
}

type DbType = 'mysql' | 'postgresql' | 'sqlite' | 'oracle' | 'mssql';

const DB_TYPES: { value: DbType; label: string }[] = [
  { value: 'mysql', label: 'MySQL' },
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'sqlite', label: 'SQLite' },
  { value: 'oracle', label: 'Oracle' },
  { value: 'mssql', label: 'SQL Server' },
];

function DatabaseManagement() {
  const [connections, setConnections] = useState<DatabaseConnection[]>([]);
  const [selectedConnection, setSelectedConnection] = useState<DatabaseConnection | null>(null);
  const [schemaResult, setSchemaResult] = useState<SchemaResult | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const isAnalyzing = taskId !== null;
  const [_taskStatus, setTaskStatus] = useState<string>('');
  const [viewMode, setViewMode] = useState<'card' | 'er'>('card');
  const [sourceSearchText, setSourceSearchText] = useState('');
  const [showDeletedConnections, setShowDeletedConnections] = useState(false);
  const [restoringConnectionId, setRestoringConnectionId] = useState<string | null>(null);
  const [dbSummary, setDbSummary] = useState<any>(null);

  // Middle panel: database list
  const [databases, setDatabases] = useState<DatabaseItem[]>([]);
  const [selectedDatabase, setSelectedDatabase] = useState<string | null>(null);

  // Test state
  const [testingCreate, setTestingCreate] = useState(false);
  const [testingEdit, setTestingEdit] = useState(false);
  const [showPwdCreate, setShowPwdCreate] = useState(false);
  const [showPwdEdit, setShowPwdEdit] = useState(false);

  const [newConnection, setNewConnection] = useState({
    name: '',
    type: 'mysql' as DbType,
    host: '',
    port: 3306,
    database: '',
    username: '',
    password: '',
    service_name: '',
    description: '',
  });

  useEffect(() => {
    loadConnections();
  }, [showDeletedConnections]);

  // When connection changes, fetch all databases from server and load schema
  useEffect(() => {
    if (!selectedConnection) {
      setDatabases([]);
      setSelectedDatabase(null);
      setSchemaResult(null);
      return;
    }

    if (selectedConnection.database) {
      setSelectedDatabase(selectedConnection.database);
    }
    Promise.all([
      fetchDatabases(selectedConnection.id),
      loadSchema(selectedConnection.id, selectedConnection.database),
    ]);
  }, [selectedConnection]);

  useEffect(() => {
    if (!selectedConnection) return;
    const savedTaskId = localStorage.getItem(`analyze_task_${selectedConnection.id}`);
    if (savedTaskId) {
      setTaskId(savedTaskId);
      setTaskStatus('running');
    }
  }, [selectedConnection]);

  useEffect(() => {
    if (taskId) {
      const interval = setInterval(async () => {
        try {
          const response = await axios.get(API_CONFIG.endpoints.task.get(taskId));
          const status = response.data.status;
          setTaskStatus(status);
          if (status === 'completed' || status === 'failed') {
            clearInterval(interval);
            if (status === 'completed') {
              loadSchema(selectedConnection!.id, selectedConnection!.database);
            }
            if (selectedConnection) {
              localStorage.removeItem(`analyze_task_${selectedConnection.id}`);
            }
            setTaskId(null);
          }
        } catch (error) {
          logger.error('DatabaseManagement', '获取任务状态失败', error);
        }
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [taskId, selectedConnection]);

  const loadConnections = async () => {
    try {
      const response = await axios.get(API_CONFIG.endpoints.database.connections, {
        params: { include_deleted: showDeletedConnections }
      });
      setConnections(response.data);
    } catch (error) {
      logger.error('DatabaseManagement', '加载连接列表失败', error);
    }
  };

  const fetchDatabases = async (connectionId: string) => {
    try {
      const response = await axios.get(
        `${API_CONFIG.endpoints.database.connections}/${connectionId}/databases`
      );
      setDatabases(response.data.databases || []);
    } catch (error) {
      logger.error('DatabaseManagement', '获取数据库列表失败', error);
      setDatabases([]);
    }
  };

  const handleSelectDatabase = async (dbName: string) => {
    if (!selectedConnection) return;
    setSelectedDatabase(dbName);
    try {
      await axios.put(
        API_CONFIG.endpoints.database.connection(selectedConnection.id),
        { database: dbName }
      );
      const updated = { ...selectedConnection, database: dbName };
      setSelectedConnection(updated);
    } catch (error) {
      logger.error('DatabaseManagement', '设置数据库失败', error);
    }
  };

  const loadSchema = async (connectionId: string, dbName?: string) => {
    try {
      setIsLoading(true);
      const response = await axios.get(API_CONFIG.endpoints.database.analysisResult(connectionId));
      const data = response.data;
      const targetDb = dbName || selectedDatabase;
      if (data.analyzed_databases && !data.analyzed_databases.includes(targetDb)) {
        setSchemaResult(null);
      } else {
        setSchemaResult(data);
      }
      setSelectedTable(null);
      loadDbSummary(connectionId);
    } catch (error) {
      logger.error('DatabaseManagement', '加载Schema失败', error);
      setSchemaResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  const loadDbSummary = async (connectionId: string) => {
    try {
      const res = await axios.get(API_CONFIG.endpoints.database.summary(connectionId));
      setDbSummary(res.data.summary);
    } catch {
      setDbSummary(null);
    }
  };

  const handleSelectConnection = async (connection: DatabaseConnection) => {
    setSelectedConnection(connection);
    setSelectedTable(null);
  };

  const handleCreateConnection = async () => {
    try {
      const { database: _db, ...payload } = newConnection;
      await axios.post(API_CONFIG.endpoints.database.connections, payload);
      await loadConnections();
      setShowCreateModal(false);
      setNewConnection({
        name: '',
        type: 'mysql',
        host: '',
        port: 3306,
        database: '',
        username: '',
        password: '',
        service_name: '',
        description: '',
      });
    } catch (error) {
      logger.error('DatabaseManagement', '创建连接失败', error);
    }
  };

  const handleUpdateConnection = async () => {
    if (!selectedConnection) return;
    try {
      await axios.put(
        API_CONFIG.endpoints.database.connection(selectedConnection.id),
        newConnection
      );
      await loadConnections();
      setShowEditModal(false);
      const updated = { ...selectedConnection, ...newConnection };
      setSelectedConnection(updated);
    } catch (error) {
      logger.error('DatabaseManagement', '更新连接失败', error);
    }
  };

  const handleDeleteConnection = async (connectionId: string) => {
    if (!confirm('确定要删除这个连接吗？删除后可恢复。')) return;
    try {
      await axios.delete(API_CONFIG.endpoints.database.connection(connectionId));
      await loadConnections();
      if (selectedConnection?.id === connectionId) {
        setSelectedConnection(null);
        setSchemaResult(null);
        setDatabases([]);
      }
    } catch (error) {
      logger.error('DatabaseManagement', '删除连接失败', error);
    }
  };

  const handleRestoreConnection = async (connectionId: string) => {
    setRestoringConnectionId(connectionId);
    try {
      await axios.post(API_CONFIG.endpoints.database.restore(connectionId));
      await loadConnections();
    } catch (error) {
      logger.error('DatabaseManagement', '恢复连接失败', error);
    } finally {
      setRestoringConnectionId(null);
    }
  };

  const handleTestCreateConfig = async () => {
    setTestingCreate(true);
    try {
      const response = await axios.post(
        API_CONFIG.endpoints.database.testConnectionConfig,
        newConnection
      );
      alert(response.data.success ? '连接测试成功！' : '连接测试失败！');
    } catch (error) {
      logger.error('DatabaseManagement', '测试连接失败', error);
      alert('连接测试失败！');
    } finally {
      setTestingCreate(false);
    }
  };

  const handleTestEditConfig = async () => {
    setTestingEdit(true);
    try {
      const response = await axios.post(
        API_CONFIG.endpoints.database.testConnectionConfig,
        newConnection
      );
      alert(response.data.success ? '连接测试成功！' : '连接测试失败！');
    } catch (error) {
      logger.error('DatabaseManagement', '测试连接失败', error);
      alert('连接测试失败！');
    } finally {
      setTestingEdit(false);
    }
  };

  const handleAnalyze = async () => {
    if (!selectedConnection) return;
    try {
      const response = await axios.post(
        API_CONFIG.endpoints.database.analyze(selectedConnection.id),
        { database: selectedDatabase }
      );
      const newTaskId = response.data.task_id;
      localStorage.setItem(`analyze_task_${selectedConnection.id}`, newTaskId);
      setTaskId(newTaskId);
      setTaskStatus('running');
    } catch (error) {
      logger.error('DatabaseManagement', '开始分析失败', error);
    }
  };

  const handleImport = async () => {
    if (!selectedConnection) return;
    try {
      const response = await axios.post(
        API_CONFIG.endpoints.database.import(selectedConnection.id)
      );
      alert(`导入任务已创建，任务ID: ${response.data.task_id}`);
    } catch (error) {
      logger.error('DatabaseManagement', '开始导入失败', error);
    }
  };

  const handleOpenEditModal = () => {
    if (selectedConnection) {
      setNewConnection({
        name: selectedConnection.name,
        type: selectedConnection.type as DbType,
        host: selectedConnection.host,
        port: selectedConnection.port,
        database: selectedConnection.database,
        username: selectedConnection.username,
        password: '',
        service_name: selectedConnection.service_name || '',
        description: selectedConnection.description || '',
      });
      setShowEditModal(true);
    }
  };

  const getTableColumns = (tableName: string) => {
    return schemaResult?.columns.filter(col => col.table_name === tableName) || [];
  };

  const filteredConnections = connections.filter(c =>
    c.name.toLowerCase().includes(sourceSearchText.toLowerCase())
  );

  return (
    <div className="database-management">
      {/* Header: buttons + search */}
      <div className="dv-header-row">
        <Button type="primary" onClick={() => setShowCreateModal(true)}>
          添加数据源
        </Button>
        <Button onClick={handleOpenEditModal} disabled={!selectedConnection}>
          编辑数据源
        </Button>
        {selectedConnection?.is_deleted ? (
          <Button
            icon={<UndoOutlined />}
            disabled={!selectedConnection}
            onClick={() => handleRestoreConnection(selectedConnection!.id)}
            loading={restoringConnectionId === selectedConnection?.id}
          >
            恢复数据源
          </Button>
        ) : (
          <Button danger disabled={!selectedConnection} onClick={() => handleDeleteConnection(selectedConnection!.id)}>
            删除数据源
          </Button>
        )}
        <Input.Search
          placeholder="搜索数据源..."
          value={sourceSearchText}
          onChange={(e) => setSourceSearchText(e.target.value)}
          style={{ width: 240 }}
          allowClear
        />
        <Switch
          checkedChildren="含已删除"
          unCheckedChildren="仅活跃"
          checked={showDeletedConnections}
          onChange={setShowDeletedConnections}
          style={{ marginLeft: 8 }}
        />
      </div>

      {/* Body: 3 panels */}
      <div className="dv-body">
        {/* Left: source list */}
        <div className="db-source-panel">
          <div className="dv-panel-header">
            <h4>数据源</h4>
          </div>
          <div className="db-source-list">
            {filteredConnections.length === 0 ? (
              <div className="dv-empty">{sourceSearchText ? '无匹配源' : '暂无数据源'}</div>
            ) : (
              filteredConnections.map((conn) => (
                <div
                  key={conn.id}
                  className={`db-source-item${selectedConnection?.id === conn.id ? ' selected' : ''}${conn.is_deleted ? ' deleted' : ''}`}
                  onClick={() => handleSelectConnection(conn)}
                >
                  <div className="db-source-name">
                    {conn.is_deleted ? <span style={{ textDecoration: 'line-through', opacity: 0.6 }}>{conn.name}</span> : conn.name}
                  </div>
                  <div className="db-source-type">{conn.type}</div>
                  {conn.is_deleted && <div className="db-deleted-badge">已删除</div>}
                  <div className="db-source-meta">{conn.host || conn.database || '-'}</div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Middle: database list */}
        <div className="db-middle-panel">
          <div className="dv-panel-header">
            <h4>数据库</h4>
          </div>
          <div className="db-list">
            {!selectedConnection ? (
              <div className="dv-empty">请选择数据源</div>
            ) : databases.length > 0 ? (
              databases.map((db) => (
                <div
                  key={db.name}
                  className={`db-item${selectedDatabase === db.name ? ' selected' : ''}`}
                  onClick={() => handleSelectDatabase(db.name)}
                >
                  <div className="db-item-name">{db.name}</div>
                  {db.status === DB_STATUS.EXTRACTED && (
                    <div className="db-item-status extracted">已提取</div>
                  )}
                  {db.status === DB_STATUS.DELETED && (
                    <div className="db-item-status deleted">已删除</div>
                  )}
                </div>
              ))
            ) : (
              <div className="dv-empty">暂无数据库</div>
            )}
          </div>
        </div>

        {/* Right: table info */}
        <div className="db-table-panel">
          {!selectedConnection ? (
            <div className="empty-state">请从左侧选择数据源</div>
          ) : (
            <>
              <div className="header-actions">
                <button onClick={handleAnalyze} disabled={isAnalyzing || !selectedDatabase}>
                  {isAnalyzing ? '分析中...' : '分析Schema'}
                </button>
                <button onClick={handleImport} disabled={!schemaResult}>
                  导入图谱
                </button>
                <Button icon={<ReloadOutlined />} onClick={() => loadSchema(selectedConnection.id, selectedConnection.database)}>
                  刷新
                </Button>
                {schemaResult && (
                  <div className="view-mode-switch" style={{ marginLeft: 'auto', marginBottom: 0 }}>
                    <button
                      className={`view-btn ${viewMode === 'card' ? 'active' : ''}`}
                      onClick={() => setViewMode('card')}
                    >
                      卡片视图
                    </button>
                    <button
                      className={`view-btn ${viewMode === 'er' ? 'active' : ''}`}
                      onClick={() => setViewMode('er')}
                    >
                      ER图视图
                    </button>
                  </div>
                )}
              </div>

              {isLoading ? (
                <div className="loading">加载中...</div>
              ) : schemaResult ? (
                <div className="schema-content">
                  {dbSummary && (
                    <div className="db-summary-card">
                      {dbSummary.db_description && (
                        <div className="summary-item">
                          <span className="summary-label">概要</span>
                          <span className="summary-value">{dbSummary.db_description}</span>
                        </div>
                      )}
                      {dbSummary.business_domain && (
                        <div className="summary-item">
                          <span className="summary-label">业务领域</span>
                          <span className="summary-value">{dbSummary.business_domain}</span>
                        </div>
                      )}
                      {dbSummary.key_entities && (
                        <div className="summary-item">
                          <span className="summary-label">关键实体</span>
                          <span className="summary-value">{dbSummary.key_entities}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {viewMode === 'card' && (
                    <>
                      <div className="tables-section">
                        <h3>表结构 ({schemaResult.tables.length} 个表)</h3>
                        <div className="tables-grid">
                          {schemaResult.tables.map(table => {
                            const colCount = schemaResult.columns.filter(c => c.table_name === table.table_name).length;
                            const fkOut = schemaResult.foreign_keys.filter(fk => fk.table_name === table.table_name);
                            const fkIn = schemaResult.foreign_keys.filter(fk => fk.referenced_table_name === table.table_name);
                            const rels = (schemaResult.inferred_relationships || []).filter(
                              (r: any) => r.source_table === table.table_name || r.target_table === table.table_name
                            );
                            return (
                              <div
                                key={table.id}
                                className={`table-card ${selectedTable === table.table_name ? 'selected' : ''}`}
                                onClick={() => setSelectedTable(table.table_name)}
                              >
                                <div className="table-header">
                                  <span className="table-name">{table.table_name}</span>
                                  {table.entity_type && (
                                    <span className="entity-type">{table.entity_type}</span>
                                  )}
                                </div>
                                {table.business_description && (
                                  <p className="table-description">{table.business_description}</p>
                                )}
                                <div className="table-meta">
                                  <span>列: {colCount}</span>
                                  {table.row_count != null && <span>行: {table.row_count}</span>}
                                  {table.engine && <span>{table.engine}</span>}
                                </div>
                                {(fkOut.length > 0 || fkIn.length > 0 || rels.length > 0) && (
                                  <div className="table-relations">
                                    {fkOut.length > 0 && (
                                      <div className="relation-line">
                                        <span className="relation-label">关联:</span>
                                        {fkOut.map(fk => (
                                          <span key={fk.id} className="relation-tag" title={`${fk.column_name} → ${fk.referenced_table_name}.${fk.referenced_column_name}`}>
                                            → {fk.referenced_table_name}
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                    {fkIn.length > 0 && (
                                      <div className="relation-line">
                                        <span className="relation-label">被关联:</span>
                                        {fkIn.map(fk => (
                                          <span key={fk.id} className="relation-tag" title={`${fk.table_name}.${fk.column_name} → ${fk.referenced_column_name}`}>
                                            {fk.table_name}
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                    {rels.map((r: any, i: number) => (
                                      <div key={i} className="relation-line inferred">
                                        <span className="relation-label">业务:</span>
                                        <span className="inferred-text">
                                          {r.source_table === table.table_name
                                            ? `→ ${r.target_table}`
                                            : `${r.source_table} →`}
                                          {r.relationship_type && <span> ({r.relationship_type})</span>}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      {selectedTable && (
                        <div className="columns-section">
                          <h3>字段详情: {selectedTable}</h3>
                          <table className="columns-table">
                            <thead>
                              <tr>
                                <th>字段名</th>
                                <th>类型</th>
                                <th>语义类型</th>
                                <th>可空</th>
                                <th>键</th>
                                <th>业务描述</th>
                              </tr>
                            </thead>
                            <tbody>
                              {getTableColumns(selectedTable).map(col => (
                                <tr key={col.id}>
                                  <td>{col.column_name}</td>
                                  <td>{col.data_type}</td>
                                  <td>{col.semantic_type || '-'}</td>
                                  <td>{col.is_nullable}</td>
                                  <td>{col.column_key || '-'}</td>
                                  <td>{col.business_description || '-'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}

                      {schemaResult.foreign_keys.length > 0 && (
                        <div className="fk-section">
                          <h3>外键约束 ({schemaResult.foreign_keys.length} 个)</h3>
                          <div className="fk-list">
                            {schemaResult.foreign_keys.map(fk => (
                              <div key={fk.id} className="fk-item">
                                <span>{fk.table_name}.{fk.column_name}</span>
                                <span className="fk-arrow">→</span>
                                <span>{fk.referenced_table_name}.{fk.referenced_column_name}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}

                  {viewMode === 'er' && (
                    <ERDiagram
                      tables={schemaResult.tables}
                      foreignKeys={schemaResult.foreign_keys}
                      getTableColumns={getTableColumns}
                    />
                  )}
                </div>
              ) : (
                <div className="empty-state">
                  {selectedDatabase
                    ? '请点击"分析Schema"按钮'
                    : '请从上方选择数据库'}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="modal">
          <div className="modal-content">
            <h2>添加数据源</h2>
            <div className="form-group">
              <label>连接名称 *</label>
              <input
                type="text"
                value={newConnection.name}
                onChange={(e) => setNewConnection({ ...newConnection, name: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>数据库类型 *</label>
              <select
                value={newConnection.type}
                onChange={(e) => setNewConnection({ ...newConnection, type: e.target.value as DbType })}
              >
                {DB_TYPES.map(type => (
                  <option key={type.value} value={type.value}>{type.label}</option>
                ))}
              </select>
            </div>
            {newConnection.type !== 'sqlite' && (
              <>
                <div className="form-group">
                  <label>主机 *</label>
                  <input
                    type="text"
                    value={newConnection.host}
                    onChange={(e) => setNewConnection({ ...newConnection, host: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>端口 *</label>
                  <input
                    type="number"
                    value={newConnection.port}
                    onChange={(e) => setNewConnection({ ...newConnection, port: parseInt(e.target.value) })}
                  />
                </div>
                <div className="form-group">
                  <label>用户名 *</label>
                  <input
                    type="text"
                    value={newConnection.username}
                    onChange={(e) => setNewConnection({ ...newConnection, username: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>密码</label>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <input
                      type={showPwdCreate ? 'text' : 'password'}
                      value={newConnection.password}
                      onChange={(e) => setNewConnection({ ...newConnection, password: e.target.value })}
                      style={{ flex: 1 }}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPwdCreate(!showPwdCreate)}
                      style={{ padding: '4px 8px', fontSize: 12 }}
                    >
                      {showPwdCreate ? '隐藏' : '显示'}
                    </button>
                  </div>
                </div>
              </>
            )}
            {newConnection.type === 'sqlite' && (
              <div className="form-group">
                <label>文件路径 *</label>
                <input
                  type="text"
                  value={newConnection.database}
                  onChange={(e) => setNewConnection({ ...newConnection, database: e.target.value })}
                  placeholder="/path/to/database.db"
                />
              </div>
            )}
            {newConnection.type === 'oracle' && (
              <div className="form-group">
                <label>服务名</label>
                <input
                  type="text"
                  value={newConnection.service_name}
                  onChange={(e) => setNewConnection({ ...newConnection, service_name: e.target.value })}
                />
              </div>
            )}
            <div className="form-group">
              <label>描述</label>
              <textarea
                value={newConnection.description}
                onChange={(e) => setNewConnection({ ...newConnection, description: e.target.value })}
              />
            </div>
            <div className="modal-actions">
              <button onClick={() => setShowCreateModal(false)}>取消</button>
              <button onClick={handleTestCreateConfig} disabled={testingCreate}>
                {testingCreate ? '测试中...' : '测试'}
              </button>
              <button onClick={handleCreateConnection}>创建</button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && (
        <div className="modal">
          <div className="modal-content">
            <h2>编辑数据源</h2>
            <div className="form-group">
              <label>连接名称 *</label>
              <input
                type="text"
                value={newConnection.name}
                onChange={(e) => setNewConnection({ ...newConnection, name: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>数据库类型 *</label>
              <select
                value={newConnection.type}
                onChange={(e) => setNewConnection({ ...newConnection, type: e.target.value as DbType })}
              >
                {DB_TYPES.map(type => (
                  <option key={type.value} value={type.value}>{type.label}</option>
                ))}
              </select>
            </div>
            {newConnection.type !== 'sqlite' && (
              <>
                <div className="form-group">
                  <label>主机 *</label>
                  <input
                    type="text"
                    value={newConnection.host}
                    onChange={(e) => setNewConnection({ ...newConnection, host: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>端口 *</label>
                  <input
                    type="number"
                    value={newConnection.port}
                    onChange={(e) => setNewConnection({ ...newConnection, port: parseInt(e.target.value) })}
                  />
                </div>
                <div className="form-group">
                  <label>用户名 *</label>
                  <input
                    type="text"
                    value={newConnection.username}
                    onChange={(e) => setNewConnection({ ...newConnection, username: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>密码（留空保持不变）</label>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <input
                      type={showPwdEdit ? 'text' : 'password'}
                      value={newConnection.password}
                      onChange={(e) => setNewConnection({ ...newConnection, password: e.target.value })}
                      style={{ flex: 1 }}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPwdEdit(!showPwdEdit)}
                      style={{ padding: '4px 8px', fontSize: 12 }}
                    >
                      {showPwdEdit ? '隐藏' : '显示'}
                    </button>
                  </div>
                </div>
              </>
            )}
            {newConnection.type === 'sqlite' && (
              <div className="form-group">
                <label>文件路径 *</label>
                <input
                  type="text"
                  value={newConnection.database}
                  onChange={(e) => setNewConnection({ ...newConnection, database: e.target.value })}
                />
              </div>
            )}
            {newConnection.type === 'oracle' && (
              <div className="form-group">
                <label>服务名</label>
                <input
                  type="text"
                  value={newConnection.service_name}
                  onChange={(e) => setNewConnection({ ...newConnection, service_name: e.target.value })}
                />
              </div>
            )}
            <div className="form-group">
              <label>描述</label>
              <textarea
                value={newConnection.description}
                onChange={(e) => setNewConnection({ ...newConnection, description: e.target.value })}
              />
            </div>
            <div className="modal-actions">
              <button onClick={() => setShowEditModal(false)}>取消</button>
              <button onClick={handleTestEditConfig} disabled={testingEdit}>
                {testingEdit ? '测试中...' : '测试'}
              </button>
              <button onClick={handleUpdateConnection}>保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default DatabaseManagement;

export type { TableInfo, ColumnInfo, ForeignKeyInfo };
