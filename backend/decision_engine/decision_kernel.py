from decision_engine.contracts import DecisionRequest, DecisionResponse
from decision_engine.plugin_registry import plugin_registry
from system.logger import logger


class DecisionKernel:
    def run(self, request: DecisionRequest) -> DecisionResponse:
        domain = request.domain or "workforce"
        plugin = plugin_registry.resolve(domain)

        logger.info(f"[kernel] run domain={domain}, session_id={request.session_id}, question={request.question[:60]}")

        result = plugin.run(request)

        return DecisionResponse(**result)


decision_kernel = DecisionKernel()
