import React, { useState } from 'react';
import axios from 'axios';
import { API_CONFIG } from '../config/apiConfig';

interface TaskCreationProps {
  onTaskCreated: () => void;
}

const TaskCreation: React.FC<TaskCreationProps> = ({ onTaskCreated }) => {
  const [taskType, setTaskType] = useState('relationship_extraction');
  const [payload, setPayload] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleTaskTypeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setTaskType(e.target.value);
    // 重置 payload 为对应任务类型的默认值
    switch (e.target.value) {
      case 'relationship_extraction':
        setPayload({
          document_id: '',
          content: '',
          entities: []
        });
        break;
      case 'document_upload':
        setPayload({
          title: '',
          content: '',
          metadata: {}
        });
        break;
      default:
        setPayload({});
    }
  };

  const handlePayloadChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setPayload(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    try {
      setLoading(true);
      setError(null);
      setSuccess(null);
      
      const response = await axios.post(API_CONFIG.endpoints.task.create, {
        task_type: taskType,
        payload
      });
      
      setSuccess(`任务创建成功！任务 ID: ${response.data.task_id}`);
      onTaskCreated();
      
      // 重置表单
      switch (taskType) {
        case 'relationship_extraction':
          setPayload({
            document_id: '',
            content: '',
            entities: []
          });
          break;
        case 'document_upload':
          setPayload({
            title: '',
            content: '',
            metadata: {}
          });
          break;
        default:
          setPayload({});
      }
    } catch (err) {
      setError('任务创建失败');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="task-creation">
      <h3>创建任务</h3>
      <form onSubmit={handleSubmit} className="task-form">
        <div className="form-group">
          <label htmlFor="taskType">任务类型</label>
          <select 
            id="taskType" 
            value={taskType} 
            onChange={handleTaskTypeChange}
            className="form-control"
          >
            <option value="relationship_extraction">关系提取</option>
            <option value="document_upload">文档上传</option>
          </select>
        </div>
        
        {taskType === 'relationship_extraction' && (
          <>
            <div className="form-group">
              <label htmlFor="documentId">文档 ID</label>
              <input 
                type="text" 
                id="documentId" 
                name="document_id" 
                value={payload.document_id || ''} 
                onChange={handlePayloadChange}
                className="form-control"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="content">文档内容</label>
              <textarea 
                id="content" 
                name="content" 
                value={payload.content || ''} 
                onChange={handlePayloadChange}
                className="form-control"
                rows={4}
                required
              ></textarea>
            </div>
          </>
        )}
        
        {taskType === 'document_upload' && (
          <>
            <div className="form-group">
              <label htmlFor="title">文档标题</label>
              <input 
                type="text" 
                id="title" 
                name="title" 
                value={payload.title || ''} 
                onChange={handlePayloadChange}
                className="form-control"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="content">文档内容</label>
              <textarea 
                id="content" 
                name="content" 
                value={payload.content || ''} 
                onChange={handlePayloadChange}
                className="form-control"
                rows={4}
                required
              ></textarea>
            </div>
          </>
        )}
        
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? '创建中...' : '创建任务'}
        </button>
        
        {error && <div className="error-message">{error}</div>}
        {success && <div className="success-message">{success}</div>}
      </form>
    </div>
  );
};

export default TaskCreation;