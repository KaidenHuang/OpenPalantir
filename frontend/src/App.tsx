import { useState, useEffect } from 'react'
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

function App() {
  const [activeTab, setActiveTab] = useState('document')

  // 记录组件挂载日志
  useEffect(() => {
    logger.info('App', 'App组件挂载')
    return () => {
      logger.info('App', 'App组件卸载')
    }
  }, [])

  // 记录tab切换日志
  const handleTabChange = (tab: string) => {
    logger.info('App', `切换到标签页: ${tab}`)
    setActiveTab(tab)
  }

  return (
    <div className="app">
      <nav className="nav">
        <button
          className={activeTab === 'document' ? 'active' : ''}
          onClick={() => handleTabChange('document')}
        >
          文档管理
        </button>
        <button
          className={activeTab === 'database' ? 'active' : ''}
          onClick={() => handleTabChange('database')}
        >
          数据库管理
        </button>
        <button
          className={activeTab === 'entity' ? 'active' : ''}
          onClick={() => handleTabChange('entity')}
        >
          实体管理
        </button>
        <button
          className={activeTab === 'graph' ? 'active' : ''}
          onClick={() => handleTabChange('graph')}
        >
          图谱可视化
        </button>
        <button
          className={activeTab === 'task' ? 'active' : ''}
          onClick={() => handleTabChange('task')}
        >
          任务管理
        </button>
        <button
          className={activeTab === 'model' ? 'active' : ''}
          onClick={() => handleTabChange('model')}
        >
          模型管理
        </button>
        <button
          className={activeTab === 'analysis' ? 'active' : ''}
          onClick={() => handleTabChange('analysis')}
        >
          分析报告
        </button>
        <button
          className={activeTab === 'decision' ? 'active' : ''}
          onClick={() => handleTabChange('decision')}
        >
          智能决策
        </button>
      </nav>
      
      <main className="main">
        {activeTab === 'document' && (
          <div className="tab-content">
            <DocumentViewer />
          </div>
        )}

        {activeTab === 'database' && (
          <div className="tab-content">
            <DatabaseManagement />
          </div>
        )}

        {activeTab === 'entity' && (
          <div className="tab-content">
            <EntityManagement />
          </div>
        )}

        {activeTab === 'graph' && (
          <div className="tab-content">
            <GraphVisualization />
          </div>
        )}

        {activeTab === 'task' && (
          <div className="tab-content">
            <TaskManagement />
          </div>
        )}

        {activeTab === 'model' && (
          <div className="tab-content">
            <ModelManagement />
          </div>
        )}

        {activeTab === 'analysis' && (
          <div className="tab-content">
            <AnalysisDashboard />
          </div>
        )}

        {activeTab === 'decision' && (
          <div className="tab-content">
            <DecisionAssistant />
          </div>
        )}
      </main>
    </div>
  )
}

export default App