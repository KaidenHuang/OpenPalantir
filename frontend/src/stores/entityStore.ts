/**
 * entityStore — 实体管理状态
 *
 * 管理实体搜索/列表/详情/关系。
 * 迁移自 EntityManagement。
 */
import { create } from 'zustand';
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

interface Pagination {
  current: number;
  pageSize: number;
  total: number;
}

interface EntityState {
  // 数据
  entities: Entity[];
  selectedEntity: Entity | null;
  pagination: Pagination;
  loading: boolean;

  // 缓存
  _lastFetched: number;
  _staleTime: number;

  // Actions
  fetchEntities: (page: number, pageSize: number, search: string, type: string) => Promise<void>;
  selectEntity: (entity: Entity) => Promise<void>;
  setPagination: (pagination: Partial<Pagination>) => void;
}

export const useEntityStore = create<EntityState>()((set, get) => ({
  entities: [],
  selectedEntity: null,
  pagination: { current: 1, pageSize: 50, total: 0 },
  loading: false,
  _lastFetched: 0,
  _staleTime: 10_000,

  fetchEntities: async (page, pageSize, search, type) => {
    set({ loading: true });
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
        const mapped = (response.data.entities || []).map((entity) => ({
          ...entity,
          id: entity.id || (entity as unknown as Record<string, unknown>).entity_id || `e_${Math.random().toString(36).slice(2, 8)}`,
          count: entity.count ?? entity.count,
        })) as Entity[];
        set({
          entities: mapped,
          pagination: {
            current: response.data.pagination.current_page,
            pageSize: response.data.pagination.page_size,
            total: response.data.pagination.total_count,
          },
          loading: false,
        });
      } else {
        set({ entities: [], pagination: { ...get().pagination, total: 0, current: 1 }, loading: false });
      }
    } catch {
      set({ entities: [], pagination: { ...get().pagination, total: 0, current: 1 }, loading: false });
    }
  },

  selectEntity: async (entity) => {
    try {
      const response = await entityService.getEntity(entity.id);
      if (response.status === 'success' && response.data) {
        const entityData = response.data.entity;
        const relationshipsResponse = await entityService.getEntityRelationships(entity.id);
        if (relationshipsResponse.status === 'success' && relationshipsResponse.data) {
          set({
            selectedEntity: {
              ...entityData,
              relationships: relationshipsResponse.data.relationships || [],
            } as Entity,
          });
        } else {
          set({ selectedEntity: entityData as Entity });
        }
      } else {
        set({ selectedEntity: entity });
      }
    } catch {
      set({ selectedEntity: entity });
    }
  },

  setPagination: (partial) => set((s) => ({ pagination: { ...s.pagination, ...partial } })),
}));