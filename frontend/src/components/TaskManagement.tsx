import React, { useEffect } from 'react';
import TaskList from './TaskList';
import { logger } from '../services/logger';

const TaskManagement: React.FC = () => {
  useEffect(() => {
    logger.info('TaskManagement', '任务管理组件挂载');
    return () => {
      logger.info('TaskManagement', '任务管理组件卸载');
    };
  }, []);

  return (
    <div className="task-management">
      <div className="task-list-section">
        <TaskList />
      </div>
    </div>
  );
};

export default TaskManagement;