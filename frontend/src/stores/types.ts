/**
 * 前端 Stores 共享类型定义
 *
 * 从各组件中提取的接口定义，统一管理以避免重复。
 */

// ============================================================
// 图谱相关
// ============================================================

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  count: number;
  color: string;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
  confidence: number;
  width: number;
  color: string;
  subject_id?: string;
  object_id?: string;
  occurrence_time?: string;
  description?: string;
}

// ============================================================
// 任务相关
// ============================================================

export interface Task {
  task_id: string;
  task_type: string;
  status: string;
  progress: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  document_name?: string;
  payload?: unknown;
  result?: unknown;
}

// ============================================================
// 文档源相关
// ============================================================

export interface DocumentSource {
  id: string;
  name: string;
  path: string;
  source_type: 'local' | 's3';
  created_at: string;
  updated_at: string;
  is_deleted?: boolean;
}

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size?: number;
  modified?: string;
}

export interface SummaryData {
  doc_name?: string;
  structure?: Record<string, unknown>[];
  summary?: string;
  [key: string]: unknown;
}

export interface Entity {
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

export interface Relationship {
  subject: string;
  object: string;
  type: string;
  predicate?: string;
  confidence: number;
  occurrence_time?: string;
  description?: string;
}

// ============================================================
// 模型相关
// ============================================================

export interface ModelPlatform {
  key: string;
  label: string;
  apiUrl: string;
  apiKey: string;
  models: ModelInfo[];
}

export interface ModelInfo {
  id: number;
  name: string;
  model_type: 'local' | 'cloud';
  platform: string;
  enabled: boolean;
}

export interface PlatformConfig {
  apiUrl: string;
  apiKey: string;
  modelName: string;
}

// ============================================================
// 数据库相关
// ============================================================

export interface DatabaseConnection {
  id: string;
  name: string;
  connection_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  is_deleted?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface SchemaTable {
  table_name: string;
  entity_type?: string;
}

export interface SchemaColumn {
  table_name: string;
  column_name: string;
  data_type?: string;
  column_key?: string;
}

export interface SchemaForeignKey {
  table_name: string;
  column_name: string;
  referenced_table_name: string;
  referenced_column_name: string;
}

export interface InferredRelationship {
  source_table: string;
  target_table: string;
  relationship_type?: string;
}

export interface SchemaResult {
  tables: SchemaTable[];
  columns: SchemaColumn[];
  foreign_keys: SchemaForeignKey[];
  inferred_relationships?: InferredRelationship[];
}

export interface DbSummary {
  db_description?: string;
  business_domain?: string;
  key_entities?: string[];
}

export interface DatabaseItem {
  name: string;
  size?: string;
  tables?: number;
}