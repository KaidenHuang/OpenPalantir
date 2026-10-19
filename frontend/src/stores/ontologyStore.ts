/**
 * ontologyStore — 本体标识的中文显示名
 *
 * 图谱节点只存实体类型 key（如 person）、边只存谓词 key，界面要显示中文只能自己翻译。
 * 词表取自 GET /api/ontology/vocabulary（全部域视图的 key→display_name 并集），
 * 一次拉取全局复用；未命中的 key 原样显示，绝不显示空白。
 */
import { useEffect, useMemo } from 'react';
import { create } from 'zustand';
import { httpGet } from '../services/httpClient';
import { API_CONFIG } from '../config/apiConfig';

export interface OntologyTerm {
  key: string;
  display_name: string;
}

export interface OntologyNamedTerm {
  name: string;
  display_name: string;
}

interface Vocabulary {
  object_types?: OntologyTerm[];
  link_types?: OntologyTerm[];
  domains?: OntologyNamedTerm[];
}

interface OntologyState {
  typeLabels: Record<string, string>;
  predicateLabels: Record<string, string>;
  domainLabels: Record<string, string>;
  objectTypes: OntologyTerm[];
}

const toMap = (terms: { key: string; display_name: string }[] = []) =>
  Object.fromEntries(terms.map(t => [t.key, t.display_name || t.key]));

const toNameMap = (terms: OntologyNamedTerm[] = []) =>
  Object.fromEntries(terms.map(t => [t.name, t.display_name || t.name]));

const useOntologyStore = create<OntologyState>()(() => ({
  typeLabels: {},
  predicateLabels: {},
  domainLabels: {},
  objectTypes: [],
}));

let pending: Promise<void> | null = null;

/** 词表一次会话只取一次；失败时清空以便下次挂载重试，期间界面显示原始 key */
export function loadOntologyVocabulary(): Promise<void> {
  if (!pending) {
    pending = httpGet<Vocabulary>(API_CONFIG.endpoints.ontology.vocabulary)
      .then(res => {
        useOntologyStore.setState({
          typeLabels: toMap(res.data.object_types),
          predicateLabels: toMap(res.data.link_types),
          domainLabels: toNameMap(res.data.domains),
          objectTypes: res.data.object_types || [],
        });
      })
      .catch(() => {
        pending = null;
      });
  }
  return pending;
}

/** 把标识翻译成显示名；空标识返回空串，未知标识返回原值 */
const labelOf = (map: Record<string, string>) =>
  (key?: string | null): string => (key ? map[key] ?? key : '');

export interface OntologyLabels {
  labelType: (key?: string | null) => string;
  labelPredicate: (key?: string | null) => string;
  labelDomain: (key?: string | null) => string;
  /** 本体词表里的实体类型，供「按类型筛选」一类控件使用（value 仍是原始 key） */
  objectTypes: OntologyTerm[];
}

export function useOntologyLabels(): OntologyLabels {
  const typeLabels = useOntologyStore(s => s.typeLabels);
  const predicateLabels = useOntologyStore(s => s.predicateLabels);
  const domainLabels = useOntologyStore(s => s.domainLabels);
  const objectTypes = useOntologyStore(s => s.objectTypes);

  useEffect(() => {
    void loadOntologyVocabulary();
  }, []);

  return useMemo(() => ({
    labelType: labelOf(typeLabels),
    labelPredicate: labelOf(predicateLabels),
    labelDomain: labelOf(domainLabels),
    objectTypes,
  }), [typeLabels, predicateLabels, domainLabels, objectTypes]);
}
