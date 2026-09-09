import { useEffect, useRef, useState } from 'react';
import API_CONFIG from '../config/apiConfig';
import { useAbortController } from '../hooks/useAbortController';

interface WorkOrder {
  title: string;
  priority: string;
  owner_role: string;
  steps: string[];
  acceptance_criteria: string[];
}

interface KeyIssue {
  issue: string;
  severity: string;
  evidence: string[];
}

interface Option {
  name: string;
  description: string;
  pros: string[];
  cons: string[];
  risks: string[];
}

interface DecisionAnswer {
  summary: string;
  situation_analysis: string;
  key_issues: KeyIssue[];
  options: Option[];
  recommendation: string | { option: string; reason?: string } | null;
  work_orders: WorkOrder[];
  confidence?: number;
  confidence_reason?: string;
}

interface EvidenceCitation {
  citation: string;
  source_type: string;
  source_id: string;
}

interface EvidenceItem {
  evidence_id: string;
  source_type: string;
  source_name: string;
  summary: string;
  citation: string;
  relevance_score: number;
}

interface ToolTraceStep {
  step: number;
  tool_name: string;
  params: Record<string, unknown>;
  result_summary: string;
  success: boolean;
  execution_time_ms: number;
}

interface AnalyzedQuery {
  domain: string;
  intent: string;
  entities: string[];
  constraints: Record<string, unknown>;
  sub_questions: string[];
  reasoning: string;
}

interface DecisionResponse {
  domain: string;
  intent: string;
  session_id: string;
  analyzed_query: AnalyzedQuery;
  evidence: EvidenceItem[];
  evidence_citations: EvidenceCitation[];
  answer: DecisionAnswer;
  tool_trace?: ToolTraceStep[];
  decision_mode?: string;
  response_type?: string;  // "normal" | "simple" | "no_data"
}

interface ChatMessage {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  result?: DecisionResponse;
  loading?: boolean;
}

const STORAGE_KEY = 'decision_session_id';

const WELCOME_MESSAGE: ChatMessage = {
  id: 'welcome',
  type: 'assistant',
  content: '您好！我是智能问答决策助手，请问有什么可以帮助您的？',
  timestamp: new Date(),
};

function genSessionId(): string {
  return 'sess_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function prioritySeverity(p: string): 'high' | 'medium' | 'low' {
  if (p === 'P0') return 'high';
  if (p === 'P1') return 'medium';
  return 'low';
}

function severityBadge(severity: string) {
  const colors: Record<string, string> = {
    high: '#e74c3c', medium: '#f39c12', low: '#27ae60',
  };
  return {
    backgroundColor: colors[severity] || '#999', color: '#fff',
    padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: 600,
  };
}

