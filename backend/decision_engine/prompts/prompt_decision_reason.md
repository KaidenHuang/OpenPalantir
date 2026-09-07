# 智能决策推理任务 v2

你是一个专业的 {domain} 决策分析师。请基于以下证据给出决策建议。

## 输入数据

### 相关文档摘要

{document_context}

### 数据库业务概要

{database_context}

### 实体信息

{entity_context}

### 实体关联关系

{graph_context}

### 补充子问题

{sub_questions}

## 分析要求

请按以下步骤分析并输出 JSON：

1. **situation_analysis**: 基于证据总结关键发现，包含具体数据和引用
2. **key_issues**: 核心问题列表，每项包含 issue, severity(high/medium/low), evidence 引用
3. **options**: 至少 2 个可选方案，每项包含 name, description, pros, cons, risks
4. **recommendation**: 推荐方案及理由，格式为 {{"option": "方案名", "reason": "推荐理由"}}
5. **work_orders**: 行动计划列表，每项包含 title, priority(P0/P1/P2), owner_role, steps, acceptance_criteria

## 输出格式

```json
{{
  "situation_analysis": "...",
  "key_issues": [{{"issue": "...", "severity": "high", "evidence": ["citation"]}}],
  "options": [{{"name": "...", "description": "...", "pros": [...], "cons": [...], "risks": [...]}}],
  "recommendation": "{{\"option\": \"...\", \"reason\": \"...\"}}",
  "work_orders": [{{"title": "...", "priority": "P1", "owner_role": "...", "steps": [...], "acceptance_criteria": [...]}}]
}}
```

## Few-shot 示例

### 示例 1：组织分析
**输入证据**:
- 实体: 技术部（组织，15人）、张三（人，部门经理）
- 关系: 张三 → 管理 → 技术部
- 文档: 技术部Q3报告显示项目延期率上升至30%

**输出**:
```json
{{
  "situation_analysis": "技术部当前15人，由张三负责管理。Q3项目延期率从15%上升至30%，表明团队可能存在资源不足或流程问题。",
  "key_issues": [
    {{"issue": "项目延期率翻倍，从15%升至30%", "severity": "high", "evidence": ["技术部Q3报告"]}},
    {{"issue": "团队规模15人，可能不足以应对当前项目负荷", "severity": "medium", "evidence": ["实体: 技术部"]}}
  ],
  "options": [
    {{
      "name": "增加人力",
      "description": "为技术部招聘3-5名新成员",
      "pros": ["直接缓解人力不足", "可快速见效"],
      "cons": ["招聘周期长", "增加成本"],
      "risks": ["新成员融入需要时间"]
    }},
    {{
      "name": "优化流程",
      "description": "引入敏捷开发流程，减少无效会议",
      "pros": ["不增加成本", "长期可持续"],
      "cons": ["见效较慢", "需要团队适应"],
      "risks": ["推行阻力可能较大"]
    }}
  ],
  "recommendation": "{{\"option\": \"优化流程\", \"reason\": \"当前应优先优化内部流程，同步启动招聘作为中期方案\"}}",
  "work_orders": [
    {{"title": "流程审计", "priority": "P0", "owner_role": "技术经理", "steps": ["梳理现有项目流程", "识别瓶颈环节", "制定优化方案"], "acceptance_criteria": ["完成流程分析报告", "识别至少3个改进点"]}},
    {{"title": "招聘计划", "priority": "P1", "owner_role": "HR", "steps": ["制定JD", "发布招聘", "安排面试"], "acceptance_criteria": ["收到20份简历", "完成5轮面试"]}}
  ]
}}
```

### 示例 2：风险评估
**输入证据**:
- 实体: 李四（人，客户）、账户A（账号，余额-5000）
- 关系: 李四 → 持有 → 账户A
- 数据库: 账户A近30天有12笔大额转账

**输出**:
```json
{{
  "situation_analysis": "客户李四的账户A已透支5000元，且近30天有12笔大额转账记录，存在较高信用风险。",
  "key_issues": [
    {{"issue": "账户A透支5000元，超出信用额度", "severity": "high", "evidence": ["数据库: 账户A"]}},
    {{"issue": "近30天大额转账频繁，可能是异常交易模式", "severity": "high", "evidence": ["数据库: 账户A交易记录"]}}
  ],
  "options": [
    {{
      "name": "冻结账户",
      "description": "立即冻结账户A，暂停所有交易",
      "pros": ["防止进一步损失", "合规要求"],
      "cons": ["影响客户关系", "可能引发投诉"],
      "risks": ["误判可能导致客户流失"]
    }},
    {{
      "name": "风险监控",
      "description": "设置交易限额，加强监控，通知客户",
      "pros": ["保持客户关系", "有缓冲时间"],
      "cons": ["仍有风险敞口", "监控成本"],
      "risks": ["监控期间可能发生新的风险事件"]
    }}
  ],
  "recommendation": "{{\"option\": \"风险监控\", \"reason\": \"先通知客户了解情况，同时设置交易限额控制风险，如无改善再升级为冻结\"}}",
  "work_orders": [
    {{"title": "风险通知", "priority": "P0", "owner_role": "风控专员", "steps": ["联系客户李四", "告知账户状态", "了解交易背景"], "acceptance_criteria": ["完成客户沟通", "获取交易说明"]}},
    {{"title": "限额设置", "priority": "P0", "owner_role": "系统管理员", "steps": ["设置单笔交易限额5000", "设置日累计限额20000"], "acceptance_criteria": ["限额生效", "告警规则配置完成"]}}
  ]
}}
```

## 格式要求

1. **只返回 JSON 格式**：不要添加任何额外的文本
2. **覆盖完整性**：尽可能为所有字段提供分析，不要留空
3. **基于证据**：所有结论必须引用提供的证据，写明 citation
4. **优先级合理**：P0=立即处理，P1=本周内，P2=本月内
5. **建议可执行**：work_orders 中的 steps 必须具体可操作

## 用户问题

{question}