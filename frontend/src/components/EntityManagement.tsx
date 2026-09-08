import React, { useState, useEffect, useCallback } from 'react';
import { Table, Input, Select, Button, Tag, Space, Popconfirm, message, Tooltip } from 'antd';
import { ReloadOutlined, DeleteOutlined, EditOutlined, PlusOutlined, CloseOutlined, CheckOutlined } from '@ant-design/icons';
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';
import { useEntityStore } from '../stores/entityStore';
import { useAbortController } from '../hooks/useAbortController';
import { entityService } from '../services/entityService';
import type { Entity, Relationship } from '../stores/types';

const entityTypeColors: Record<string, string> = {
  person: '#FF6B6B', organization: '#4ECDC4', location: '#45B7D1',
  event: '#96CEB4', concept: '#F39C12', default: '#95A5A6',
};

// ── 扩展属性编辑组件 ──

const AttributesEditor: React.FC<{
  attributes: Record<string, unknown>;
  entityId: string;
  onUpdated: () => void;
}> = ({ attributes, entityId, onUpdated }) => {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState('');
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [adding, setAdding] = useState(false);

  const entries = Object.entries(attributes || {});

  const handleSave = async (key: string, value: string) => {
    try {
      const updated = { ...attributes, [key]: value };
      await entityService.updateEntity(entityId, { attributes: updated });
      message.success('属性已更新');
      setEditingKey(null);
      onUpdated();
    } catch {
      message.error('更新失败');
    }
  };

  const handleDelete = async (key: string) => {
    try {
      const updated = { ...attributes };
      delete updated[key];
      await entityService.updateEntity(entityId, { attributes: updated });
      message.success('属性已删除');
      onUpdated();
    } catch {
      message.error('删除失败');
    }
  };

  const handleAdd = async () => {
    if (!newKey.trim()) return;
    try {
      const updated = { ...attributes, [newKey.trim()]: newValue };
      await entityService.updateEntity(entityId, { attributes: updated });
      message.success('属性已添加');
      setAdding(false);
      setNewKey('');
      setNewValue('');
      onUpdated();
    } catch {
      message.error('添加失败');
    }
  };

  if (!entries.length && !adding) {
    return (
      <Button size="small" icon={<PlusOutlined />} onClick={() => setAdding(true)}>
        添加属性
      </Button>
    );
  }

  return (
    <div>
      {entries.map(([key, val]) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4, fontSize: 12 }}>
          <span style={{ fontWeight: 'bold', minWidth: 60, flexShrink: 0 }}>{key}:</span>
          {editingKey === key ? (
            <>
              <Input
                size="small"
                value={editingValue}
                onChange={(e) => setEditingValue(e.target.value)}
                style={{ flex: 1 }}
                onPressEnter={() => handleSave(key, editingValue)}
              />
              <Button size="small" type="text" icon={<CheckOutlined />} onClick={() => handleSave(key, editingValue)} />
              <Button size="small" type="text" icon={<CloseOutlined />} onClick={() => setEditingKey(null)} />
            </>
          ) : (
            <>
              <span style={{ flex: 1, wordBreak: 'break-all' }}>{String(val)}</span>
              <Button size="small" type="text" icon={<EditOutlined />}
                onClick={() => { setEditingKey(key); setEditingValue(String(val)); }} />
              <Popconfirm title="删除此属性？" onConfirm={() => handleDelete(key)}>
                <Button size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </>
          )}
        </div>
      ))}
      {adding ? (
        <div style={{ display: 'flex', gap: 4, marginTop: 4, fontSize: 12 }}>
          <Input size="small" placeholder="键" value={newKey} onChange={(e) => setNewKey(e.target.value)} style={{ width: 80 }} />
          <Input size="small" placeholder="值" value={newValue} onChange={(e) => setNewValue(e.target.value)}
            onPressEnter={handleAdd} />
          <Button size="small" type="text" icon={<CheckOutlined />} onClick={handleAdd} />
          <Button size="small" type="text" icon={<CloseOutlined />} onClick={() => setAdding(false)} />
        </div>
      ) : (
        <Button size="small" icon={<PlusOutlined />} onClick={() => setAdding(true)} style={{ marginTop: 4 }}>
          添加
        </Button>
      )}
    </div>
  );
};

