from decision_engine.plugins.base_decision_plugin import BaseDecisionPlugin


class WorkforcePlugin(BaseDecisionPlugin):
    domain = "workforce"
    system_prompt_extra = """
你专注于人力资源与组织管理分析。关注：
- 组织架构合理性（管理跨度、层级深度）
- 人才梯队健康度（关键岗位覆盖率、继任计划）
- 薪酬竞争力（内部公平性、外部对标）
- 人员流失风险（关键人员留存、离职率）
"""
