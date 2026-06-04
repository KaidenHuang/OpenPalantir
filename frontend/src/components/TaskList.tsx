import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { logger } from '../services/logger';
import { API_CONFIG } from '../config/apiConfig';

interface Task {
  task_id: string;
  task_type: string;
  status: string;
  progress: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

const TaskList: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [stoppingTaskId, setStoppingTaskId] = useState<string | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [confirmDialogType, setConfirmDialogType] = useState<'delete' | 'stop'>('delete');

  useEffect(() => {
    logger.info('TaskList', '任务列表组件挂载');
    fetchTasks();
    return () => {
      logger.info('TaskList', '任务列表组件卸载');
    };
  }, []);

  const fetchTasks = async () => {
    try {
      logger.info('TaskList', '开始获取任务列表');
      setLoading(true);
      const response = await axios.get(API_CONFIG.endpoints.task.list);
      console.log('任务列表原始数据:', response.data);
      // 按创建时间降序排序
      const sortedTasks = response.data.tasks.sort((a: Task, b: Task) => 
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
      console.log('排序后的任务数据:', sortedTasks);
      setTasks(sortedTasks);
      setError(null);
      logger.info('TaskList', `任务列表获取成功，共${response.data.tasks.length}个任务`);
    } catch (err) {
      logger.error('TaskList', '获取任务列表失败', err);
      setError('Failed to fetch tasks');
      console.error(err);
    } finally {
      setLoading(false);
      logger.info('TaskList', '任务列表获取完成');
    }
  };

  const getTaskTypeLabel = (type: string): string => {
    switch (type) {
      case 'relationship_extraction':
        return '关系提取';
      case 'document_upload':
        return '文档上传';
      case 'database_schema_import':
        return '数据库Schema导入';
      case 'database_schema_analyze':
        return '数据库Schema分析';
      default:
        return type;
    }
  };

  const getStatusClass = (status: string): string => {
    switch (status) {
      case 'pending':
        return 'status-pending';
      case 'running':
        return 'status-running';
      case 'completed':
        return 'status-completed';
      case 'failed':
        return 'status-failed';
      case 'stopped':
        return 'status-stopped';
      default:
        return '';
    }
  };

  const handleDeleteClick = (taskId: string) => {
    setDeletingTaskId(taskId);
    setConfirmDialogType('delete');
    setShowConfirmDialog(true);
  };

  const handleStopClick = (taskId: string) => {
    setStoppingTaskId(taskId);
    setConfirmDialogType('stop');
    setShowConfirmDialog(true);
  };

  const cancelAction = () => {
    setDeletingTaskId(null);
    setStoppingTaskId(null);
    setShowConfirmDialog(false);
  };

  const confirmAction = async () => {
    if (confirmDialogType === 'delete') {
      if (!deletingTaskId) return;
      
      try {
        logger.info('TaskList', `开始删除任务: ${deletingTaskId}`);
        await axios.delete(API_CONFIG.endpoints.task.delete(deletingTaskId));
        logger.info('TaskList', `任务删除成功: ${deletingTaskId}`);
        // 刷新任务列表
        fetchTasks();
      } catch (err) {
        logger.error('TaskList', '删除任务失败', err);
        setError('Failed to delete task');
        console.error(err);
      } finally {
        setDeletingTaskId(null);
        setShowConfirmDialog(false);
      }
    } else if (confirmDialogType === 'stop') {
      if (!stoppingTaskId) return;
      
      try {
        logger.info('TaskList', `开始停止任务: ${stoppingTaskId}`);
        await axios.post(API_CONFIG.endpoints.task.stop(stoppingTaskId));
        logger.info('TaskList', `任务停止成功: ${stoppingTaskId}`);
        // 刷新任务列表
        fetchTasks();
      } catch (err) {
        logger.error('TaskList', '停止任务失败', err);
        setError('Failed to stop task');
        console.error(err);
      } finally {
        setStoppingTaskId(null);
        setShowConfirmDialog(false);
      }
    }
  };

  return (
    <div className="task-list">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h3>任务列表</h3>
        <Button icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
      </div>
      {loading ? (
        <div className="loading">加载中...</div>
      ) : error ? (
        <div className="error">{error}</div>
      ) : (
        <div className="task-list-container">
          {tasks.length === 0 ? (
            <div className="no-tasks">暂无任务</div>
          ) : (
            <table className="task-table">
              <thead>
                <tr>
                  <th>任务 ID</th>
                  <th>文档名称</th>
                  <th>任务类型</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.task_id}>
                    <td>{task.task_id}</td>
                    <td>{task.document_name || '-'}</td>
                    <td>{getTaskTypeLabel(task.task_type)}</td>
                    <td>
                      <span className={`status-badge ${getStatusClass(task.status)}`}>
                        {task.status === 'pending' && '待处理'}
                        {task.status === 'running' && '运行中'}
                        {task.status === 'completed' && '已完成'}
                        {task.status === 'failed' && '失败'}
                        {task.status === 'stopped' && '已停止'}
                      </span>
                    </td>
                    <td>
                      {task.status === 'running' && (
                        <div className="progress-container">
                          <div 
                            className="progress-bar" 
                            style={{ width: `${task.progress}%` }}
                          ></div>
                          <span className="progress-text">{task.progress}%</span>
                        </div>
                      )}
                      {task.status !== 'running' && <span>-</span>}
                    </td>
                    <td>{new Date(task.created_at).toLocaleString()}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '5px' }}>
                        {/* 显示停止按钮的条件 */}
                        {task.status === 'pending' || task.status === 'running' ? (
                          <button
                            className="btn btn-warning"
                            onClick={() => handleStopClick(task.task_id)}
                            style={{ 
                              padding: '4px 10px', 
                              fontSize: '12px',
                              backgroundColor: '#ffc107',
                              color: '#333',
                              border: 'none',
                              borderRadius: '3px',
                              cursor: 'pointer'
                            }}
                          >
                            停止
                          </button>
                        ) : null}
                        <button
                          className="btn btn-danger"
                          onClick={() => handleDeleteClick(task.task_id)}
                          disabled={task.status === 'running'}
                          style={{ 
                            padding: '4px 10px', 
                            fontSize: '12px',
                            backgroundColor: task.status === 'running' ? '#ccc' : '#dc3545',
                            color: '#fff',
                            border: 'none',
                            borderRadius: '3px',
                            cursor: task.status === 'running' ? 'not-allowed' : 'pointer'
                          }}
                        >
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 删除确认对话框 */}
      {showConfirmDialog && (
        <div 
          className="confirm-dialog-overlay"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 1000
          }}
        >
          <div 
            className="confirm-dialog"
            style={{
              backgroundColor: '#fff',
              padding: '20px',
              borderRadius: '8px',
              boxShadow: '0 2px 10px rgba(0, 0, 0, 0.1)',
              maxWidth: '400px',
              width: '90%'
            }}
          >
            <h4 style={{ margin: '0 0 15px 0', fontSize: '16px' }}>
              {confirmDialogType === 'delete' ? '确认删除' : '确认停止'}
            </h4>
            <p style={{ margin: '0 0 20px 0', fontSize: '14px', color: '#666' }}>
              {confirmDialogType === 'delete' 
                ? '确定要删除此任务吗？此操作无法撤销。' 
                : '确定要停止此任务吗？已处理的数据可能不会被保存。'}
            </p>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                onClick={cancelAction}
                style={{
                  padding: '8px 16px',
                  fontSize: '14px',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  backgroundColor: '#fff',
                  cursor: 'pointer'
                }}
              >
                取消
              </button>
              <button
                onClick={confirmAction}
                style={{
                  padding: '8px 16px',
                  fontSize: '14px',
                  border: 'none',
                  borderRadius: '4px',
                  backgroundColor: confirmDialogType === 'delete' ? '#dc3545' : '#ffc107',
                  color: confirmDialogType === 'delete' ? '#fff' : '#333',
                  cursor: 'pointer'
                }}
              >
                {confirmDialogType === 'delete' ? '确认删除' : '确认停止'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TaskList;