// ── 关系列表组件 ──

const RelationshipList: React.FC<{
  relationships: Relationship[];
  currentEntityName: string;
  onNavigateToEntity: (entityId: string) => void;
  onRelationshipChanged: () => void;
}> = ({ relationships, currentEntityName, onNavigateToEntity, onRelationshipChanged }) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editPredicate, setEditPredicate] = useState('');
  const [editDesc, setEditDesc] = useState('');

  const handleDelete = async (relId: string) => {
    try {
      await entityService.deleteRelationship(relId);
      message.success('关系已删除');
      onRelationshipChanged();
    } catch {
      message.error('删除失败');
    }
  };

  const handleSaveEdit = async (relId: string) => {
    try {
      await entityService.updateRelationship(relId, {
        predicate: editPredicate,
        description: editDesc,
      });
      message.success('关系已更新');
      setEditingId(null);
      onRelationshipChanged();
    } catch {
      message.error('更新失败');
    }
  };

  const getRelatedEntityId = (rel: Relationship) => {
    return rel.subject === currentEntityName ? rel.object_id : rel.subject_id;
  };

  const getDirection = (rel: Relationship) => {
    return rel.subject === currentEntityName ? '→' : '←';
  };

  return (
    <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
      {relationships.map((rel) => {
        const relId = rel.relationship_id || rel.id || '';
        const isEditing = editingId === relId;

        return (
          <li key={relId || Math.random()} style={{ marginBottom: 6, paddingBottom: 6, borderBottom: '1px dashed #ddd' }}>
            {isEditing ? (
              <div style={{ fontSize: 12 }}>
                <Space size={4} style={{ marginBottom: 4 }}>
                  <Input size="small" value={editPredicate} onChange={(e) => setEditPredicate(e.target.value)}
                    placeholder="关系类型" style={{ width: 100 }} />
                  <Input size="small" value={editDesc} onChange={(e) => setEditDesc(e.target.value)}
                    placeholder="描述" style={{ flex: 1 }} />
                  <Button size="small" type="text" icon={<CheckOutlined />} onClick={() => handleSaveEdit(relId)} />
                  <Button size="small" type="text" icon={<CloseOutlined />} onClick={() => setEditingId(null)} />
                </Space>
              </div>
            ) : (
              <>
                <div style={{ fontSize: 12, display: 'flex', alignItems: 'center' }}>
                  <span style={{ fontWeight: 'bold' }}>{rel.subject || '未知'}</span>
                  <Tooltip title={rel.description || ''}>
                    <span style={{ margin: '0 6px', color: '#1890ff', fontWeight: 'bold' }}>
                      {rel.predicate || rel.type || '关联'}
                    </span>
                  </Tooltip>
                  <span style={{ fontWeight: 'bold' }}>{rel.object || '未知'}</span>
                  <Space size={2} style={{ marginLeft: 'auto' }}>
                    {getRelatedEntityId(rel) && (
                      <Button size="small" type="link" style={{ fontSize: 11, padding: '0 2px' }}
                        onClick={() => onNavigateToEntity(getRelatedEntityId(rel)!)}>
                        跳转{getDirection(rel)}
                      </Button>
                    )}
                    <Button size="small" type="text" icon={<EditOutlined />} style={{ fontSize: 11 }}
                      onClick={() => {
                        setEditingId(relId);
                        setEditPredicate(rel.predicate || rel.type || '');
                        setEditDesc(rel.description || '');
                      }} />
                    {relId && (
                      <Popconfirm title="删除此关系？" onConfirm={() => handleDelete(relId)}>
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    )}
                  </Space>
                </div>
                <div style={{ fontSize: 11, color: '#666', marginTop: 3 }}>
                  <span>置信度: {((rel.confidence || 0) * 100).toFixed(1)}%</span>
                  {rel.occurrence_time && <span style={{ marginLeft: 10 }}>时间: {rel.occurrence_time}</span>}
                  {rel.description && <div style={{ marginTop: 2 }}>描述: {rel.description}</div>}
                </div>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
};

// ── 主组件 ──

const EntityManagement: React.FC = () => {
  const {
    entities, selectedEntity, pagination, loading,
    fetchEntities, selectEntity, setPagination,
  } = useEntityStore();

  const { getComponentSignal, getLatestSignal } = useAbortController();
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<string>('all');

  useEffect(() => {
    const signal = getComponentSignal();
    fetchEntities(1, pagination.pageSize, searchTerm, filterType, signal);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleTableChange = (pag: TablePaginationConfig) => {
    const p = pag.current || 1;
    const ps = pag.pageSize || 10;
    setPagination({ current: p, pageSize: ps });
    const signal = getLatestSignal('entities');
    fetchEntities(p, ps, searchTerm, filterType, signal);
  };

  const handleSearch = (value: string) => {
    setSearchTerm(value);
    setPagination({ current: 1 });
    const signal = getLatestSignal('entities');
    fetchEntities(1, pagination.pageSize, value, filterType, signal);
  };

  const handleTypeChange = (value: string) => {
    setFilterType(value);
    setPagination({ current: 1 });
    const signal = getLatestSignal('entities');
    fetchEntities(1, pagination.pageSize, searchTerm, value, signal);
  };

  const handleRefresh = () => {
    const signal = getComponentSignal();
    fetchEntities(pagination.current, pagination.pageSize, searchTerm, filterType, signal);
  };

  // 跳转到关联实体
  const handleNavigateToEntity = useCallback((entityId: string) => {
    const target = entities.find(e => e.id === entityId);
    if (target) {
      selectEntity(target);
    } else {
      // 实体不在当前列表，直接按 ID 获取
      selectEntity({ id: entityId, name: '', type: '', confidence: 0 } as Entity);
    }
  }, [entities, selectEntity]);

  // 关系/属性变更后刷新当前实体
  const handleEntityRefresh = useCallback(() => {
    if (selectedEntity) {
      selectEntity(selectedEntity);
    }
  }, [selectedEntity, selectEntity]);

  const columns: ColumnsType<Entity> = [
    {
      title: '实体名称', dataIndex: 'name', key: 'name', ellipsis: true, width: '35%',
    },
    {
      title: '类型', dataIndex: 'type', key: 'type', width: '25%',
      render: (type: string) => (
        <Tag color={entityTypeColors[type] || entityTypeColors.default}>{type}</Tag>
      ),
    },
    {
      title: '置信度', dataIndex: 'confidence', key: 'confidence', align: 'center', width: '20%',
      render: (confidence: number) => `${((confidence || 0) * 100).toFixed(1)}%`,
    },
    {
      title: '出现次数', dataIndex: 'count', key: 'count', align: 'center', width: '20%',
      render: (count: number) => count ?? 0,
    },
  ];

  const attrs = (selectedEntity?.attributes || {}) as Record<string, unknown>;
  const hasAttrs = Object.keys(attrs).length > 0;

  return (
    <div className="entity-management">
      <div className="entity-header">
        <div className="entity-search" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
          <Button icon={<ReloadOutlined />} onClick={handleRefresh}>刷新</Button>
          <Input.Search placeholder="搜索实体..." allowClear onSearch={handleSearch} style={{ width: 280 }} />
          <Select value={filterType} onChange={handleTypeChange} style={{ width: 130 }}>
            <Select.Option value="all">所有类型</Select.Option>
            <Select.Option value="person">人物</Select.Option>
            <Select.Option value="organization">组织</Select.Option>
            <Select.Option value="location">地点</Select.Option>
            <Select.Option value="event">事件</Select.Option>
            <Select.Option value="concept">概念</Select.Option>
          </Select>
        </div>
      </div>

      <div className="entity-content" style={{ display: 'flex', gap: 12 }}>
        <div className="entity-list" style={{ flex: 1, minWidth: 0 }}>
          <Table
            columns={columns}
            dataSource={entities}
            rowKey="id"
            loading={loading}
            pagination={{
              current: pagination.current,
              pageSize: pagination.pageSize,
              total: pagination.total,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50', '100'],
              showTotal: (total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`,
            }}
            onChange={handleTableChange}
            onRow={(record) => ({
              onClick: () => selectEntity(record),
              style: { cursor: 'pointer', background: selectedEntity?.id === record.id ? '#e6f7ff' : undefined },
            })}
            size="small"
            scroll={{ y: 'calc(100vh - 320px)' }}
          />
        </div>

        <div className="entity-details" style={{ flex: 1, border: '1px solid #e0e0e0', borderRadius: '4px', padding: 10, overflow: 'auto', minWidth: 300 }}>
          {selectedEntity ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, paddingBottom: 6, borderBottom: '1px solid #e0e0e0' }}>
                <h3 style={{ margin: 0, fontSize: 16 }}>{selectedEntity.name}</h3>
                <Tag color={entityTypeColors[selectedEntity.type] || entityTypeColors.default}>{selectedEntity.type}</Tag>
              </div>

              {/* 基础属性 */}
              <div style={{ marginBottom: 12 }}>
                <h4 style={{ margin: '0 0 6px 0', fontSize: 13, fontWeight: 'bold' }}>基础属性</h4>
                <div style={{ backgroundColor: '#f9f9f9', padding: 8, borderRadius: 4 }}>
                  <div style={{ marginBottom: 5, display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span style={{ fontWeight: 'bold' }}>置信度:</span>
                    <span>{((selectedEntity.confidence || 0) * 100).toFixed(1)}%</span>
                  </div>
                  <div style={{ marginBottom: 5, display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span style={{ fontWeight: 'bold' }}>出现次数:</span>
                    <span>{selectedEntity.count || 0}</span>
                  </div>
                  {selectedEntity.description && (
                    <div style={{ marginBottom: 5, fontSize: 12 }}>
                      <span style={{ fontWeight: 'bold', display: 'block', marginBottom: 3 }}>描述:</span>
                      <span style={{ display: 'block', whiteSpace: 'pre-wrap' }}>{selectedEntity.description}</span>
                    </div>
                  )}
                  {selectedEntity.byname && (
                    <div style={{ marginBottom: 5, fontSize: 12 }}>
                      <span style={{ fontWeight: 'bold', display: 'block', marginBottom: 3 }}>别名:</span>
                      <span>{Array.isArray(selectedEntity.byname) ? selectedEntity.byname.join('、') : selectedEntity.byname}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* 扩展属性 */}
              <div style={{ marginBottom: 12 }}>
                <h4 style={{ margin: '0 0 6px 0', fontSize: 13, fontWeight: 'bold' }}>
                  扩展属性 {hasAttrs && <span style={{ fontWeight: 'normal', color: '#999' }}>({Object.keys(attrs).length})</span>}
                </h4>
                <div style={{ backgroundColor: '#f9f9f9', padding: 8, borderRadius: 4 }}>
                  <AttributesEditor
                    attributes={attrs}
                    entityId={selectedEntity.id}
                    onUpdated={handleEntityRefresh}
                  />
                </div>
              </div>

              {/* 关联关系 */}
              {selectedEntity.relationships && selectedEntity.relationships.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <h4 style={{ margin: '0 0 6px 0', fontSize: 13, fontWeight: 'bold' }}>
                    关联关系 <span style={{ fontWeight: 'normal', color: '#999' }}>({selectedEntity.relationships.length})</span>
                  </h4>
                  <div style={{ backgroundColor: '#f9f9f9', padding: 8, borderRadius: 4 }}>
                    <RelationshipList
                      relationships={selectedEntity.relationships}
                      currentEntityName={selectedEntity.name}
                      onNavigateToEntity={handleNavigateToEntity}
                      onRelationshipChanged={handleEntityRefresh}
                    />
                  </div>
                </div>
              )}

              {/* 数据来源 */}
              <div>
                <h4 style={{ margin: '0 0 6px 0', fontSize: 13, fontWeight: 'bold' }}>数据来源</h4>
                {selectedEntity.datasource ? (
                  <div style={{ backgroundColor: '#f9f9f9', padding: 8, borderRadius: 4 }}>
                    <div style={{ fontSize: 12, color: '#333', wordBreak: 'break-all' }}>{selectedEntity.datasource}</div>
                  </div>
                ) : (
                  <p style={{ margin: 0, color: '#999', fontSize: 12 }}>暂无数据来源信息</p>
                )}
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#999', fontSize: 13 }}>
              请选择一个实体查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default EntityManagement;
