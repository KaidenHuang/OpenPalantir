import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import './App.css'
import GraphVisualization from './components/GraphVisualization'
import DocumentViewer from './components/DocumentViewer'
import AnalysisDashboard from './components/AnalysisDashboard'
import EntityManagement from './components/EntityManagement'
import TaskManagement from './components/TaskManagement'
import ModelManagement from './components/ModelManagement'
import DatabaseManagement from './components/DatabaseManagement'
import DecisionAssistant from './components/DecisionAssistant'
import { logger } from './services/logger'

// 标签页配置：路径 → 组件映射
const TABS = [
  { key: 'document', label: '文档管理', path: '/document' },
  { key: 'database', label: '数据库管理', path: '/database' },
  { key: 'entity', label: '实体管理', path: '/entity' },
  { key: 'graph', label: '图谱可视化', path: '/graph' },
  { key: 'task', label: '任务管理', path: '/task' },
  { key: 'model', label: '模型管理', path: '/model' },
  { key: 'analysis', label: '分析报告', path: '/analysis' },
  { key: 'decision', label: '智能决策', path: '/decision' },
] as const

function AppContent() {
  const navigate = useNavigate()
  const location = useLocation()

  // 从 URL 路径推导当前激活标签
  const activeTab = TABS.find(t => location.pathname.startsWith(t.path))?.key || 'document'

  useEffect(() => {
    logger.info('App', 'App组件挂载')
    return () => {
      logger.info('App', 'App组件卸载')
    }
  }, [])

  const handleTabChange = (tab: typeof TABS[number]) => {
    logger.info('App', `切换到标签页: ${tab.key}`)
    navigate(tab.path)
  }

  return (
    <div className="app">
      <nav className="nav">
        {TABS.map(tab => (
          <button
            key={tab.key}
            className={activeTab === tab.key ? 'active' : ''}
            onClick={() => handleTabChange(tab)}
          >
            {tab.label}
          </button>
        ))}
        <img src="/openpalantir.svg" alt="OpenPalantir" className="nav-logo" />
      </nav>

      <main className="main">
        <Routes>
          <Route path="/document" element={<div className="tab-content"><DocumentViewer /></div>} />
          <Route path="/database" element={<div className="tab-content"><DatabaseManagement /></div>} />
          <Route path="/entity" element={<div className="tab-content"><EntityManagement /></div>} />
          <Route path="/graph" element={<div className="tab-content"><GraphVisualization /></div>} />
          <Route path="/task" element={<div className="tab-content"><TaskManagement /></div>} />
          <Route path="/model" element={<div className="tab-content"><ModelManagement /></div>} />
          <Route path="/analysis" element={<div className="tab-content"><AnalysisDashboard /></div>} />
          <Route path="/decision" element={<div className="tab-content"><DecisionAssistant /></div>} />
          <Route path="*" element={<Navigate to="/document" replace />} />
        </Routes>
      </main>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  )
}

export default App
