import React, { useState, useEffect, useCallback } from 'react';
import { Table, Input, Select, Button, Tag, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';
import { entityService } from '../services/entityService';

interface Entity {
  id: string;
  name: string;
  type: string;
  confidence: number;
  count?: number;
  description?: string;
  byname?: string | string[];
  properties?: Record<string, string>;
  datasource?: string;
  relationships?: Relationship[];
}

interface Relationship {
  subject: string;
  object: string;
  type: string;
  predicate?: string;
  confidence: number;
  occurrence_time?: string;
  description?: string;
}

const entityTypeColors: Record<string, string> = {
  person: '#FF6B6B',
  organization: '#4ECDC4',
  location: '#45B7D1',
  event: '#96CEB4',
  concept: '#F39C12',
  default: '#95A5A6',
};

const EntityManagement: React.FC = () => {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<string>('all');
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 50,
    total: 0,
  });

  const fetchEntities = useCallback(async (
    page: number,
    pageSize: number,
    search: string,
    type: string,
  ) => {
    setLoading(true);
    try {
      const entityType = type === 'all' ? undefined : type;
      const response = search.trim()
        ? await entityService.searchEntities({
            query: search.trim(),
            page,
            limit: pageSize,
            entity_type: entityType,
          })
        : await entityService.listEntities(page, pageSize, entityType, search.trim() || undefined);

      if (response.status === 'success' && response.data) {
        const mapped = (response.data.entities || []).map((entity: any) => ({
          ...entity,
          id: entity.id || entity.entity_id || `e_${Math.random().toString(36).slice(2, 8)}`,
          count: entity.count ?? entity.count,
        }));
        setEntities(mapped);
        setPagination({
          current: response.data.pagination.current_page,
          pageSize: response.data.pagination.page_size,
          total: response.data.pagination.total_count,
        });
      } else {
        setEntities([]);
        setPagination(prev => ({ ...prev, total: 0, current: 1 }));
      }
    } catch (error) {
      message.error('获取实体列表失败');
      console.error('Error fetching entities:', error);
      setEntities([]);
      setPagination(prev => ({ ...prev, total: 0, current: 1 }));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEntities(1, pagination.pageSize, searchTerm, filterType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleTableChange = (pag: TablePaginationConfig) => {
    const p = pag.current || 1;
    const ps = pag.pageSize || 10;
    setPagination(prev => ({ ...prev, current: p, pageSize: ps }));
    fetchEntities(p, ps, searchTerm, filterType);
  };

  const handleSearch = (value: string) => {
    setSearchTerm(value);
    setPagination(prev => ({ ...prev, current: 1 }));
    fetchEntities(1, pagination.pageSize, value, filterType);
  };

  const handleTypeChange = (value: string) => {
    setFilterType(value);
    setPagination(prev => ({ ...prev, current: 1 }));
    fetchEntities(1, pagination.pageSize, searchTerm, value);
  };

  const handleRefresh = () => {
    fetchEntities(pagination.current, pagination.pageSize, searchTerm, filterType);
  };

  const handleEntitySelect = async (entity: Entity) => {
    try {
      const response = await entityService.getEntity(entity.id);
      if (response.status === 'success' && response.data) {
        const { entity: entityData } = response.data;
        setSelectedEntity(entityData);
        const relationshipsResponse = await entityService.getEntityRelationships(entity.id);
        if (relationshipsResponse.status === 'success' && relationshipsResponse.data) {
          setSelectedEntity({
            ...entityData,
            relationships: relationshipsResponse.data.relationships || [],
          });
        }
      } else {
        setSelectedEntity(entity);
      }
    } catch (error) {
      console.error('Error fetching entity details:', error);
      setSelectedEntity(entity);
    }
  };

  const columns: ColumnsType<Entity> = [
    {
      title: '实体名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      width: '35%',
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: '25%',
      render: (type: string) => (
        <Tag color={entityTypeColors[type] || entityTypeColors.default}>
          {type}
        </Tag>
      ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      key: 'confidence',
      align: 'center',
      width: '20%',
      render: (confidence: number) => `${((confidence || 0) * 100).toFixed(1)}%`,
    },
    {
      title: '出现次数',
      dataIndex: 'count',
      key: 'count',
      align: 'center',
      width: '20%',
      render: (count: number) => count ?? 0,
    },
  ];

  return (
    <div className="entity-management">
      <div className="entity-header">
        <div className="entity-search" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
          <Button icon={<ReloadOutlined />} onClick={handleRefresh}>
            刷新
          </Button>
          <Input.Search
            placeholder="搜索实体..."
            allowClear
            onSearch={handleSearch}
            style={{ width: 280 }}
          />
          <Select
            value={filterType}
            onChange={handleTypeChange}
            style={{ width: 130 }}
          >
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
              showTotal: (total, range) =>
                `第 ${range[0]}-${range[1]} 条，共 ${total} 条`,
            }}
            onChange={handleTableChange}
            onRow={(record) => ({
              onClick: () => handleEntitySelect(record),
              style: {
                cursor: 'pointer',
                background: selectedEntity?.id === record.id ? '#e6f7ff' : undefined,
              },
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
                <Tag color={entityTypeColors[selectedEntity.type] || entityTypeColors.default}>
                  {selectedEntity.type}
                </Tag>
              </div>

              <div style={{ marginBottom: 12 }}>
                <h4 style={{ margin: '0 0 6px 0', fontSize: 13, fontWeight: 'bold' }}>实体属性</h4>
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
                  {selectedEntity.properties && Object.entries(selectedEntity.properties).map(([key, value]) => (
                    <div key={key} style={{ marginBottom: 5, display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                      <span style={{ fontWeight: 'bold' }}>{key}:</span>
                      <span>{value}</span>
                    </div>
                  ))}
                </div>
              </div>

              {selectedEntity.relationships && selectedEntity.relationships.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <h4 style={{ margin: '0 0 6px 0', fontSize: 13, fontWeight: 'bold' }}>关联关系</h4>
                  <div style={{ backgroundColor: '#f9f9f9', padding: 8, borderRadius: 4 }}>
                    <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
                      {selectedEntity.relationships.map((relationship, index) => (
                        <li key={index} style={{ marginBottom: 6, paddingBottom: 6, borderBottom: '1px dashed #ddd' }}>
                          <div style={{ fontSize: 12 }}>
                            <span style={{ fontWeight: 'bold' }}>{relationship.subject || '未知'}</span>
                            <span style={{ margin: '0 6px', color: '#1890ff', fontWeight: 'bold' }}>{relationship.predicate || relationship.type || '关联'}</span>
                            <span style={{ fontWeight: 'bold' }}>{relationship.object || '未知'}</span>
                          </div>
                          <div style={{ fontSize: 11, color: '#666', marginTop: 3 }}>
                            <span>置信度: {((relationship.confidence || 0) * 100).toFixed(1)}%</span>
                            {relationship.occurrence_time && (
                              <span style={{ marginLeft: 10 }}>时间: {relationship.occurrence_time}</span>
                            )}
                            {relationship.description && (
                              <div style={{ marginTop: 2 }}>描述: {relationship.description}</div>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              <div>
                <h4 style={{ margin: '0 0 6px 0', fontSize: 13, fontWeight: 'bold' }}>数据来源</h4>
                {selectedEntity.datasource ? (
                  <div style={{ backgroundColor: '#f9f9f9', padding: 8, borderRadius: 4 }}>
                    <div style={{ fontSize: 12, color: '#333', wordBreak: 'break-all' }}>
                      {selectedEntity.datasource}
                    </div>
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
