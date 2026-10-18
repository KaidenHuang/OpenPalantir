import { useCallback, useEffect, useMemo, useState } from 'react';
import { message, Button, Tag, Input, Spin, Popover } from 'antd';
import { ReloadOutlined, EditOutlined, SaveOutlined } from '@ant-design/icons';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useNavigate } from 'react-router-dom';
import { API_CONFIG } from '../config/apiConfig';
import { httpGet, httpPost, httpPut } from '../services/httpClient';
import { useAbortController } from '../hooks/useAbortController';
import { useSafePolling } from '../hooks/useSafePolling';

interface SourceRef {
  n: number;
  datasource: string;
  node_id: string;
  title: string;
}

interface WikiPage {
  page_id: string;
  title: string;
  kind: 'document' | 'topic' | 'entity' | 'answer';
  status: 'draft' | 'published';
  content: string;
  source_refs: SourceRef[];
  datasource: string;
  links: string[];
  created_at: string;
  updated_at: string;
}

const KIND_LABELS: Record<string, string> = {
  document: '文档页',
  topic: '主题页',
  entity: '实体页',
  answer: '问答沉淀',
};

const KIND_COLORS: Record<string, string> = {
  document: 'blue',
  topic: 'green',
  entity: 'purple',
  answer: 'orange',
};

