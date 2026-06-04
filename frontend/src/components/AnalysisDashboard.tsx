import React, { useState } from 'react';
import axios from 'axios';
import { API_CONFIG } from '../config/apiConfig';
import './AnalysisDashboard.css';

interface AnalysisResult {
  type: string;
  data: any;
}

const AnalysisDashboard: React.FC = () => {
  const [activeAnalysis, setActiveAnalysis] = useState('path');
  const [analysisResults, setAnalysisResults] = useState<AnalysisResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // 路径分析参数
  const [sourceEntity, setSourceEntity] = useState('');
  const [targetEntity, setTargetEntity] = useState('');
  const [pathK, setPathK] = useState(1);
  const [pathWeighted, setPathWeighted] = useState(false);
  
  // 中心性分析参数
  const [centralityTypes, setCentralityTypes] = useState<string[]>(['degree', 'betweenness', 'closeness', 'pagerank', 'eigenvector']);
  
  // 趋势分析参数
  const [timeRange, setTimeRange] = useState('last_6_months');
  const [trendMetrics, setTrendMetrics] = useState<string[]>(['entity_count', 'relationship_count', 'community_count', 'centrality_trend']);
  
  // 报告参数
  const [reportFormat, setReportFormat] = useState('html');

  // 执行路径分析
  const runPathAnalysis = async () => {
    if (!sourceEntity || !targetEntity) {
      setError('请输入源实体和目标实体');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await axios.post(API_CONFIG.endpoints.analysis.path, {
        source_entity: sourceEntity,
        target_entity: targetEntity,
        k: pathK,
        weighted: pathWeighted
      });
      
      setAnalysisResults([{
        type: 'path',
        data: response.data
      }]);
    } catch (error: any) {
      setError(`路径分析失败: ${error.message || '未知错误'}`);
      console.error('Error running path analysis:', error);
    } finally {
      setLoading(false);
    }
  };

  // 执行社区分析
  const runCommunityAnalysis = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await axios.post(API_CONFIG.endpoints.analysis.community);
      
      setAnalysisResults([{
        type: 'community',
        data: response.data
      }]);
    } catch (error: any) {
      setError(`社区分析失败: ${error.message || '未知错误'}`);
      console.error('Error running community analysis:', error);
    } finally {
      setLoading(false);
    }
  };

  // 执行中心性分析
  const runCentralityAnalysis = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await axios.post(API_CONFIG.endpoints.analysis.centrality, {
        centrality_types: centralityTypes
      });
      
      setAnalysisResults([{
        type: 'centrality',
        data: response.data
      }]);
    } catch (error: any) {
      setError(`中心性分析失败: ${error.message || '未知错误'}`);
      console.error('Error running centrality analysis:', error);
    } finally {
      setLoading(false);
    }
  };

  // 执行趋势分析
  const runTrendAnalysis = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await axios.post(API_CONFIG.endpoints.analysis.trend, {
        time_range: timeRange,
        metrics: trendMetrics
      });
      
      setAnalysisResults([{
        type: 'trend',
        data: response.data
      }]);
    } catch (error: any) {
      setError(`趋势分析失败: ${error.message || '未知错误'}`);
      console.error('Error running trend analysis:', error);
    } finally {
      setLoading(false);
    }
  };

  // 生成分析报告
  const generateReport = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await axios.post(API_CONFIG.endpoints.analysis.report, {
        analysis_type: activeAnalysis,
        format: reportFormat
      });
      
      setAnalysisResults([{
        type: 'report',
        data: response.data
      }]);
    } catch (error: any) {
      setError(`报告生成失败: ${error.message || '未知错误'}`);
      console.error('Error generating report:', error);
    } finally {
      setLoading(false);
    }
  };

  // 下载报告
  const downloadReport = (data: any) => {
    if (!data || !data.report) return;
    
    const format = data.format || 'html';
    const mimeTypes = {
      html: 'text/html',
      markdown: 'text/markdown'
    };
    
    const blob = new Blob([data.report], { type: mimeTypes[format as keyof typeof mimeTypes] || 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `analysis-report.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // 渲染路径分析结果
  const renderPathAnalysis = (data: any) => {
    if (!data || !data.paths || data.paths.length === 0) {
      return <div className="analysis-result">未找到路径</div>;
    }

    return (
      <div className="analysis-result">
        <h4>路径分析结果</h4>
        <p>源实体: {data.source}</p>
        <p>目标实体: {data.target}</p>
        <p>找到路径数: {data.total_paths}</p>
        <div className="paths">
          {data.paths.map((path: string[], index: number) => (
            <div key={index} className="path">
              <p>路径 {index + 1}: {path.join(' → ')}</p>
              <p>长度: {data.path_lengths[index]}</p>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // 渲染社区分析结果
  const renderCommunityAnalysis = (data: any) => {
    if (!data || !data.communities || data.communities.length === 0) {
      return <div className="analysis-result">未检测到社区</div>;
    }

    return (
      <div className="analysis-result">
        <h4>社区分析结果</h4>
        <p>总社区数: {data.total_communities}</p>
        {data.largest_community && (
          <div className="largest-community">
            <h5>最大社区</h5>
            <p>社区ID: {data.largest_community.community_id}</p>
            <p>节点数量: {data.largest_community.size}</p>
            <p>密度: {data.largest_community.density.toFixed(4)}</p>
            <p>边数: {data.largest_community.edge_count}</p>
            {data.largest_community.key_entities && data.largest_community.key_entities.length > 0 && (
              <p>关键实体: {data.largest_community.key_entities.map((entity: any) => entity.node).join(', ')}</p>
            )}
          </div>
        )}
        <div className="communities">
          {data.communities.slice(0, 5).map((community: any, index: number) => (
            <div key={index} className="community">
              <h5>社区 {community.community_id} (大小: {community.size})</h5>
              <p>密度: {community.density.toFixed(4)}</p>
              {community.key_entities && community.key_entities.length > 0 && (
                <p>关键实体: {community.key_entities.map((entity: any) => entity.node).join(', ')}</p>
              )}
            </div>
          ))}
        </div>
        {data.communities.length > 5 && (
          <p className="more-communities">... 还有 {data.communities.length - 5} 个社区</p>
        )}
      </div>
    );
  };

  // 渲染中心性分析结果
  const renderCentralityAnalysis = (data: any) => {
    if (!data || !data.top_nodes || data.top_nodes.length === 0) {
      return <div className="analysis-result">未找到中心节点</div>;
    }

    return (
      <div className="analysis-result">
        <h4>中心性分析结果</h4>
        {data.top_nodes_by_type && Object.entries(data.top_nodes_by_type).map(([type, nodes]) => (
          <div key={type} className="centrality-type">
            <h5>{getCentralityTypeName(type)}</h5>
            <div className="centrality-nodes">
              {(nodes as any[]).slice(0, 5).map((node: any, index: number) => (
                <div key={index} className="centrality-node">
                  <p>节点: {node.node}</p>
                  <p>值: {(node[`${type}_centrality`] || 0).toFixed(4)}</p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  // 渲染趋势分析结果
  const renderTrendAnalysis = (data: any) => {
    if (!data || !data.trends || data.trends.length === 0) {
      return <div className="analysis-result">未找到趋势数据</div>;
    }

    return (
      <div className="analysis-result">
        <h4>趋势分析结果</h4>
        <p>时间范围: {data.time_range}</p>
        <div className="trends">
          {data.trends.map((trend: any, index: number) => (
            <div key={index} className="trend">
              <h5>{trend.label || trend.metric}</h5>
              <div className="trend-data">
                {trend.labels && trend.values && trend.labels.map((label: string, i: number) => (
                  <div key={i} className="trend-point">
                    <span>{label}: </span>
                    <span>{trend.values[i]}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // 渲染报告结果
  const renderReport = (data: any) => {
    if (!data || !data.report) {
      return <div className="analysis-result">报告生成失败</div>;
    }

    return (
      <div className="analysis-result">
        <div className="report-header">
          <h4>分析报告</h4>
          <button 
            className="download-button"
            onClick={() => downloadReport(data)}
          >
            下载报告
          </button>
        </div>
        {data.format === 'html' ? (
          <div className="html-report" dangerouslySetInnerHTML={{ __html: data.report }} />
        ) : (
          <pre className="markdown-report">{data.report}</pre>
        )}
        {data.data && (
          <div className="report-data">
            <h5>报告数据</h5>
            <pre>{JSON.stringify(data.data, null, 2)}</pre>
          </div>
        )}
      </div>
    );
  };

  // 渲染分析结果
  const renderAnalysisResult = () => {
    if (analysisResults.length === 0) {
      return <div className="no-analysis">请选择分析类型并执行分析</div>;
    }

    const result = analysisResults[0];
    switch (result.type) {
      case 'path':
        return renderPathAnalysis(result.data);
      case 'community':
        return renderCommunityAnalysis(result.data);
      case 'centrality':
        return renderCentralityAnalysis(result.data);
      case 'trend':
        return renderTrendAnalysis(result.data);
      case 'report':
        return renderReport(result.data);
      default:
        return <div className="analysis-result">未知分析类型</div>;
    }
  };

  // 获取中心性类型的中文名称
  const getCentralityTypeName = (type: string): string => {
    const typeMap: Record<string, string> = {
      degree: '度中心性',
      betweenness: '介数中心性',
      closeness: '接近中心性',
      pagerank: 'PageRank中心性',
      eigenvector: '特征向量中心性'
    };
    return typeMap[type] || type;
  };

  return (
    <div className="analysis-dashboard">
      <div className="analysis-controls">
        <div className="analysis-tabs">
          <button 
            className={activeAnalysis === 'path' ? 'active' : ''}
            onClick={() => setActiveAnalysis('path')}
          >
            路径分析
          </button>
          <button 
            className={activeAnalysis === 'community' ? 'active' : ''}
            onClick={() => setActiveAnalysis('community')}
          >
            社区分析
          </button>
          <button 
            className={activeAnalysis === 'centrality' ? 'active' : ''}
            onClick={() => setActiveAnalysis('centrality')}
          >
            中心性分析
          </button>
          <button 
            className={activeAnalysis === 'trend' ? 'active' : ''}
            onClick={() => setActiveAnalysis('trend')}
          >
            趋势分析
          </button>
        </div>

        <div className="analysis-inputs">
          {activeAnalysis === 'path' && (
            <div className="path-inputs">
              <input
                type="text"
                placeholder="源实体"
                value={sourceEntity}
                onChange={(e) => setSourceEntity(e.target.value)}
              />
              <input
                type="text"
                placeholder="目标实体"
                value={targetEntity}
                onChange={(e) => setTargetEntity(e.target.value)}
              />
              <input
                type="number"
                placeholder="路径数量"
                value={pathK}
                onChange={(e) => setPathK(parseInt(e.target.value) || 1)}
                min="1"
                max="10"
              />
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={pathWeighted}
                  onChange={(e) => setPathWeighted(e.target.checked)}
                />
                加权路径
              </label>
              <button onClick={runPathAnalysis} disabled={loading}>
                {loading ? '分析中...' : '执行分析'}
              </button>
            </div>
          )}

          {activeAnalysis === 'community' && (
            <button onClick={runCommunityAnalysis} disabled={loading}>
              {loading ? '分析中...' : '执行分析'}
            </button>
          )}

          {activeAnalysis === 'centrality' && (
            <div className="centrality-inputs">
              <div className="centrality-types">
                {['degree', 'betweenness', 'closeness', 'pagerank', 'eigenvector'].map((type) => (
                  <label key={type} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={centralityTypes.includes(type)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setCentralityTypes([...centralityTypes, type]);
                        } else {
                          setCentralityTypes(centralityTypes.filter(t => t !== type));
                        }
                      }}
                    />
                    {getCentralityTypeName(type)}
                  </label>
                ))}
              </div>
              <button onClick={runCentralityAnalysis} disabled={loading || centralityTypes.length === 0}>
                {loading ? '分析中...' : '执行分析'}
              </button>
            </div>
          )}

          {activeAnalysis === 'trend' && (
            <div className="trend-inputs">
              <select
                value={timeRange}
                onChange={(e) => setTimeRange(e.target.value)}
              >
                <option value="last_7_days">最近7天</option>
                <option value="last_30_days">最近30天</option>
                <option value="last_3_months">最近3个月</option>
                <option value="last_12_months">最近12个月</option>
              </select>
              <div className="trend-metrics">
                {['entity_count', 'relationship_count', 'community_count', 'centrality_trend'].map((metric) => (
                  <label key={metric} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={trendMetrics.includes(metric)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setTrendMetrics([...trendMetrics, metric]);
                        } else {
                          setTrendMetrics(trendMetrics.filter(m => m !== metric));
                        }
                      }}
                    />
                    {metric === 'entity_count' ? '实体数量' :
                     metric === 'relationship_count' ? '关系数量' :
                     metric === 'community_count' ? '社区数量' : '中心性趋势'}
                  </label>
                ))}
              </div>
              <button onClick={runTrendAnalysis} disabled={loading || trendMetrics.length === 0}>
                {loading ? '分析中...' : '执行分析'}
              </button>
            </div>
          )}

          <div className="report-options">
            <select
              value={reportFormat}
              onChange={(e) => setReportFormat(e.target.value)}
            >
              <option value="html">HTML格式</option>
              <option value="markdown">Markdown格式</option>
            </select>
            <button onClick={generateReport} disabled={loading}>
              {loading ? '生成中...' : '生成报告'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="analysis-error">
          <p>{error}</p>
          <button onClick={() => setError(null)}>关闭</button>
        </div>
      )}

      <div className="analysis-results">
        {loading ? (
          <div className="analysis-loading">
            <div className="loading-spinner"></div>
            <p>分析中...</p>
          </div>
        ) : (
          renderAnalysisResult()
        )}
      </div>
    </div>
  );
};

export default AnalysisDashboard;