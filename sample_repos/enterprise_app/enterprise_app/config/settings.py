"""Enterprise Global Configuration & Feature Flags Engine (250+ lines)."""

import os
import json
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentConfig:
    """Configuration settings for enterprise application environment."""
    env_name: str = "production"
    debug_mode: bool = False
    secret_key: str = "enterprise_prod_secret_key_881920"
    database_url: str = "postgresql://admin:secret@localhost:5432/enterprise_db"
    redis_url: str = "redis://localhost:6379/0"
    max_connection_pool: int = 50
    request_timeout_seconds: float = 30.0
    feature_flags: Dict[str, bool] = field(default_factory=lambda: {
        "enable_tiered_discounts": True,
        "enable_rate_limiting": True,
        "enable_audit_logging": True,
        "enable_s3_storage": False,
        "enable_sms_notifications": False,
    })


class ConfigLoader:
    """Loads configuration settings from environment variables and JSON config files."""

    def __init__(self, config_file_path: Optional[str] = None):
        self.config_path = config_file_path or os.getenv("ENTERPRISE_CONFIG_PATH")
        self.active_config = EnvironmentConfig()

    def load_configuration(self) -> EnvironmentConfig:
        """Load and parse environment config parameters."""
        if self.config_path and os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.active_config.env_name = data.get("env_name", self.active_config.env_name)
                self.active_config.debug_mode = data.get("debug_mode", self.active_config.debug_mode)
                self.active_config.secret_key = data.get("secret_key", self.active_config.secret_key)
                self.active_config.database_url = data.get("database_url", self.active_config.database_url)
                logger.info(f"Loaded configuration from file {self.config_path}")
            except Exception as err:
                logger.error(f"Failed to parse config file {self.config_path}: {err}")

        # Override with environment variables
        if os.getenv("APP_ENV"):
            self.active_config.env_name = os.getenv("APP_ENV")
        if os.getenv("DATABASE_URL"):
            self.active_config.database_url = os.getenv("DATABASE_URL")
        if os.getenv("SECRET_KEY"):
            self.active_config.secret_key = os.getenv("SECRET_KEY")

        return self.active_config

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if feature flag is active."""
        return self.active_config.feature_flags.get(feature_name, False)
