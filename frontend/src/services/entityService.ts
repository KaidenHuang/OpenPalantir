import axios from 'axios';
import { API_CONFIG } from '../config/apiConfig';

interface Entity {
  id: string;
  name: string;
  type: string;
  confidence: number;
  count?: number;
  properties?: Record<string, string>;
  documents?: string[];
  relationships?: Relationship[];
  document_id?: string;
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
  attributes?: Record<string, any>;
}

export const entityService = {
  // 获取实体列表
  async listEntities(page: number = 1, limit: number = 10, entityType?: string, query?: string): Promise<EntityListResponse> {
    try {
      const params: Record<string, any> = { page, limit };
      if (entityType) params.entity_type = entityType;
      if (query) params.query = query;
      const response = await axios.get(API_CONFIG.endpoints.graph.nodes, { params });
      return response.data;
    } catch (error) {
      console.error('Error listing entities:', error);
      throw error;
    }
  },

  // 获取实体详情
  async getEntity(entityId: string): Promise<EntityResponse> {
    try {
      const response = await axios.get(API_CONFIG.endpoints.graph.node(entityId));
      return response.data;
    } catch (error) {
      console.error(`Error getting entity ${entityId}:`, error);
      throw error;
    }
  },

  // 搜索实体
  async searchEntities(request: EntitySearchRequest): Promise<EntityListResponse> {
    try {
      const response = await axios.post(API_CONFIG.endpoints.graph.searchNodes, request);
      return response.data;
    } catch (error) {
      console.error('Error searching entities:', error);
      throw error;
    }
  },

  // 更新实体
  async updateEntity(entityId: string, request: EntityUpdateRequest): Promise<{ status: string; message: string }> {
    try {
      const response = await axios.put(API_CONFIG.endpoints.graph.updateNode(entityId), request);
      return response.data;
    } catch (error) {
      console.error(`Error updating entity ${entityId}:`, error);
      throw error;
    }
  },

  // 删除实体
  async deleteEntity(entityId: string): Promise<{ status: string; message: string }> {
    try {
      const response = await axios.delete(API_CONFIG.endpoints.graph.deleteNode(entityId));
      return response.data;
    } catch (error) {
      console.error(`Error deleting entity ${entityId}:`, error);
      throw error;
    }
  },

  // 获取实体关系
  async getEntityRelationships(entityId: string): Promise<RelationshipsResponse> {
    try {
      const response = await axios.get(API_CONFIG.endpoints.graph.nodeRelationships(entityId));
      return response.data;
    } catch (error) {
      console.error(`Error getting relationships for entity ${entityId}:`, error);
      throw error;
    }
  },
};
