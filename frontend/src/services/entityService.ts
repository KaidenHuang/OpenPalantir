import { httpGet, httpPost, httpPut, httpDelete } from './httpClient';
import { API_CONFIG } from '../config/apiConfig';
import type { Entity, Relationship } from '../stores/types';

interface Pagination {
  total_count: number;
  total_pages: number;
  current_page: number;
  page_size: number;
}

interface EntityListResponse {
  status: string;
  data: {
    entities: Entity[];
    pagination: Pagination;
  };
}

interface EntityResponse {
  status: string;
  data: {
    entity: Entity;
  };
}

interface RelationshipsResponse {
  status: string;
  data: {
    relationships: Relationship[];
  };
}

interface EntitySearchRequest {
  query: string;
  limit?: number;
  page?: number;
  entity_type?: string;
}

interface EntityUpdateRequest {
  name?: string;
  type?: string;
  description?: string;
  attributes?: Record<string, unknown>;
}

export const entityService = {
  // 获取实体列表
  async listEntities(page: number = 1, limit: number = 10, entityType?: string, query?: string, signal?: AbortSignal): Promise<EntityListResponse> {
    try {
      const params: Record<string, unknown> = { page, limit };
      if (entityType) params.entity_type = entityType;
      if (query) params.query = query;
      const response = await httpGet(API_CONFIG.endpoints.graph.nodes, { params, signal });
      return response.data;
    } catch (error) {
      console.error('Error listing entities:', error);
      throw error;
    }
  },

  // 获取实体详情
  async getEntity(entityId: string, signal?: AbortSignal): Promise<EntityResponse> {
    try {
      const response = await httpGet(API_CONFIG.endpoints.graph.node(entityId), { signal });
      return response.data;
    } catch (error) {
      console.error(`Error getting entity ${entityId}:`, error);
      throw error;
    }
  },

  // 搜索实体
  async searchEntities(request: EntitySearchRequest, signal?: AbortSignal): Promise<EntityListResponse> {
    try {
      const response = await httpPost(API_CONFIG.endpoints.graph.searchNodes, request, { signal });
      return response.data;
    } catch (error) {
      console.error('Error searching entities:', error);
      throw error;
    }
  },

  // 更新实体
  async updateEntity(entityId: string, request: EntityUpdateRequest, signal?: AbortSignal): Promise<{ status: string; message: string }> {
    try {
      const response = await httpPut(API_CONFIG.endpoints.graph.updateNode(entityId), request, { signal });
      return response.data;
    } catch (error) {
      console.error(`Error updating entity ${entityId}:`, error);
      throw error;
    }
  },

  // 删除实体
  async deleteEntity(entityId: string, signal?: AbortSignal): Promise<{ status: string; message: string }> {
    try {
      const response = await httpDelete(API_CONFIG.endpoints.graph.deleteNode(entityId), { signal });
      return response.data;
    } catch (error) {
      console.error(`Error deleting entity ${entityId}:`, error);
      throw error;
    }
  },

  // 获取实体关系
  async getEntityRelationships(entityId: string, signal?: AbortSignal): Promise<RelationshipsResponse> {
    try {
      const response = await httpGet(API_CONFIG.endpoints.graph.nodeRelationships(entityId), { signal });
      return response.data;
    } catch (error) {
      console.error(`Error getting relationships for entity ${entityId}:`, error);
      throw error;
    }
  },

  // 更新关系属性
  async updateRelationship(relationshipId: string, props: Record<string, unknown>, signal?: AbortSignal): Promise<{ status: string }> {
    try {
      const response = await httpPut(API_CONFIG.endpoints.graph.updateRelationship(relationshipId), props, { signal });
      return response.data;
    } catch (error) {
      console.error(`Error updating relationship ${relationshipId}:`, error);
      throw error;
    }
  },

  // 删除关系
  async deleteRelationship(relationshipId: string, signal?: AbortSignal): Promise<{ status: string }> {
    try {
      const response = await httpDelete(API_CONFIG.endpoints.graph.deleteRelationship(relationshipId), { signal });
      return response.data;
    } catch (error) {
      console.error(`Error deleting relationship ${relationshipId}:`, error);
      throw error;
    }
  },

  // 获取实体 N-hop 子图
  async getEntitySubgraph(entityId: string, hops: number = 2, limit: number = 100, signal?: AbortSignal): Promise<{
    status: string;
    data: { nodes: Entity[]; edges: Array<{ source: string; target: string; predicate: string; confidence: number; relationship_id: string; description: string }> };
  }> {
    try {
      const response = await httpGet(API_CONFIG.endpoints.graph.nodeSubgraph(entityId, hops, limit), { signal });
      return response.data;
    } catch (error) {
      console.error(`Error getting subgraph for entity ${entityId}:`, error);
      throw error;
    }
  },
};
