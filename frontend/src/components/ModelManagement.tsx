import React, { useState, useEffect, useMemo } from 'react';
import { Input, Button, Select, message, Modal, Form, Spin } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { API_CONFIG } from '../config/apiConfig';
import { httpGet, httpPost } from '../services/httpClient';
import { useModelStore } from '../stores/modelStore';
import { useAbortController } from '../hooks/useAbortController';

const { Option } = Select;

interface ModelPlatform {
  id: string;
  name: string;
  status: 'available' | 'unavailable' | 'unknown';
  type: 'local' | 'cloud';
  enabled: boolean;
}

interface PlatformConfig {
  apiUrl: string;
  apiKey: string;
  model: string;
}

const ModelManagement: React.FC = () => {
  const { fetchPlatforms, fetchOllamaModels: storeFetchOllama, createModel: storeCreateModel, updateModel: storeUpdateModel } = useModelStore();

  // 直接从 store 订阅，消除双重状态
  const storeModels = useModelStore((s) => s.models);
  const ollamaModels = useModelStore((s) => s.ollamaModels);

  const { getComponentSignal, getLatestSignal } = useAbortController();

  const [searchText, setSearchText] = useState('');
  const [config, setConfig] = useState<PlatformConfig>({
    apiUrl: 'https://api.openai.com/v1',
    apiKey: '',
    model: 'gpt-4'
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [selectedPlatform, setSelectedPlatform] = useState<string>('');
  const [isAddModalVisible, setIsAddModalVisible] = useState(false);
  const [newModelName, setNewModelName] = useState('');
  const [newModelType, setNewModelType] = useState<'local' | 'cloud'>('cloud');

  // 从 store 的 models 派生出 UI 用的 platforms 列表
  const platforms = useMemo(() => {
    return storeModels
      .map((model) => ({
        id: model.name.toLowerCase(),
        name: model.name,
        status: (model as unknown as Record<string, unknown>).status as ModelPlatform['status'] || 'unknown',
        type: model.model_type as ModelPlatform['type'],
        enabled: model.enabled,
      }))
      .sort((a, b) => (b.enabled ? 1 : 0) - (a.enabled ? 1 : 0));
  }, [storeModels]);

  // 页面加载时从后端API加载模型列表
  useEffect(() => {
    const signal = getComponentSignal();
    loadModelsFromBackend(signal);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 当选择平台变化时，更新配置
  useEffect(() => {
    if (selectedPlatform) {
      updateConfigForPlatform(selectedPlatform);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPlatform]);

  // 当选择Ollama平台时，获取模型列表
  useEffect(() => {
    if (selectedPlatform === 'ollama') {
      const signal = getLatestSignal('ollama');
      fetchOllamaModels(signal);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPlatform, config.apiUrl]);

  // 获取Ollama模型列表
  const fetchOllamaModels = async (signal?: AbortSignal) => {
    try {
      const ollamaConfig = storeModels.find(m => m.name.toLowerCase() === 'ollama');
      const apiUrl = ollamaConfig?.api_url ? ollamaConfig.api_url : 'http://localhost:11434';
      let validApiUrl = apiUrl;
      if (!validApiUrl.startsWith('http://') && !validApiUrl.startsWith('https://')) {
        validApiUrl = `http://${validApiUrl}`;
      }
      await storeFetchOllama(validApiUrl, signal);
    } catch {
      // store 会保留旧数据
    }
  };

  // 从后端API加载模型列表
  const loadModelsFromBackend = async (signal?: AbortSignal) => {
    try {
      setInitialLoading(true);
      await fetchPlatforms(signal);
      // platforms 由 useMemo 自动从 storeModels 派生
      if (platforms.length > 0 && !selectedPlatform) {
        setSelectedPlatform(platforms[0].id);
      }
    } catch {
      message.error('加载模型列表失败');
      setSelectedPlatform('openai');
    } finally {
      setInitialLoading(false);
    }
  };

  // 根据选择的平台更新配置
  const updateConfigForPlatform = (platformId: string) => {
    const platform = storeModels.find(m => m.name.toLowerCase() === platformId);
    if (platform) {
      setConfig({
        apiUrl: platform.api_url || '',
        apiKey: platform.api_key || '',
        model: platform.models?.[0] || ''
      });
    }
  };

  // 处理平台选择
  const handlePlatformSelect = (platformId: string) => {
    setSelectedPlatform(platformId);
  };

  // 处理配置变更
  const handleConfigChange = (key: keyof PlatformConfig, value: string) => {
    setConfig(prev => ({
      ...prev,
      [key]: value
    }));
  };

  // 保存配置
  const handleSaveConfig = async () => {
    if (!selectedPlatform) {
      message.error('请选择一个平台');
      return;
    }

    setSaving(true);
    try {
      // 找到对应的模型
      const platform = storeModels.find(m => m.name.toLowerCase() === selectedPlatform);
      if (!platform) {
        message.error('平台不存在');
        return;
      }

      // 先测试连接状态
      let status = 'unknown';
      
      if (selectedPlatform === 'ollama') {
        try {
          const signal = getComponentSignal();
          const response = await httpGet(`${config.apiUrl}/api/tags`, { signal });
          status = response.status === 200 ? 'available' : 'unavailable';
        } catch {
          status = 'unavailable';
        }
      } else {
        // 对于云端模型，简单检查API地址和密钥
        if (!config.apiKey) {
          message.error('请输入API密钥');
          setSaving(false);
          return;
        }
        status = 'available'; // 简化处理，实际应该调用API测试
      }

      // 更新模型配置
      await storeUpdateModel(platform.id, {
        api_url: config.apiUrl,
        api_key: config.apiKey,
        models: [config.model],
        status
      });

      message.success('配置保存成功');
      loadModelsFromBackend(getComponentSignal());
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string };
      message.error(`配置保存失败: ${err.response?.data?.detail || err.message || '未知错误'}`);
      console.error('Failed to save config:', error);
    } finally {
      setSaving(false);
    }
  };

  // 刷新模型状态
  const handleRefresh = () => {
    useModelStore.setState({ _lastFetched: 0 });
    loadModelsFromBackend(getComponentSignal());
  };

  // 打开添加模型模态框
  const handleAddModel = () => {
    setIsAddModalVisible(true);
  };

  // 关闭添加模型模态框
  const handleCancelAddModel = () => {
    setIsAddModalVisible(false);
    setNewModelName('');
    setNewModelType('cloud');
  };

  // 提交添加模型
  const handleSubmitAddModel = async () => {
    if (!newModelName) {
      message.error('请输入模型名称');
      return;
    }
    
    try {
      await storeCreateModel(newModelName, newModelType, getComponentSignal());

      message.success('模型添加成功');
      setIsAddModalVisible(false);
      setNewModelName('');
      setNewModelType('cloud');
      loadModelsFromBackend(getComponentSignal());
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string };
      message.error(`模型添加失败: ${err.response?.data?.detail || err.message || '未知错误'}`);
      console.error('Failed to add model:', error);
    }
  };

  // 测试连接
  const handleTestConnection = async () => {
    if (!selectedPlatform) {
      message.error('请选择一个平台');
      return;
    }

    setLoading(true);
    try {
      // 找到对应的模型
      const platform = storeModels.find(m => m.name.toLowerCase() === selectedPlatform);
      if (!platform) {
        message.error('平台不存在');
        return;
      }

      // 调用后端测试连接接口
      const signal = getComponentSignal();
      const response = await httpPost(API_CONFIG.endpoints.model.testConnection(platform.id), {
        api_url: config.apiUrl,
        api_key: config.apiKey,
        model: config.model
      }, { signal });

      if (response.data.status === 'success') {
        message.success(response.data.message);
      } else {
        message.error(response.data.message || '测试连接失败');
      }
      // 无论测试结果如何，都刷新模型列表以更新状态
      loadModelsFromBackend(getComponentSignal());
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string };
      message.error(`连接测试失败: ${err.response?.data?.detail || err.message || '未知错误'}`);
      console.error('Failed to test connection:', error);
    } finally {
      setLoading(false);
    }
  };

  // 启用模型
  const handleEnableModel = async (modelId: number) => {
    try {
      const signal = getComponentSignal();
      const response = await httpPost(API_CONFIG.endpoints.model.enable(modelId), undefined, { signal });
      if (response.data.status === 'success') {
        message.success(response.data.message);
        useModelStore.setState({ _lastFetched: 0 });
        loadModelsFromBackend(getComponentSignal());
      } else {
        message.error('启用失败');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string };
      message.error(`启用失败: ${err.response?.data?.detail || err.message || '未知错误'}`);
      console.error('Failed to enable model:', error);
    }
  };

  // 过滤平台列表
  const filteredPlatforms = platforms.filter(platform => 
    platform.name.toLowerCase().includes(searchText.toLowerCase())
  );

  return (
    <div className="model-management" style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Oxygen, Ubuntu, Cantarell, Fira Sans, Droid Sans, Helvetica Neue, sans-serif'
    }}>
      {initialLoading ? (
        <div style={{
          flex: 1,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          fontSize: '16px',
          color: '#666'
        }}>
          <Spin size="large" />
          <span style={{ marginLeft: '12px' }}>加载中...</span>
        </div>
      ) : (
        <>
          {/* 顶部操作栏 */}
          <div style={{
            display: 'flex',
            gap: '16px',
            marginTop: '-5px',
            marginBottom: '-10px',
            alignItems: 'center'
          }}>
            <Button type="primary" onClick={handleAddModel} style={{ borderRadius: 6 }}>添加</Button>
            <Button icon={<ReloadOutlined />} onClick={handleRefresh} style={{ borderRadius: 6 }}>刷新</Button>
            <Input
              placeholder="输入名称搜索"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: '300px', borderRadius: 6 }}
            />
          </div>

          <div style={{
            display: 'flex',
            gap: '20px',
            flex: 1
          }}>
            {/* 左侧平台列表 */}
            <div style={{
              width: '200px',
              border: '1px solid #e8e8e8',
              borderRadius: 8,
              padding: '16px',
              backgroundColor: '#ffffff'
            }}>
              {filteredPlatforms.map(platform => {
                const model = storeModels.find(m => m.name.toLowerCase() === platform.id);
                return (
                  <div
                    key={platform.id}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      padding: '10px',
                      marginBottom: '8px',
                      borderRadius: 6,
                      backgroundColor: platform.id === selectedPlatform ? '#e6f7ff' : '#ffffff',
                      border: platform.enabled
                        ? '2px solid #52c41a'
                        : platform.id === selectedPlatform
                          ? '1px solid #1890ff'
                          : '1px solid #e8e8e8',
                      cursor: 'pointer',
                      transition: 'all 0.3s ease'
                    }}
                    onClick={() => handlePlatformSelect(platform.id)}
                  >
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      width: '100%'
                    }}>
                      <span style={{
                        fontWeight: platform.id === selectedPlatform ? '600' : '400',
                        color: platform.id === selectedPlatform ? '#1890ff' : '#333333',
                        flex: 1,
                        fontSize: '14px'
                      }}>{platform.name}</span>
                      <span style={{
                        fontSize: '12px',
                        padding: '2px 8px',
                        borderRadius: 10,
                        backgroundColor: platform.status === 'available' ? '#f6ffed' : platform.status === 'unavailable' ? '#fff1f0' : '#f7f7f7',
                        color: platform.status === 'available' ? '#52c41a' : platform.status === 'unavailable' ? '#ff4d4f' : '#8c8c8c'
                      }}>
                        {platform.status === 'available' ? '可用' : platform.status === 'unavailable' ? '不可用' : '未知'}
                      </span>
                    </div>
                    <div style={{ marginTop: 6, display: 'flex', gap: 6 }}>
                      {platform.enabled ? (
                        <span style={{
                          fontSize: '12px',
                          color: '#52c41a',
                          fontWeight: 500,
                          display: 'flex',
                          alignItems: 'center',
                          gap: 4
                        }}>
                          已启用
                        </span>
                      ) : (
                        <Button
                          size="small"
                          type="link"
                          style={{ padding: 0, fontSize: '12px', height: 'auto' }}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (model) handleEnableModel(model.id);
                          }}
                          disabled={platform.status !== 'available'}
                        >
                          启用
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* 右侧配置区域 */}
            <div style={{
              flex: 1,
              border: '1px solid #e8e8e8',
              borderRadius: 8,
              padding: '24px',
              backgroundColor: '#ffffff'
            }}>
              <div style={{ marginBottom: '20px' }}>
                <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '600', color: '#262626' }}>API配置</h3>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500', color: '#333' }}>API地址</label>
                <Input
                  value={config.apiUrl}
                  onChange={(e) => handleConfigChange('apiUrl', e.target.value)}
                  style={{ width: '100%', borderRadius: 6 }}
                />
              </div>

              {selectedPlatform !== 'ollama' && (
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500', color: '#333' }}>API密钥</label>
                  <Input.Password
                    value={config.apiKey}
                    onChange={(e) => handleConfigChange('apiKey', e.target.value)}
                    style={{ width: '100%', borderRadius: 6 }}
                  />
                </div>
              )}

              <div style={{ marginBottom: '30px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500', color: '#333' }}>模型选择</label>
                <Select
                  value={config.model}
                  onChange={(value) => handleConfigChange('model', value)}
                  style={{ width: '100%', borderRadius: 6 }}
                  showSearch
                  allowClear
                  filterOption={false}
                  onSearch={(inputValue) => {
                    // 当用户输入时，不触发搜索，直接使用输入值
                    if (inputValue) {
                      handleConfigChange('model', inputValue);
                    }
                  }}
                >
                  {selectedPlatform === 'openai' && (
                    <>
                      <Option value="gpt-4">GPT-4</Option>
                      <Option value="gpt-3.5-turbo">GPT-3.5 Turbo</Option>
                      <Option value="gpt-4o">GPT-4o</Option>
                    </>
                  )}
                  {selectedPlatform === 'ollama' && (
                    <>
                      {ollamaModels.length > 0 ? (
                        ollamaModels.map(model => (
                          <Option key={model} value={model}>{model}</Option>
                        ))
                      ) : (
                        <Option value="llama3">Llama 3</Option>
                      )}
                    </>
                  )}
                  {selectedPlatform === 'deepseek' && (
                    <>
                      <Option value="deepseek-v4-flash">DeepSeek V4 Flash</Option>
                      <Option value="deepseek-v4-pro">DeepSeek V4 Pro</Option>
                    </>
                  )}
                </Select>
              </div>

              <div style={{ display: 'flex', gap: '12px' }}>
                <Button
                  onClick={handleTestConnection}
                  loading={loading}
                  style={{ borderRadius: 6 }}
                >
                  连接测试
                </Button>
                <Button
                  type="primary"
                  onClick={handleSaveConfig}
                  loading={saving}
                  style={{ borderRadius: 6 }}
                >
                  保存配置
                </Button>
              </div>
            </div>
          </div>

          {/* 添加模型模态框 */}
          <Modal
            title="添加模型"
            open={isAddModalVisible}
            onOk={handleSubmitAddModel}
            onCancel={handleCancelAddModel}
          >
            <Form layout="vertical">
              <Form.Item label="模型名称">
                <Input
                  value={newModelName}
                  onChange={(e) => setNewModelName(e.target.value)}
                  placeholder="请输入模型名称"
                />
              </Form.Item>
              <Form.Item label="模型类型">
                <Select
                  value={newModelType}
                  onChange={(value) => setNewModelType(value)}
                >
                  <Option value="cloud">云端</Option>
                  <Option value="local">本地</Option>
                </Select>
              </Form.Item>
            </Form>
          </Modal>
        </>
      )}
    </div>
  );
};

export default ModelManagement;
