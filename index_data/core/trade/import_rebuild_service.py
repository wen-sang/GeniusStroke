"""
账户导入重建服务

将历史文件导入 + 当前状态重算 + 历史收益重算封装为正式服务，
供 API 管理接口和脚本共用。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from core.trade.import_rebuild_runtime import AccountImportRebuilder, DEFAULT_CONFIG, merge_config


class AccountImportRebuildService:
    """导入历史文件并重建账户。"""

    def build_config(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = deepcopy(DEFAULT_CONFIG)
        if not overrides:
            return config

        filtered_overrides = {key: value for key, value in overrides.items() if value is not None}
        merge_config(config, filtered_overrides)
        return config

    def rebuild_from_imports(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = self.build_config(overrides)
        config["skip_confirmation"] = True
        rebuilder = AccountImportRebuilder(config)
        return rebuilder.run()

    def preview_from_imports(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = self.build_config(overrides)
        rebuilder = AccountImportRebuilder(config)
        preview = rebuilder.build_preview()
        return {
            "success": True,
            "cancelled": False,
            "account_id": None,
            "preview": preview,
            "current_summary": {},
            "history_summary": {},
        }


account_import_rebuild_service = AccountImportRebuildService()