/** 把正文里的 [n] 引用编号变成锚点链接，交给自定义 a 渲染器处理（代码块内原样保留） */
function linkifyCitations(md: string): string {
  let inCodeFence = false;
  return md.split('\n').map(line => {
    if (/^\s*(```|~~~)/.test(line)) {
      inCodeFence = !inCodeFence;
      return line;
    }
    return inCodeFence ? line : line.replace(/\[(\d+)\](?!\()/g, '[\\[$1\\]](#cite-$1)');
  }).join('\n');
}

/** DOC://{source_id}/{文件相对路径} */
function parseDocDatasource(ds: string): { sourceId: string; file: string } | null {
  if (!ds.startsWith('DOC://')) return null;
  const rest = ds.slice('DOC://'.length);
  const slash = rest.indexOf('/');
  if (slash <= 0) return null;
  return { sourceId: rest.slice(0, slash), file: rest.slice(slash + 1) };
}

function WikiViewer() {
  const [pages, setPages] = useState<WikiPage[]>([]);
  const [current, setCurrent] = useState<WikiPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [pendingEntity, setPendingEntity] = useState<string | null>(null);
  const { getComponentSignal } = useAbortController();
  const navigate = useNavigate();

  const loadPages = useCallback(async () => {
    try {
      const signal = getComponentSignal();
      const res = await httpGet(API_CONFIG.endpoints.wiki.pages, { signal });
      const list: WikiPage[] = res.data.pages || [];
      setPages(list);
      setCurrent(prev => (prev ? list.find(p => p.page_id === prev.page_id) || prev : prev));
      return list;
    } catch {
      // 列表加载失败时保留现有状态
      return [] as WikiPage[];
    }
  }, [getComponentSignal]);

  useEffect(() => {
    setLoading(true);
    loadPages().finally(() => setLoading(false));
  }, [loadPages]);

  // 图谱右键菜单跳转：为指定实体生成页面
  useEffect(() => {
    const raw = sessionStorage.getItem('wiki_pending_entity');
    if (!raw) return;
    sessionStorage.removeItem('wiki_pending_entity');
    try {
      const { entity_id } = JSON.parse(raw) as { entity_id: string };
      if (!entity_id) return;
      setPendingEntity(`ENT://${entity_id}/`);
      httpPost(API_CONFIG.endpoints.wiki.generate, { entity_id })
        .then(res => setTaskId(res.data.task_id))
        .catch(() => message.error('实体页生成任务提交失败'));
    } catch {
      // 忽略损坏的暂存值
    }
  }, []);

  const openPage = async (pageId: string) => {
    try {
      const signal = getComponentSignal();
      const res = await httpGet<WikiPage>(API_CONFIG.endpoints.wiki.page(pageId), { signal });
      setCurrent(res.data);
      setEditing(false);
    } catch {
      message.error('页面加载失败');
    }
  };

  const savePage = async () => {
    if (!current) return;
    try {
      await httpPut(API_CONFIG.endpoints.wiki.page(current.page_id), { content: draft });
      message.success('已保存');
      await loadPages();
      setEditing(false);
    } catch {
      message.error('保存失败');
    }
  };

  const publishPage = async () => {
    if (!current) return;
    try {
      await httpPost(API_CONFIG.endpoints.wiki.status(current.page_id), { status: 'published' });
      message.success('已发布');
      await loadPages();
    } catch {
      message.error('发布失败');
    }
  };

  const startGenerate = async (scope: 'all' | 'topics' | 'entities') => {
    try {
      const res = await httpPost(API_CONFIG.endpoints.wiki.generate, { scope });
      setTaskId(res.data.task_id);
      message.info('Wiki 生成任务已提交');
    } catch {
      message.error('生成任务提交失败');
    }
  };

  useSafePolling(async () => {
    const res = await httpGet(API_CONFIG.endpoints.task.get(taskId!));
    const status = res.data.status;
    if (status === 'completed') {
      setTaskId(null);
      const list = await loadPages();
      if (pendingEntity) {
        const hit = list.find(p => p.datasource.startsWith(pendingEntity));
        setPendingEntity(null);
        if (hit) {
          await openPage(hit.page_id);
          message.success('实体页已生成');
          return;
        }
        message.warning('该实体暂未生成 Wiki 页');
        return;
      }
      message.success('Wiki 生成完成');
    } else if (status === 'failed') {
      setTaskId(null);
      setPendingEntity(null);
      message.error(`Wiki 生成失败: ${res.data.error || '未知错误'}`);
    }
  }, 3000, !!taskId);

  const askAboutPage = () => {
    if (!current) return;
    sessionStorage.setItem(
      'decision_pending_scope',
      JSON.stringify({ datasource: current.datasource, title: current.title }),
    );
    navigate('/decision');
  };

  /** 引用锚点跳回文档管理：由 DocumentViewer 消费 wiki_pending_doc */
  const openCitationSource = useCallback((ref: SourceRef) => {
    const parsed = parseDocDatasource(ref.datasource);
    if (!parsed) {
      message.info('该来源不是文档（来自图谱或数据库）');
      return;
    }
    sessionStorage.setItem(
      'wiki_pending_doc',
      JSON.stringify({ source_id: parsed.sourceId, file: parsed.file, node_id: ref.node_id }),
    );
    navigate('/document');
  }, [navigate]);

  const openPageByTitle = (title: string) => {
    const hit = pages.find(p => p.title === title);
    if (hit) {
      void openPage(hit.page_id);
      return;
    }
    message.info(`「${title}」页面尚未生成`);
  };

  const refsByNumber = useMemo(() => {
    const map = new Map<number, SourceRef>();
    (current?.source_refs || []).forEach(ref => map.set(ref.n, ref));
    return map;
  }, [current]);

  const mdComponents = useMemo<Components>(() => ({
    a: ({ href, children }) => {
      const cite = href?.match(/^#cite-(\d+)$/);
      if (!cite) {
        return <a href={href}>{children}</a>;
      }
      const ref = refsByNumber.get(Number(cite[1]));
      if (!ref) {
        return <sup className="wiki-ref">[{cite[1]}]</sup>;
      }
      return (
        <Popover
          title={ref.title || `引用 ${ref.n}`}
          content={
            <div className="wiki-cite-card">
              <div><code>{ref.datasource}</code></div>
              {ref.node_id && <div className="wiki-cite-node">摘要节点 #{ref.node_id}</div>}
              <Button
                size="small"
                type="link"
                style={{ padding: 0, marginTop: 4 }}
                onClick={() => openCitationSource(ref)}
              >
                在文档中打开
              </Button>
            </div>
          }
        >
          <sup className="wiki-ref wiki-ref-clickable">[{ref.n}]</sup>
        </Popover>
      );
    },
  }), [refsByNumber, openCitationSource]);

  const grouped: Record<string, WikiPage[]> = {};
  for (const p of pages) {
    (grouped[p.kind] = grouped[p.kind] || []).push(p);
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 120px)' }}>
      <div style={{ width: 280, overflowY: 'auto', borderRight: '1px solid #eee', paddingRight: 8 }}>
        <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
          <Button size="small" icon={<ReloadOutlined />} loading={!!taskId}
                  onClick={() => startGenerate('all')}>生成全部</Button>
          <Button size="small" onClick={() => startGenerate('topics')}>仅主题页</Button>
          <Button size="small" onClick={() => startGenerate('entities')}>仅实体页</Button>
        </div>
        {loading && <Spin size="small" />}
        {Object.entries(grouped).map(([kind, list]) => (
          <div key={kind} style={{ marginBottom: 12 }}>
            <Tag color={KIND_COLORS[kind]}>{KIND_LABELS[kind] || kind}</Tag>
            {list.map(p => (
              <div
                key={p.page_id}
                onClick={() => openPage(p.page_id)}
                style={{
                  padding: '4px 8px', cursor: 'pointer', borderRadius: 4,
                  background: current?.page_id === p.page_id ? '#e6f4ff' : 'transparent',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  fontSize: 13,
                }}
              >
                {p.title}
                {p.status === 'draft' && <span style={{ color: '#fa8c16', marginLeft: 4 }}>草稿</span>}
              </div>
            ))}
          </div>
        ))}
        {!pages.length && !loading && (
          <p style={{ color: '#999', fontSize: 12 }}>暂无 Wiki 页面，点击「生成全部」从文档摘要创建。</p>
        )}
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {current ? (
          <div style={{ padding: '8px 16px' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
              <Tag color={KIND_COLORS[current.kind]}>{KIND_LABELS[current.kind]}</Tag>
              <span style={{ color: '#888', fontSize: 12 }}>更新于 {current.updated_at?.slice(0, 16)}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                {editing ? (
                  <>
                    <Button size="small" icon={<SaveOutlined />} onClick={savePage}>保存</Button>
                    <Button size="small" onClick={() => setEditing(false)}>取消</Button>
                  </>
                ) : (
                  <>
                    <Button size="small" icon={<EditOutlined />}
                            onClick={() => { setDraft(current.content); setEditing(true); }}>编辑</Button>
                    {current.status === 'draft' && (
                      <Button size="small" onClick={publishPage}>发布</Button>
                    )}
                    {current.kind === 'document' && current.datasource && (
                      <Button size="small" onClick={askAboutPage}>就本页提问</Button>
                    )}
                  </>
                )}
              </span>
            </div>
            {editing ? (
              <Input.TextArea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                autoSize={{ minRows: 20 }}
                style={{ fontFamily: 'monospace', fontSize: 13 }}
              />
            ) : (
              <div className="wiki-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                  {linkifyCitations(current.content)}
                </ReactMarkdown>
              </div>
            )}
            {current.links?.length > 0 && !editing && (
              <div style={{ marginTop: 16, borderTop: '1px dashed #ddd', paddingTop: 8 }}>
                <span style={{ color: '#888', fontSize: 12 }}>相关页面：</span>
                {current.links.map(l => {
                  const linked = pages.some(p => p.title === l);
                  return (
                    <Tag
                      key={l}
                      className={linked ? 'wiki-link-tag' : undefined}
                      style={{ cursor: linked ? 'pointer' : 'default', opacity: linked ? 1 : 0.5 }}
                      onClick={linked ? () => openPageByTitle(l) : undefined}
                    >
                      {l}
                    </Tag>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <p style={{ color: '#999' }}>从左侧选择一个页面。</p>
        )}
      </div>
    </div>
  );
}

export default WikiViewer;