function DecisionAssistant() {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEY) || '';
  });
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { getLatestSignal } = useAbortController();

  const toggleSection = (key: string) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const loading = messages.some(m => m.loading);

  // Auto scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load session on mount
  useEffect(() => {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (existing) {
      setSessionId(existing);
      fetchSession(existing);
    } else {
      const newId = genSessionId();
      localStorage.setItem(STORAGE_KEY, newId);
      setSessionId(newId);
      setMessages([WELCOME_MESSAGE]);
    }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchSession = async (sid: string) => {
    try {
      const signal = getLatestSignal('session');
      const res = await fetch(`${API_CONFIG.baseUrl}/api/decision/session/${sid}`, { signal });
      if (!res.ok) {
        setMessages([WELCOME_MESSAGE]);
        return;
      }
      const session = await res.json();
      const loaded: ChatMessage[] = [];
      if (session.turns) {
        for (const turn of session.turns) {
          loaded.push({
            id: turn.turn_id + '-q', type: 'user',
            content: turn.question, timestamp: new Date(turn.timestamp),
          });
          loaded.push({
            id: turn.turn_id + '-a', type: 'assistant',
            content: turn.answer?.situation_analysis || turn.answer?.summary || '',
            timestamp: new Date(turn.timestamp),
            result: {
              domain: session.domain,
              intent: turn.analyzed_query?.intent || '',
              session_id: sid,
              analyzed_query: turn.analyzed_query,
              evidence: turn.evidence || [],
              evidence_citations: turn.evidence_citations || [],
              answer: turn.answer,
              response_type: turn.response_type || 'normal',
            },
          });
        }
      }
      setMessages(loaded.length > 0 ? loaded : [WELCOME_MESSAGE]);
    } catch (err) {
      if ((err as { name?: string }).name === 'AbortError') return;
      setMessages([WELCOME_MESSAGE]);
    }
  };

  const startNewSession = () => {
    const newId = genSessionId();
    localStorage.setItem(STORAGE_KEY, newId);
    setSessionId(newId);
    setMessages([WELCOME_MESSAGE]);
  };

  const askDecision = async () => {
    if (!question.trim() || loading) return;

    const q = question;
    setQuestion('');

    const userMsg: ChatMessage = {
      id: Date.now().toString(), type: 'user',
      content: q, timestamp: new Date(),
    };
    const loadingMsg: ChatMessage = {
      id: (Date.now() + 1).toString(), type: 'assistant',
      content: '', timestamp: new Date(), loading: true,
    };
    setMessages(prev => [...prev, userMsg, loadingMsg]);

    const signal = getLatestSignal('ask');
    const timeoutId = setTimeout(() => {
      // 超时由外部 AbortController 处理
    }, 120000);
    try {
      const response = await fetch(API_CONFIG.endpoints.decision.ask, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, domain: 'workforce', session_id: sessionId }),
        signal,
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.detail || '请求失败');
      }

      const data: DecisionResponse = await response.json();
      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem(STORAGE_KEY, data.session_id);
      }

      setMessages(prev => prev.map(m =>
        m.id === loadingMsg.id
          ? {
              id: loadingMsg.id, type: 'assistant',
              content: data.answer.situation_analysis || data.answer.summary || (typeof data.answer.recommendation === 'string' ? data.answer.recommendation : '') || '',
              timestamp: new Date(), result: data,
            }
          : m
      ));
    } catch (err: unknown) {
      const msg = err instanceof Error
        ? (err.name === 'AbortError' ? '请求超时，请重试' : err.message)
        : '调用失败';
      setMessages(prev => {
        const filtered = prev.filter(m => m.id !== loadingMsg.id);
        return [...filtered, {
          id: (Date.now() + 1).toString(), type: 'assistant',
          content: `抱歉，发生错误：${msg}`,
          timestamp: new Date(),
        }];
      });
    } finally {
      clearTimeout(timeoutId);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      askDecision();
    }
  };

  return (
    <div className="decision-assistant">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>智能问答决策</h2>
        <button className="btn btn-secondary" onClick={startNewSession} style={{ fontSize: 12, padding: '4px 12px' }}>
          新建会话
        </button>
      </div>

      <div className="chat-container">
        <div className="chat-messages">
          {messages.map((msg) => (
            <div key={msg.id} className={`chat-message ${msg.type}`}>
              <div className="chat-message-content">
                {msg.loading ? (
                  <div className="loading-indicator">思考中...</div>
                ) : (
                  <>
                    {msg.content && <p style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</p>}
                    {msg.result && (() => {
                      const r = msg.result!;
                      const hasContent =
                        r.response_type === 'no_data' ||
                        r.answer?.key_issues?.length > 0 ||
                        r.answer?.options?.length > 0 ||
                        (typeof r.answer?.recommendation === 'object' && r.answer.recommendation !== null && !!r.answer.recommendation.option) ||
                        (typeof r.answer?.recommendation === 'string' && !!r.answer.recommendation) ||
                        r.answer?.work_orders?.length > 0 ||
                        r.evidence_citations?.length > 0 ||
                        r.evidence?.length > 0 ||
                        (r.tool_trace && r.tool_trace.length > 0);
                      if (!hasContent) return null;
                      return (
                      <div className="decision-result">
                        {r.response_type !== 'simple' && (
                          <>

                            {r.answer.key_issues?.length > 0 && (
                              <div style={{ marginBottom: 8 }}>
                                <h4>关键问题</h4>
                                {r.answer.key_issues.map((ki, idx) => (
                                  <div key={idx} className="decision-card" style={{ marginBottom: 6 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                      <span style={severityBadge(ki.severity)}>{ki.severity}</span>
                                      <strong>{ki.issue}</strong>
                                    </div>
                                    {ki.evidence?.length > 0 && (
                                      <div style={{ fontSize: 12, color: '#666' }}>
                                        证据：{ki.evidence.join(', ')}
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            {r.answer.options?.length > 0 && (
                              <div style={{ marginBottom: 8 }}>
                                <h4>可选方案</h4>
                                {r.answer.options.map((opt, idx) => (
                                  <div key={idx} className="decision-card" style={{ marginBottom: 8 }}>
                                    <strong>{opt.name}</strong>
                                    <p style={{ margin: '4px 0', fontSize: 12, color: '#555' }}>{opt.description}</p>
                                    {opt.pros?.length > 0 && (
                                      <div style={{ fontSize: 12, color: '#27ae60' }}>优势：{opt.pros.join('、')}</div>
                                    )}
                                    {opt.cons?.length > 0 && (
                                      <div style={{ fontSize: 12, color: '#e74c3c' }}>劣势：{opt.cons.join('、')}</div>
                                    )}
                                    {opt.risks?.length > 0 && (
                                      <div style={{ fontSize: 12, color: '#f39c12' }}>风险：{opt.risks.join('、')}</div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            {r.answer.recommendation &&
                              typeof r.answer.recommendation === 'object' &&
                              r.answer.recommendation.option && (
                              <div style={{ marginBottom: 8, padding: '8px 10px', background: '#e8f5e9', borderRadius: 6 }}>
                                <strong>推荐方案：</strong>
                                {r.answer.recommendation.option}
                                {r.answer.recommendation.reason && (
                                  <span style={{ color: '#555', marginLeft: 8, fontSize: 12 }}>
                                    — {r.answer.recommendation.reason}
                                  </span>
                                )}
                              </div>
                            )}

                            {r.answer.work_orders?.length > 0 && (
                              <div style={{ marginBottom: 8 }}>
                                <h4>行动工单</h4>
                                <div className="decision-workorders">
                                  {r.answer.work_orders.map((wo, idx) => (
                                    <div className="decision-card" key={`${wo.title}-${idx}`}>
                                      <div><strong>{wo.title}</strong></div>
                                      <div style={{ fontSize: 12, marginTop: 4 }}>
                                        <span style={{ ...severityBadge(prioritySeverity(wo.priority)), marginRight: 6 }}>
                                          {wo.priority}
                                        </span>
                                        <span>{wo.owner_role}</span>
                                      </div>
                                      {wo.steps?.length > 0 && (
                                        <div style={{ marginTop: 6, fontSize: 12 }}>
                                          <strong>步骤：</strong>
                                          <ol style={{ margin: '4px 0', paddingLeft: 18 }}>
                                            {wo.steps.map((s, si) => <li key={si}>{s}</li>)}
                                          </ol>
                                        </div>
                                      )}
                                      {wo.acceptance_criteria?.length > 0 && (
                                        <div style={{ marginTop: 4, fontSize: 12 }}>
                                          <strong>验收标准：</strong>
                                          <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                                            {wo.acceptance_criteria.map((ac, ai) => <li key={ai}>{ac}</li>)}
                                          </ul>
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </>
                        )}

                        {/* 无数据响应：额外提示横幅 */}
                        {r.response_type === 'no_data' && (
                          <div style={{ marginTop: 8, padding: '8px 10px', background: '#fff3e0', borderRadius: 6, fontSize: 12 }}>
                            <strong>提示：</strong>未找到相关数据，请尝试调整查询条件或确认数据源已接入。
                          </div>
                        )}

                        {/* 证据引用和证据详情：仅 normal 响应展示 */}
                        {r.response_type !== 'simple' && r.response_type !== 'no_data' && (
                          <>
                            {r.evidence_citations?.length > 0 && (
                              <div style={{ marginTop: 8 }}>
                                <h4
                                  onClick={() => toggleSection(`citations-${msg.id}`)}
                                  style={{ cursor: 'pointer', userSelect: 'none', fontSize: 13, margin: 0 }}
                                >
                                  {expandedSections[`citations-${msg.id}`] ? '▼ ' : '▶ '}证据引用
                                </h4>
                                {expandedSections[`citations-${msg.id}`] && (
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                                    {r.evidence_citations.map((cit, idx) => (
                                      <span key={idx} style={{
                                        fontSize: 11, padding: '2px 8px', background: '#eef',
                                        borderRadius: 12, color: '#446',
                                      }}>
                                        {cit.citation}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}

                            {r.evidence?.length > 0 && (
                              <div style={{ marginTop: 8 }}>
                                <h4
                                  onClick={() => toggleSection(`details-${msg.id}`)}
                                  style={{ cursor: 'pointer', userSelect: 'none', fontSize: 13, margin: 0 }}
                                >
                                  {expandedSections[`details-${msg.id}`] ? '▼ ' : '▶ '}证据详情
                                </h4>
                                {expandedSections[`details-${msg.id}`] && (
                                  <ul style={{ marginTop: 6, marginBottom: 0 }}>
                                    {r.evidence.map((e) => (
                                      <li key={e.evidence_id} style={{ fontSize: 12, marginBottom: 4 }}>
                                        <span style={{ color: '#888' }}>[{e.source_type}]</span>{' '}
                                        {e.citation && <span style={{ color: '#446', fontWeight: 600 }}>{e.citation}</span>}
                                        <span style={{ color: '#666' }}> — {e.summary?.slice(0, 120)}</span>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            )}
                          </>
                        )}

                        {/* 多 Agent 审核标记 */}
                        {(() => {
                          const reason = r.answer?.confidence_reason || '';
                          const hasCritic = reason.includes('Critic');
                          if (!hasCritic) return null;
                          return (
                            <div style={{
                              marginTop: 8, padding: '6px 10px',
                              background: '#fff8e1', borderRadius: 6,
                              borderLeft: '3px solid #f39c12', fontSize: 12,
                            }}>
                              <strong>🔍 多 Agent 审核</strong>
                              <span style={{ color: '#666', marginLeft: 8 }}>
                                {reason.split('Critic')[1]?.replace(/^[：:;\s]*/, '') || 'Critic 已审核'}
                              </span>
                            </div>
                          );
                        })()}

                        {r.tool_trace && r.tool_trace.length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            <h4
                              onClick={() => toggleSection(`tool-trace-${msg.id}`)}
                              style={{ cursor: 'pointer', userSelect: 'none', fontSize: 13, margin: 0 }}
                            >
                              {expandedSections[`tool-trace-${msg.id}`] ? '▼ ' : '▶ '}
                              工具调用链 ({r.tool_trace.length} 步)
                            </h4>
                            {expandedSections[`tool-trace-${msg.id}`] && (
                              <div style={{ marginTop: 6 }}>
                                {r.tool_trace.map((trace, idx) => (
                                  <div key={idx} style={{
                                    marginBottom: 6, padding: '6px 10px',
                                    background: trace.success ? '#f0f7f0' : '#fff0f0',
                                    borderRadius: 6,
                                    borderLeft: `3px solid ${trace.success ? '#27ae60' : '#e74c3c'}`,
                                    fontSize: 12,
                                  }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                      <strong>Step {trace.step}: {trace.tool_name}</strong>
                                      <span style={{ color: '#888', fontSize: 11 }}>
                                        {trace.execution_time_ms.toFixed(0)}ms
                                      </span>
                                    </div>
                                    <div style={{ color: '#666', marginTop: 2 }}>
                                      参数: {JSON.stringify(trace.params)}
                                    </div>
                                    <div style={{ color: trace.success ? '#333' : '#e74c3c', marginTop: 2 }}>
                                      结果: {trace.result_summary}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      );
                    })()}
                  </>
                )}
              </div>
              <div className="chat-message-time">
                {msg.timestamp.toLocaleString('zh-CN')}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input-container">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="输入您的问题，按 Enter 发送..."
            rows={3}
            disabled={loading}
          />
          <button className="btn btn-primary" onClick={askDecision} disabled={loading || !question.trim()}>
            {loading ? '分析中...' : '发送'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default DecisionAssistant;