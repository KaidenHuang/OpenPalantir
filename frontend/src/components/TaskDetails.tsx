import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_CONFIG } from '../config/apiConfig';

interface Task {
  task_id: string;
  task_type: string;
  status: string;
  payload: any;
  result: any;
  progress: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

interface TaskDetailsProps {
  taskId: string | null;
}

const TaskDetails: React.FC<TaskDetailsProps> = ({ taskId }) => {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (taskId) {
      fetchTaskDetails();
    }
  }, [taskId]);

  const fetchTaskDetails = async () => {
    if (!taskId) return;
    
    try {
      setLoading(true);
      const response = await axios.get(API_CONFIG.endpoints.task.get(taskId));
      setTask(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to fetch task details');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const getTaskTypeLabel = (type: string): string => {
    switch (type) {
      case 'relationship_extraction':
        return '关系提取';
      case 'document_upload':
        return '文档上传';
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
      default:
        return '';
    }
  };

  if (!taskId) {
    return (
      <div className="task-details">
        <h3>任务详情</h3>
        <div className="no-task-selected">请选择一个任务查看详情</div>
      </div>
    );
  }

  return (
    <div className="task-details">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h3>任务详情</h3>
        <button 
          className="btn btn-primary" 
          onClick={fetchTaskDetails}
          style={{ padding: '8px 16px', fontSize: '14px' }}
        >
          刷新
        </button>
      </div>
      {loading ? (
        <div className="loading">加载中...</div>
      ) : error ? (
        <div className="error">{error}</div>
      ) : task ? (
        <div className="task-details-content">
          <div className="task-info">
            <div className="info-item">
              <span className="label">任务 ID:</span>
              <span className="value">{task.task_id}</span>
            </div>
            <div className="info-item">
              <span className="label">任务类型:</span>
              <span className="value">{getTaskTypeLabel(task.task_type)}</span>
            </div>
            <div className="info-item">
              <span className="label">状态:</span>
              <span className={`status-badge ${getStatusClass(task.status)}`}>
                {task.status === 'pending' && '待处理'}
                {task.status === 'running' && '运行中'}
                {task.status === 'completed' && '已完成'}
                {task.status === 'failed' && '失败'}
              </span>
            </div>
            <div className="info-item">
              <span className="label">进度:</span>
              <span className="value">
                {task.status === 'running' ? `${task.progress}%` : '-'}
              </span>
            </div>
            <div className="info-item">
              <span className="label">创建时间:</span>
              <span className="value">{new Date(task.created_at).toLocaleString()}</span>
            </div>
            <div className="info-item">
              <span className="label">开始时间:</span>
              <span className="value">{task.started_at ? new Date(task.started_at).toLocaleString() : '-'}</span>
            </div>
            <div className="info-item">
              <span className="label">完成时间:</span>
              <span className="value">{task.completed_at ? new Date(task.completed_at).toLocaleString() : '-'}</span>
            </div>
          </div>
          
          {task.status === 'failed' && task.error && (
            <div className="task-error">
              <h4>错误信息:</h4>
              <pre>{task.error}</pre>
            </div>
          )}
          
          {task.result && (
            <div className="task-result">
              <h4>任务结果:</h4>
              <pre>{JSON.stringify(task.result, null, 2)}</pre>
            </div>
          )}
        </div>
      ) : (
        <div className="no-task-found">任务不存在</div>
      )}
    </div>
  );
};

export default TaskDetails;