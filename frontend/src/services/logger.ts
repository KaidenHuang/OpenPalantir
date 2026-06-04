export enum LogLevel {
  DEBUG = 'debug',
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  CRITICAL = 'critical'
}

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  module: string;
  message: string;
  details?: any;
}

class Logger {
  private static instance: Logger;
  private logLevel: LogLevel;
  private maxDays: number;
  
  private constructor() {
    // 从localStorage读取日志级别，默认为INFO
    const storedLevel = localStorage.getItem('logLevel');
    this.logLevel = storedLevel as LogLevel || LogLevel.INFO;
    this.maxDays = 7; // 保留最近7天的日志
    this.cleanupOldLogs();
  }
  
  public static getInstance(): Logger {
    if (!Logger.instance) {
      Logger.instance = new Logger();
    }
    return Logger.instance;
  }
  
  private getCurrentLogKey(): string {
    const today = new Date();
    const dateStr = today.toISOString().split('T')[0];
    return `log-${dateStr}`;
  }
  
  private getLogKeyForDate(date: Date): string {
    const dateStr = date.toISOString().split('T')[0];
    return `log-${dateStr}`;
  }
  
  private cleanupOldLogs(): void {
    const today = new Date();
    const cutoffDate = new Date(today);
    cutoffDate.setDate(today.getDate() - this.maxDays);
    
    // 遍历localStorage中的所有键
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('log-')) {
        const dateStr = key.replace('log-', '');
        const logDate = new Date(dateStr);
        if (logDate < cutoffDate) {
          localStorage.removeItem(key);
        }
      }
    }
  }
  
  private addLogEntry(level: LogLevel, module: string, message: string, details?: any): void {
    // 检查日志级别
    const levelOrder = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL];
    if (levelOrder.indexOf(level) < levelOrder.indexOf(this.logLevel)) {
      return;
    }
    
    const logEntry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      module,
      message,
      details
    };
    
    const logKey = this.getCurrentLogKey();
    const existingLogs = localStorage.getItem(logKey);
    const logs = existingLogs ? JSON.parse(existingLogs) : [];
    
    logs.push(logEntry);
    
    // 限制每个日志文件的大小
    if (logs.length > 1000) {
      logs.shift(); // 删除最旧的日志
    }
    
    try {
      localStorage.setItem(logKey, JSON.stringify(logs));
    } catch (e) {
      // 如果localStorage容量不足，删除最旧的日志
      this.cleanupOldLogs();
      try {
        localStorage.setItem(logKey, JSON.stringify(logs));
      } catch (e) {
        // 如果仍然失败，只保留最近的100条日志
        const recentLogs = logs.slice(-100);
        localStorage.setItem(logKey, JSON.stringify(recentLogs));
      }
    }
  }
  
  public setLogLevel(level: LogLevel): void {
    this.logLevel = level;
    localStorage.setItem('logLevel', level);
  }
  
  public getLogLevel(): LogLevel {
    return this.logLevel;
  }
  
  public debug(module: string, message: string, details?: any): void {
    this.addLogEntry(LogLevel.DEBUG, module, message, details);
  }
  
  public info(module: string, message: string, details?: any): void {
    this.addLogEntry(LogLevel.INFO, module, message, details);
  }
  
  public warning(module: string, message: string, details?: any): void {
    this.addLogEntry(LogLevel.WARNING, module, message, details);
  }
  
  public error(module: string, message: string, details?: any): void {
    this.addLogEntry(LogLevel.ERROR, module, message, details);
  }
  
  public critical(module: string, message: string, details?: any): void {
    this.addLogEntry(LogLevel.CRITICAL, module, message, details);
  }
  
  public getLogsForDate(date: Date): LogEntry[] {
    const logKey = this.getLogKeyForDate(date);
    const logs = localStorage.getItem(logKey);
    return logs ? JSON.parse(logs) : [];
  }
  
  public getAllLogs(): LogEntry[] {
    const allLogs: LogEntry[] = [];
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('log-')) {
        const logs = localStorage.getItem(key);
        if (logs) {
          allLogs.push(...JSON.parse(logs));
        }
      }
    }
    
    // 按时间排序
    return allLogs.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }
  
  public clearLogs(): void {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('log-')) {
        localStorage.removeItem(key);
      }
    }
  }
}

// 创建全局日志实例
export const logger = Logger.getInstance();
